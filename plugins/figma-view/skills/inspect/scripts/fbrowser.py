"""The Figma tab Claude opened with claude-in-chrome, driven over one CDP session (browser-harness).

claude-in-chrome opens tabs in the Chrome profile that has the Claude extension, which is where Figma is
logged in; browser-harness cannot pick a profile on its own. Figma stamps each tab's URL with a unique
`t=` token, so that token selects exactly Claude's tab and never one of the user's. Claude closes the tab
with claude-in-chrome afterwards; close() here only detaches and clears emulation.
"""

import base64
import json
import time
from urllib.parse import parse_qs, urlparse

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp

class FigmaTab:
    def __init__(self, tab_token, width=1440, tall=None):
        ensure_daemon()
        matches = [t for t in cdp("Target.getTargets")["targetInfos"] if t["type"] == "page"
                   and "figma.com/design/" in t["url"] and parse_qs(urlparse(t["url"]).query).get("t") == [tab_token]]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one Figma tab with t={tab_token}, found {len(matches)}. "
                               "Read the tab's current URL from claude-in-chrome tabs_context again.")
        self.target = matches[0]["targetId"]
        self.session = cdp("Target.attachToTarget", targetId=self.target, flatten=True)["sessionId"]
        # The tab may sit behind the user's; focus emulation keeps it rendering and taking input
        # (hidden tabs never acknowledge dispatched input events).
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self.tall = False
        if tall:
            # A very tall viewport shows ~100 layer rows at once, so the Layers panel rarely scrolls.
            # Figma's virtual list positions rows from its own scroll model, and after a scroll clicks
            # landed one row off. Restored with normal() before screenshots and on close.
            self.tall = True
            self.call("Emulation.setDeviceMetricsOverride", width=width, height=tall, deviceScaleFactor=0,
                      mobile=False)

    def normal(self):
        if self.tall:
            self.call("Emulation.clearDeviceMetricsOverride")
            self.tall = False
            time.sleep(0.5)

    def call(self, method, **params):
        # Figma's main thread can stall for seconds while a page loads; input acks wait for it.
        slow = method.startswith("Input.") or method == "Page.captureScreenshot"
        return cdp(method, session_id=self.session, _response_timeout=20 if slow else 5, **params)

    def js(self, expression, await_promise=False):
        r = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=await_promise)
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", "JS error")[:300])
        return r.get("result", {}).get("value")

    def wait_for(self, expression, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.js(expression):
                    return True
            except RuntimeError:
                pass
            time.sleep(0.1)
        return False

    def click(self, x, y, count=1):
        self.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        for event in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", type=event, x=x, y=y, button="left", clickCount=count)

    def wheel(self, x, y, dy):
        self.call("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0, deltaY=dy)

    def key(self, key, code, modifiers=0, vk=0):
        for t in ("rawKeyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", type=t, key=key, code=code, modifiers=modifiers,
                      windowsVirtualKeyCode=vk)

    def screenshot(self, path, clip=None):
        params = {"format": "png"}
        if clip:
            params["clip"] = {**clip, "scale": 1}
        data = self.call("Page.captureScreenshot", **params)["data"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        return path

    def close(self):
        if not getattr(self, "target", None):
            return
        self.normal()
        self.call("Emulation.setFocusEmulationEnabled", enabled=False)
        cdp("Target.detachFromTarget", sessionId=self.session)
        self.target = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
