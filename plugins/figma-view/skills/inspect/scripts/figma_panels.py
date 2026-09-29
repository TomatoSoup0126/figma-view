"""Deterministic reads and captures of Figma's view-only UI for the current selection. No model involved."""

import time
from pathlib import Path

HERE = Path(__file__).parent
EXTRACT = (HERE / "figma_extract.js").read_text()


def open_properties(tab):
    xy = tab.js(
        """(() => { const t = [...document.querySelectorAll('[role="tab"]')]
            .find(t => t.innerText.trim().startsWith('Properties'));
          if (!t || t.getAttribute('aria-selected') === 'true') return null;
          const r = t.getBoundingClientRect(); return {x: r.x + r.width / 2, y: r.y + r.height / 2}; })()"""
    )
    if xy:
        tab.click(xy["x"], xy["y"])
    tab.wait_for("!!document.querySelector('[data-testid$=\"-inspection-panel\"]')", 5)
    time.sleep(0.3)


def layer_size(result):
    props = next((x.get("props", {}) for x in (result or {}).get("sections", []) if x["kind"] == "properties"), {})
    try:
        return max(float(props[k].replace(",", "").rstrip("px")) for k in ("Width", "Height"))
    except (KeyError, ValueError):
        return None


# Visible floating overlays over the canvas: [{top, hud}]. hud marks the transient zoom indicator.
OVERLAY_JS = """() => {
  const out = [], walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = walker.nextNode());) {
    const t = n.textContent.trim(), e = n.parentElement;
    if (!/^(You can only view and comment|Zoom to selection|Zoom in|Zoom out)/.test(t) || !e.checkVisibility()) continue;
    const r = e.getBoundingClientRect();
    if (r.height) out.push({top: r.top, hud: /^Zoom/.test(t)});
  }
  // The visible view-only banner splits its text differently from a hidden copy; its "Ask to edit"
  // button is the reliable handle (the banner is about 40px tall around it).
  for (const b of document.querySelectorAll('button')) {
    if ((b.innerText || '').trim() !== 'Ask to edit' || !b.checkVisibility()) continue;
    const r = b.getBoundingClientRect();
    if (r.height) out.push({top: r.top - 12, hud: false});
  }
  return out;
}"""


def capture(tab, path, size=None):
    """Zoom to selection (Shift+2), back off for small layers so their context shows, and capture the
    canvas between the side panels and above the floating toolbar."""
    tab.key("@", "Digit2", modifiers=8, vk=50)
    # Zoom to selection fills the canvas with the layer; each "-" halves the zoom so its surroundings
    # show. A 260px text layer needed two steps before its context was readable.
    steps = 0 if not size or size >= 800 else 4 if size < 60 else 3 if size < 150 else 2 if size < 400 else 1
    for _ in range(steps):
        time.sleep(0.15)
        tab.key("-", "Minus", vk=189)
    # The "Zoom to selection" HUD stays about 3s; wait it out rather than crop around it.
    time.sleep(0.5)
    tab.wait_for(f"!({OVERLAY_JS})().some(o => o.hud)", 5)
    clip = tab.js(
        """(() => {
          const left = document.querySelector('[data-testid="objects-panel"]')?.closest('[class*="left"],aside,nav')
            || document.querySelector('[data-testid="objects-panel"]');
          const right = document.querySelector('[data-testid$="-inspection-panel"]');
          const tools = document.querySelector('[data-testid="positioned-design-toolbelt"]');
          const l = left ? left.getBoundingClientRect().right : 0;
          let r = innerWidth;
          for (let e = right; e; e = e.parentElement) {
            const b = e.getBoundingClientRect();
            if (b.width < innerWidth / 2 && b.height > innerHeight * 0.6) r = b.left; else if (b.width >= innerWidth / 2) break;
          }
          // Floating overlays still showing (the view-only banner) sit above the toolbar; stop above them.
          // Use the text's own box: its wrappers include zero-height, top-anchored layers.
          let bottom = tools ? tools.getBoundingClientRect().top : innerHeight;
          for (const o of (%s)()) if (o.top > innerHeight / 2) bottom = Math.min(bottom, o.top - 16);
          return {x: Math.ceil(l), y: 0, width: Math.floor(r - l), height: Math.floor(bottom - 8)};
        })()""" % OVERLAY_JS
    )
    ok = clip and clip["width"] > 200 and clip["height"] > 200
    return tab.screenshot(str(path), clip=clip if ok else None)
