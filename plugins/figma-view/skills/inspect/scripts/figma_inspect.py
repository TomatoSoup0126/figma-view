"""Read a Figma layer's specs (size, typography, colors) and a screenshot from Figma's view-only web UI.

    uv run --project "$JEV_DIR" python figma_inspect.py --tab-token T [--find "<request>"] [--out DIR]

Without --find: reads the node the tab's `?node-id=` URL selected. No model is involved.
With --find: names quoted in 「」 are searched across all pages first; Jev picks among the results (it only
selects, never writes a query) and the walk continues from the chosen layer. Otherwise, or if that branch
fails, the walk starts from the page Jev picks. Code owns the tree walk: it expands one node at a time and
lists only that node's direct children; Jev answers one narrow question per level (which child leads to
the requested layer, and is the current node itself the answer). Layer names that say nothing (Frame 123)
get a preview of their children. Page/layer names and the request are sent to TypeSafe. Nothing in the
file is edited.
"""

import argparse
import json
import os
import re
import tempfile
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.environ.get("JEV_DIR") or str(Path.home() / ".cache/jev-ultrafast"))
from jev_ultrafast.model import CLIENT, validate_choice  # noqa: E402

from fbrowser import FigmaTab  # noqa: E402
from figma_panels import EXTRACT, capture, layer_size, open_properties  # noqa: E402

HERE = Path(__file__).parent
TREE = (HERE / "figma_tree.js").read_text()
MAX_CHILDREN = 150  # a Choice over more options than this gets split into pages of candidates later
MAX_DEPTH = 15
MAX_BACKTRACKS = 3
NONE_THRESHOLD = 0.6
TALL_VIEWPORT = 4000
HERE_THRESHOLD = 0.6


class Tree:
    def __init__(self, tab):
        self.tab = tab

    def js(self, expr):
        self.tab.js(TREE)  # idempotent; the document may have been replaced
        return self.tab.js(f"window.__figTree.{expr}")

    def frame(self):
        self.tab.js("new Promise(r => { requestAnimationFrame(() => requestAnimationFrame(r)); setTimeout(r, 150); })",
                    await_promise=True)

    def wait(self, expr, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.js(expr):
                    return True
            except RuntimeError:
                pass
            time.sleep(0.1)
        return False

    def collapse_all(self):
        self.tab.key("Escape", "Escape", vk=27)  # deselect, so selected ancestors do not stay open
        # Alt+L collapses all layers. Send Alt itself down and up: with only a modified "L", Figma kept
        # treating Alt as held and swallowed the next caret click.
        call = self.tab.call
        call("Input.dispatchKeyEvent", type="rawKeyDown", key="Alt", code="AltLeft", modifiers=1,
             windowsVirtualKeyCode=18)
        self.tab.key("¬", "KeyL", modifiers=1, vk=76)
        call("Input.dispatchKeyEvent", type="keyUp", key="Alt", code="AltLeft", windowsVirtualKeyCode=18)
        self.frame()

    def wheel(self, dy):
        st = self.js("scroll.state()")
        if st and dy:
            self.tab.wheel(st["x"], st["y"], dy)
            self.settle_scroll()

    def settle_scroll(self, timeout=1.5):
        """Wheel scrolling is animated; coordinates read mid-animation send clicks to the wrong row."""
        deadline, last, same = time.monotonic() + timeout, None, 0
        while time.monotonic() < deadline:
            self.frame()
            up = (self.js("scroll.state()") or {}).get("up")
            same = same + 1 if up == last else 0
            if same >= 2:
                return
            last = up

    def scroll_top(self):
        for _ in range(50):
            st = self.js("scroll.state()")
            if not st or st["up"] <= 0:
                return
            self.wheel(-max(st["up"], st["page"]))

    def scroll_next(self):
        st = self.js("scroll.state()")
        if not st or st["down"] <= 1:
            return False
        self.wheel(min(st["page"], st["down"]))
        return True

    def scroll_to(self, node_id, block="center"):
        """Returns True if it had to scroll."""
        moved = False
        for _ in range(3):
            d = self.js(f"scroll.delta({json.dumps(node_id)}, {json.dumps(block)})")
            if not d or abs(d) < 1:
                return moved
            self.wheel(d)
            moved = True
        return moved

    def point(self, node_id, part="name"):
        self.scroll_to(node_id)
        return self.js(f"point({json.dumps(node_id)}, {json.dumps(part)})")

    def switch_page(self, name):
        if next((p for p in self.js("pages()") if p["current"]), {}).get("name") == name:
            return
        for _ in range(5):  # the pages list scrolls on its own; bring the button into view with the wheel
            d = self.js(f"pageDelta({json.dumps(name)})")
            if not d or abs(d["delta"]) < 1:
                break
            self.tab.wheel(d["x"], d["y"], d["delta"])
            time.sleep(0.4)  # animated scroll
            self.frame()
        xy = self.js(f"pagePoint({json.dumps(name)})")
        if not xy:
            raise RuntimeError(f"Page button not clickable: {name}")
        self.tab.click(xy["x"], xy["y"])
        if not self.wait(f"pages().find(p => p.current)?.name === {json.dumps(name)} && window.__figTree.ready()", 20):
            raise RuntimeError(f"Page did not open: {name}")
        time.sleep(0.5)

    def children(self, node):
        """Direct children of node (None = page root). A parent that lists none was read before its
        children rendered, so read it once more."""
        kids = self._children(node)
        if not kids and (node is None or node["parent"]):
            time.sleep(0.8)
            kids = self._children(node)
        return kids

    def _children(self, node):
        """Direct children in panel order, via aria-rowindex while scrolling the virtualized panel."""
        if node is None:
            level, after = -1, 0
            self.scroll_top()
        else:
            row = self.js(f"row({json.dumps(node['id'])})")
            if row is None:
                raise RuntimeError(f"Layer row not rendered: {node['name']}")
            if row["expanded"] == "false":
                self.click_until(node, "caret", f"row({json.dumps(node['id'])})?.expanded === 'true'")
            level, after = row["level"], row["index"]
            self.scroll_to(node["id"], "start")
            # Expansion re-renders rows asynchronously. Wait for the first child itself: the old next
            # sibling already sits at index+1 until the re-render, and reading it ends the scan with no kids.
            self.wait(f"rows().some(r => r.index === {after + 1} && r.level === {level + 1})", 5)
        self.frame()
        found = {}
        while True:
            rendered = sorted(self.js("rows()"), key=lambda r: r["index"])
            if os.environ.get("FIGMA_DEBUG"):
                near = [(r["index"], r["level"], r["name"][:12]) for r in rendered if r["index"] > after][:4]
                print(f"    [children of {node['name'] if node else 'root'} L{level} after#{after}] next rows: {near}",
                      file=sys.stderr)
            for r in rendered:
                if r["index"] <= after:
                    continue
                if r["level"] <= level:
                    return list(found.values())
                if r["level"] == level + 1:
                    found.setdefault(r["id"], r)
                after = r["index"]
            if len(found) >= MAX_CHILDREN or not self.scroll_next():
                return list(found.values())
            self.frame()

    def search(self, query):
        """Canvas search over all pages. Returns [{key, page, name, type}]."""
        if not self.js("search.open()"):
            xy = self.js("search.button()")
            self.tab.click(xy["x"], xy["y"])
            self.wait("search.open()", 5)
        xy = self.js("search.input()")
        self.tab.click(xy["x"], xy["y"])
        # Replace any previous query. A bare Cmd+A key event does not select text; the editing command does.
        self.tab.call("Input.dispatchKeyEvent", type="rawKeyDown", key="a", code="KeyA", modifiers=4,
                      windowsVirtualKeyCode=65, commands=["selectAll"])
        self.tab.call("Input.dispatchKeyEvent", type="keyUp", key="a", code="KeyA", modifiers=4,
                      windowsVirtualKeyCode=65)
        self.tab.call("Input.insertText", text=query)
        time.sleep(0.4)
        self.wait("!search.busy()", 10)
        # With no results the scope control is not rendered; "No results in this file" is already all pages.
        if self.js("search.scopePoint()") and self.js("search.scope()") != "All pages":
            xy = self.js("search.scopePoint()")
            self.tab.click(xy["x"], xy["y"])
            # Each new session starts at "This page".
            self.wait("search.allPagesPoint()", 3)
            xy = self.js("search.allPagesPoint()")
            if not xy:
                self.tab.key("Escape", "Escape", vk=27)
                raise RuntimeError("Search scope menu has no clickable 'All pages' option")
            self.tab.click(xy["x"], xy["y"])
            time.sleep(0.4)
            self.wait("!search.busy()", 15)
        for _ in range(20):  # open collapsed page groups so their results render
            xy = self.js("search.collapsedGroup()")
            if not xy:
                break
            self.tab.click(xy["x"], xy["y"])
            self.frame()
        return self.js("search.results()")

    def close_search(self):
        for _ in range(3):
            if not self.js("search.open()"):
                return
            xy = self.js("search.closePoint()")
            if xy:
                self.tab.click(xy["x"], xy["y"])
                self.wait("!search.open() && ready()", 3)
            else:
                # A dropdown left open (e.g. by an interrupted run) lays a backdrop over the Close button.
                self.tab.key("Escape", "Escape", vk=27)
                self.frame()

    def select_result(self, result):
        """Select a search result, leave search, and reveal it in the Layers panel. Enter selects its
        children (which expands the tree down to them); Shift+Enter selects the node back. Returns the
        node's row, or None for a node without children (still selected on canvas, but not revealed)."""
        xy = self.js(f"search.resultPoint({json.dumps(result['key'])})")
        self.tab.click(xy["x"], xy["y"])
        time.sleep(0.8)
        self.close_search()
        self.tab.key("Enter", "Enter", vk=13)
        time.sleep(0.6)
        if not any(r["selected"] for r in self.js("rows()")):
            return None
        self.tab.key("Enter", "Enter", modifiers=8, vk=13)
        time.sleep(0.6)
        selected = [r for r in self.js("rows()") if r["selected"]]
        return min(selected, key=lambda r: r["level"]) if selected else None

    def click_until(self, node, part, done):
        """Click a row part until `done` holds. After the panel has been scrolled, Figma's first click
        re-syncs the list to its own scroll position (rows jump by a few rows), so that click can miss;
        recompute the point and try again."""
        for attempt in range(3):
            xy = self.point(node["id"], part)
            if not xy:
                raise RuntimeError(f"Layer row not clickable: {node['name']}")
            self.tab.click(xy["x"], xy["y"])
            if self.wait(done, 1.5):
                return
            if os.environ.get("FIGMA_DEBUG"):
                print(f"    [click {part} {node['name']}] attempt {attempt + 1} missed at {xy}", file=sys.stderr)
        raise RuntimeError(f"Click did not take effect: {part} of {node['name']}")

    def select(self, node):
        self.click_until(node, "name", f"row({json.dumps(node['id'])})?.selected")


def ask(request, state, questions):
    """One TypeSafe request with several parallel questions over the same state.
    questions: {id: {"type": "choice", "criteria": {...}, "task": str} | {"type": "noul", "task": str}}."""
    body = {
        "model": os.environ.get("TYPESAFE_MODEL", "jev-latest"),
        "state": state,
        "questions": {
            qid: {"type": q["type"], "instructions": {"request": request, "task": q["task"]},
                  **({"criteria": q["criteria"]} if q["type"] == "choice" else {})}
            for qid, q in questions.items()
        },
    }
    started = time.perf_counter()
    response = CLIENT.post("https://api.typesafe.ai/v1/systemone", json=body,
                           headers={"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}"})
    if response.is_error:
        raise RuntimeError(f"TypeSafe HTTP {response.status_code}: {response.text[:300]}")
    answers = response.json()["answers"]
    ms = round((time.perf_counter() - started) * 1000)
    out = {}
    for qid, q in questions.items():
        if q["type"] == "choice":
            a = validate_choice(answers[qid], q["criteria"])
            out[qid] = (a["choice"], a["probabilities"], a["confidence"])
        else:
            out[qid] = float(answers[qid]["noul"])
    return out, ms


PAGE_TASK = (
    "A designer's request names one layer in a Figma file. Choose the page that most likely contains it. "
    "If the request does not point to another page, the current page is a reasonable default."
)
CHILD_TASK = (
    "A designer's request names one layer in a Figma file. We are walking down the layer tree from "
    "`path` to `current`. Choose the child layer that is the requested layer or most likely contains it. "
    "Choose NONE only if nothing under `current` can be the requested layer. Generic names like "
    "'Frame 123' can still contain the target when their parent matched."
)
HERE_TASK = (
    "A designer's request names one layer in a Figma file. Is `current` itself exactly the requested "
    "layer, not merely a section or group that contains it? Respect the kind of layer the request asks "
    "for (for example a screen/frame versus a whole section, or a single text layer)."
)


GENERIC = re.compile(r"^(frame|group|rectangle|auto layout|section|container|vector|ellipse)\s*[\d.]*$", re.I)
PEEK_LIMIT = 12  # only peek when a level has this few children
PEEK_NAMES = 6


def describe(child):
    kind = "has child layers" if child["parent"] else "no child layers"
    text = f"Layer '{child['name']}' [{child['type']}], {kind}"
    if child.get("preview"):
        text += "; contains: " + ", ".join(f"'{n}'" for n in child["preview"])
    return text


def peek(tree, kids):
    """Names like 'Frame 5678' say nothing; list what is inside them so the choice has evidence."""
    if len(kids) > PEEK_LIMIT:
        return
    for k in kids:
        if k["parent"] and GENERIC.match(k["name"].strip()):
            k["preview"] = [g["name"][:40] for g in tree.children(k)[:PEEK_NAMES]]


SEARCH_TASK = (
    "A designer's request names one layer in a Figma file. These are the file's search results for a name "
    "quoted in the request. Choose the result that is the requested layer or the named container the "
    "request says it is inside. Choose NONE if no result fits."
)


def quoted(request, pages):
    """Names the request quotes, most specific (last) first, without page names."""
    names = re.findall(r"[「『“\"]([^」』”\"]+)[」』”\"]", request)
    return [n.strip() for n in reversed(names) if n.strip() and n.strip() not in pages]


def choose_page(tree, request, log):
    pages = tree.js("pages()")
    current = next((p["name"] for p in pages if p["current"]), None)
    options = {f"p{i}": f"Page '{p['name']}'" for i, p in enumerate(pages)}
    answers, ms = ask(request, {"file": tree.tab.js("document.title"), "current_page": current,
                                "pages": [p["name"] for p in pages]},
                      {"page": {"type": "choice", "criteria": options, "task": PAGE_TASK}})
    choice, probs, conf = answers["page"]
    page = pages[int(choice[1:])]["name"]
    log.append({"step": "page", "choice": page, "p": round(probs[choice], 3), "confidence": round(conf, 3),
                "latency_ms": ms})
    return page


def search_anchor(tree, request, log):
    """Code finds candidates by the quoted names; Jev only picks among them. Returns (page, node) where
    node is None when the chosen result has no children (it is then the answer, already selected)."""
    pages = [p["name"] for p in tree.js("pages()")]
    for name in quoted(request, pages):
        t0 = time.perf_counter()
        results = tree.search(name)[:60]
        search_ms = round((time.perf_counter() - t0) * 1000)
        if not results:
            log.append({"step": f"search '{name}'", "choice": "no results", "search_ms": search_ms})
            continue
        options = {f"r{i}": f"'{r['name']}' [{r['type']}] on page '{r['page']}'" for i, r in enumerate(results)}
        options["NONE"] = "None of these results is the requested layer or its container"
        answers, ms = ask(request, {"query": name, "results": list(options.values())[:-1]},
                          {"pick": {"type": "choice", "criteria": options, "task": SEARCH_TASK}})
        choice, probs, conf = answers["pick"]
        if choice == "NONE" and probs["NONE"] < NONE_THRESHOLD:
            choice = max((k for k in probs if k != "NONE"), key=probs.get)
        log.append({"step": f"search '{name}' ({len(results)} results)", "choice": choice if choice == "NONE"
                    else results[int(choice[1:])]["name"], "p": round(probs[choice], 3),
                    "confidence": round(conf, 3), "latency_ms": ms, "search_ms": search_ms})
        print(f"  {log[-1]['step'][-50:]:<50} → {log[-1]['choice'][:30]:<30} p={probs[choice]:.2f} {ms}ms", flush=True)
        if choice == "NONE":
            continue
        result = results[int(choice[1:])]
        node = tree.select_result(result)
        return result, node
    tree.close_search()
    return None, None


def find(tree, request, log):
    result, anchor = search_anchor(tree, request, log)
    if result and anchor is None:
        # A leaf result: it is the answer and is selected on canvas already.
        return {"name": result["name"], "type": result["type"], "already_selected": True}
    if anchor:
        found = descend(tree, request, result["page"], anchor, log)
        if found:
            return found
        log.append({"step": "anchor branch exhausted", "choice": "fall back to page descent"})
    page = choose_page(tree, request, log)
    tree.switch_page(page)
    tree.collapse_all()
    return descend(tree, request, page, None, log)


def with_path(node, ancestors):
    """The target plus the ancestors walked to reach it (from the search anchor or the page root)."""
    return {**node, "ancestors": [{k: a[k] for k in ("id", "name", "type")} for a in ancestors]}


def descend(tree, request, page, start, log):
    """Walk down from start (None = page root). Never backtracks above start."""
    path, excluded, backtracks = ([start] if start else []), set(), 0
    node = start
    for _ in range(MAX_DEPTH + MAX_BACKTRACKS):
        kids = [k for k in tree.children(node) if k["id"] not in excluded]
        peek(tree, kids)
        options = {f"c{i}": describe(k) for i, k in enumerate(kids)}
        # The page was already chosen, so "not here" only makes sense below the root.
        if node is not None:
            options["NONE"] = "The requested layer is not under any of these children"
        state = {"page": page, "path": [n["name"] for n in path[:-1]],
                 "current": {"name": node["name"], "type": node["type"]} if node else "(page root)",
                 "children": [describe(k) for k in kids]}
        questions = {}
        if len(options) >= 2:
            questions["child"] = {"type": "choice", "criteria": options, "task": CHILD_TASK}
        if node is not None:
            questions["here"] = {"type": "noul", "task": HERE_TASK}
        if not questions:
            return with_path(kids[0], path) if kids else None
        answers, ms = ask(request, state, questions)
        here = answers.get("here", 0.0)
        if "child" in answers:
            choice, probs, conf = answers["child"]
            # Giving up on a branch discards everything below it; do it only on a clear NONE.
            if choice == "NONE" and probs["NONE"] < NONE_THRESHOLD:
                choice = max((k for k in probs if k != "NONE"), key=probs.get)
            p = probs[choice]
        else:
            choice, p, conf = "NONE", 1.0, 1.0
        if node is not None and here >= HERE_THRESHOLD:
            choice, p = "HERE", here
        picked = kids[int(choice[1:])] if choice.startswith("c") else None
        log.append({"step": " / ".join([page] + [n["name"] for n in path]),
                    "choice": picked["name"] if picked else choice, "p": round(p, 3), "here": round(here, 3),
                    "confidence": round(conf, 3), "latency_ms": ms, "options": len(options)})
        print(f"  {log[-1]['step'][-50:]:<50} → {log[-1]['choice'][:30]:<30} p={p:.2f} here={here:.2f} {ms}ms",
              flush=True)
        if choice == "HERE":
            return with_path(node, path[:-1])
        if choice == "NONE":
            if node is None or node is start or backtracks >= MAX_BACKTRACKS:
                return None
            backtracks += 1
            excluded.add(node["id"])
            path.pop()
            node = path[-1] if path else None
            continue
        if not picked["parent"]:
            return with_path(picked, path)
        path.append(picked)
        node = picked
    return None


def file_url(tab):
    return tab.js("location.origin + location.pathname")


def inspect_selection(tab, out_dir, target=None):
    """Read the Properties panel for what is selected now and capture it."""
    open_properties(tab)
    result = tab.js(EXTRACT)
    if not result or not result.get("sections"):
        return None, None
    if target and target.get("already_selected"):
        result.update(layer=result.get("layer") or target["name"], type=result.get("type") or target["type"])
    if not result.get("node_id"):
        node = parse_qs(urlparse(tab.js("location.href")).query).get("node-id")
        result["node_id"] = node[0].replace("-", ":") if node else None
    if result.get("node_id"):
        result["url"] = f"{file_url(tab)}?node-id={result['node_id'].replace(':', '-')}"
    ancestors = (target or {}).get("ancestors") or []
    if ancestors:
        result["path"] = [a["name"] for a in ancestors] + [result.get("layer") or target["name"]]
    # Layers inside a component instance get a fresh node id on every load, so their link dies with this
    # tab. The outermost instance itself keeps its id: link to it and give the path from there.
    instance = next((a for a in ancestors if a["type"] == "Instance"), None)
    if instance:
        result["url_stable"] = False
        result["stable_url"] = f"{file_url(tab)}?node-id={instance['id'].replace(':', '-')}"
        result["stable_anchor"] = instance["name"]
    tab.normal()  # back to the real window size for a normal-looking screenshot
    shot = str(capture(tab, Path(out_dir) / "selection.png", layer_size(result)))
    return result, shot


def run(tab_token, request, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    log, result, shot, nav_ms = [], None, None, 0
    # Only the find mode clicks the Layers panel, and only it needs the tall viewport.
    with FigmaTab(tab_token, tall=TALL_VIEWPORT if request else None) as tab:
        tree = Tree(tab)
        tree.close_search()  # a previous run may have left it open, which hides the Layers panel
        if not tree.wait("ready()", 40):
            raise RuntimeError("Figma file did not load a Layers panel (not logged in, or no access?)")
        if request:
            target = find(tree, request, log)
            nav_ms = round((time.perf_counter() - started) * 1000)
            if target:
                if not target.get("already_selected"):
                    tree.select(target)
                result, shot = inspect_selection(tab, out_dir, target)
        else:
            # The URL's node-id selected the node when the page loaded; wait for its Properties.
            tab.wait_for("!!document.querySelector('[data-testid$=\"-inspection-panel\"]')", 20)
            result, shot = inspect_selection(tab, out_dir)
    status = "done" if result else ("not_found" if request else "no_selection")
    report = {"request": request, "status": status, "result": result, "screenshot": shot, "decisions": log,
              "timing_ms": {"navigate": nav_ms, "total": round((time.perf_counter() - started) * 1000)}}
    (out_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tab-token", required=True,
                        help="the t= value in the URL of the Figma tab Claude opened with claude-in-chrome")
    parser.add_argument("--find", metavar="REQUEST",
                        help="describe the layer (quote known layer names in 「」); omit to read the node the "
                             "tab's node-id URL selected")
    parser.add_argument("--out", help="output directory (default: a new temp directory)")
    args = parser.parse_args()
    out = args.out or tempfile.mkdtemp(prefix="figma-view-")
    report = run(args.tab_token, args.find, out)
    print(json.dumps({k: report[k] for k in ("status", "result", "screenshot", "timing_ms")},
                     ensure_ascii=False, indent=2))
    print(f"report: {Path(out) / 'result.json'}")
