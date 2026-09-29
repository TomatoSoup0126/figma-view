---
name: inspect
description: Read Figma layer specs (size, auto layout, text style, color tokens and hex) and a screenshot from the Figma web app without spending Figma MCP quota; works with a View seat. With a node-id URL it reads the layer directly; with only a text description it finds the layer via Jev search plus a level-by-level walk. Use when checking Figma specs, asking what font/color/size a screen uses, building UI from Figma, a figma.com/design link is pasted with design questions, or Figma MCP is out of quota or get_design_context fails.
argument-hint: "[figma.com/design URL] [description of the layer to find]"
---

# figma-view:inspect

Figma's canvas is a `<canvas>`, but the layer tree and the Properties panel on the right are DOM. This skill opens a dedicated tab with claude-in-chrome, then drives only that tab with browser-harness (CDP):
- **node-id mode**: when the URL has `?node-id=`, Figma selects that node on load, and the script reads Properties and takes a screenshot. No model is involved.
- **Description mode** (`--find`): the script first searches the names wrapped in 「」 in the request, lets Jev (TypeSafe's System One model) pick among the results, then walks down level by level. At each level Jev answers only two questions: which child to go into, and whether the current node is the target.

This assumes a View seat: Dev Mode is locked, so CSS and variables are **not available**. What is available: Layout (W/H/Radius/Border; for auto layout also Flow direction, Hug/Fill sizing, Gap, and padding. Padding is listed per side as Left/Right/Top/Bottom; do not treat a side that is not listed as 0), Typography (style name, font, weight, size/line height, letter spacing), Colors (token name and hex), Content (text), and the parent component. If the user needs anything beyond this, say so plainly; do not guess.

## Prerequisites

Below, replace `<SKILL_DIR>` with the Base directory you were given when this skill loaded (the directory that contains this SKILL.md). It differs by install method, so never hard-code it.

1. Prepare the environment (idempotent; the last line printed is the clone path, `~/.cache/jev-ultrafast` by default, overridable with the `JEV_DIR` environment variable):
   ```bash
   bash "<SKILL_DIR>/scripts/setup.sh"
   ```
   Exit code 2 means failure, with the reason on stderr. Description mode needs the `TYPESAFE_API_KEY` environment variable. **Never print its value.**
2. Requires the claude-in-chrome tools (`tabs_context_mcp`, `navigate`, `tabs_close_mcp`), and Chrome must allow remote debugging for browser-harness. On the first connection Chrome may show "Allow remote debugging?"; ask the user to click Allow.

## Workflow

1. **Open a tab**: call `tabs_context_mcp(createIfEmpty: true)` to get a tab, then `navigate` to the user's URL. Keep the node-id if there is one; otherwise use the file URL.
   - Always open your own tab. Never take over one of the user's tabs, and never run JS in other tabs. Taking over the user's tab requires bringing it to the foreground, which gets in the way of the user's own Chrome use; injecting JS into other tabs is blocked by auto mode as credential exploration. Tabs opened by claude-in-chrome land in the profile that has the extension installed and is logged in to Figma. browser-harness cannot choose a profile on its own, which is why the work is split this way.
2. **Wait for load, get the token**: wait 5–8 seconds, then call `tabs_context_mcp` again until the tab title becomes "<file name> – Figma". The `t=` value Figma adds to the URL (e.g. `t=AbCdEfGh12345678-0`) identifies this tab. Figma strips custom parameters, so this is the only marker available. If the URL is `/login`, ask the user to log in in that profile; never type credentials for them.
3. **Run**:
   ```bash
   export JEV_DIR=<path printed by setup.sh>
   # node-id mode
   uv run --quiet --project "$JEV_DIR" python "<SKILL_DIR>/scripts/figma_inspect.py" --tab-token <t>
   # Description mode
   uv run --quiet --project "$JEV_DIR" python "<SKILL_DIR>/scripts/figma_inspect.py" --tab-token <t> \
     --find "On the 「Sign-in flow v2」 page, in the 「Verification-default」 frame, select the text layer of the first OTP digit (A)"
   ```
   - Each Bash call starts a fresh shell, so include the `export JEV_DIR=...` line every time.
   - Write `--find` in the user's own words. Wrap page or layer names the user mentioned in 「」 (these corner brackets are syntax the script parses; do not replace them with other quotes), and copy the names exactly as they appear in Figma. The script searches these names first, which is the most accurate and fastest path. Do not invent names: if the search finds nothing it falls back to walking the tree, but a wrong invented name misleads Jev's choices.
   - State what kind of layer is wanted (a whole screen/frame, a Section, a single text layer); Jev uses this to decide which level to stop at.
   - Description mode usually takes 5–30 seconds, about 10 of which is the search. Set the command timeout to 180 seconds.
4. **Read the result**: the last line of stdout is the path to `result.json`; the screenshot is `selection.png` in the same directory, view it with Read. Report:
   - Layer name, type, and `result.path` (the path down from the search anchor or the page).
   - Link: when `result.url_stable` is false, the layer is **inside** a component instance. Its node id is regenerated every time Figma loads, so `result.url` only works in this tab. In that case give `result.stable_url` instead (the link to the outermost instance, `stable_anchor`, which stays valid across days) along with the path down from it. Otherwise give `result.url`.
   - Specs as a table, in the order of `sections`: Layout, Typography, Colors, Content, and the parent component.
   - In description mode, check `decisions`: one entry per step, each with `step` and `choice`. Entries from a model call also have `p` (probability of the chosen option) and `confidence`; tree-walk entries add `here` (probability that the current node is the target) and `options`. A search with no results (`choice: "no results"`) and `anchor branch exhausted` have no `p`; skip them. Ask the user to confirm it is the layer they wanted, with the link, if any `p` is below 0.5, if a search step chose `NONE` or the anchor branch was exhausted (the walk then fell back to descending from the page, where wrong picks are most common), or if the result stopped on a container such as a Section. This is not a formality: with vague requests, siblings with meaningless names (Group 101 and Group 102) are often near ties, the same request can take different branches on two runs, and these are the warning signs.
5. **Clean up**: when inspecting several layers in the same file, reuse the same tab and token. When done, close the tab with `tabs_close_mcp`.

## Status and error handling

| Situation | What to do |
|---|---|
| `status: done` | Report as in step 4 |
| `status: not_found` | List the path in `decisions` and ask the user for the layer name (in 「」) or a node-id link |
| `status: no_selection` | The URL has no node-id, or that node does not exist. Switch to description mode, or ask the user to right-click the layer in Figma → Copy link to selection |
| `Expected one Figma tab with t=...` | The URL changed or the tab was closed. Call `tabs_context_mcp` again to read the token; if the tab is gone, go back to step 1 |
| `did not load a Layers panel` | Not logged in, or no access to this file |
| `Click did not take effect` | Figma's panel state lagged behind. Run once more; if it fails again, switch to node-id mode |
| `TypeSafe HTTP 401/403` | `TYPESAFE_API_KEY` is invalid. Switch to node-id mode |

## Notes

- **Data sent out**: description mode sends the request, page names, and layer names to TypeSafe. node-id mode sends nothing.
- **Read-only**: the script only clicks pages, layer rows, expand carets, the search box, and the Properties tab. It never touches Ask to edit, Share, or comments.
- Implementation details and known pitfalls (clicks land one row off after the Figma virtual list scrolls, timing when expanding, how search results get revealed) are documented in the comments of `scripts/figma_inspect.py` and `scripts/figma_tree.js`. Read those comments before changing the code.
