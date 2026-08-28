"""Re-take the deck's screenshots against a running stack.

    api/.venv/Scripts/python.exe docs/pitch/shoot.py            # all of them
    api/.venv/Scripts/python.exe docs/pitch/shoot.py ranking    # just one

Why this is a script and not a person with a cropping tool
----------------------------------------------------------
Four of the six shots in the deck went stale within two days of being taken,
because the screens under them kept moving. A hand-cropped screenshot cannot be
re-taken the same way, so re-shooting one meant re-deciding its frame, and the
deck drifted instead of being updated. Here each shot names the component it
frames and `getBoundingClientRect` cuts it, so a re-shoot lands where the last
one did.

Chrome's own `--screenshot` cannot do this: four of the six screens are behind a
session. So this drives headless Chrome over CDP -- `Network.setCookie` puts the
real session cookies in place and `Runtime.evaluate` writes the identity marker
`web/lib/auth.ts` keeps beside them, which is what makes the product screens
render signed in.

Two traps, both hit while writing it:

  * **Scroll to the top before measuring.** Several panes are `position: sticky`.
    A clip taken after scrolling to one captures the nav bar painted over it.
  * **A tall frame is a small frame.** `.shot img` in the deck is
    height-constrained with `width: auto`, so a shot twice as tall renders half
    as wide. `max_ratio` crops from the top, which is what `.shot.clipped` is for.

Needs the demo stack up (`docs/RUNBOOK.md` section 9) and `var/demo-credentials.txt`
holding tab-separated `role<TAB>email<TAB>password` lines.
"""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
from pathlib import Path

import httpx
import websockets
from PIL import Image

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
ORIGIN = "http://localhost:8080"
API = ORIGIN + "/api"
PORT = 9350
REPO = Path(__file__).resolve().parents[2]
SHOTS = REPO / "docs" / "pitch" / "shots"
PROFILE = REPO / "var" / "chrome-profile"
CREDENTIALS = REPO / "var" / "demo-credentials.txt"

# Injected after every navigation; `__card` is how a shot names its frame.
HELPERS = """
window.__card = t => [...document.querySelectorAll('section.card')]
  .find(s => (s.querySelector('h2')||{}).textContent?.trim().startsWith(t));
window.__text = t => [...document.querySelectorAll('div,section')]
  .filter(e => new RegExp(t, 'i').test(e.textContent))
  .sort((a, b) => a.getBoundingClientRect().height - b.getBoundingClientRect().height)[0];
"""


class Tab:
    def __init__(self, ws):
        self.ws, self._id = ws, 0

    async def send(self, method, **params):
        self._id += 1
        await self.ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def js(self, expression):
        result = await self.send(
            "Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True
        )
        return result["result"].get("value")

    async def goto(self, url, settle=4.0):
        await self.send("Page.navigate", url=url)
        await asyncio.sleep(settle)
        await self.js(HELPERS)

    async def viewport(self, width, height):
        await self.send(
            "Emulation.setDeviceMetricsOverride",
            width=width, height=height, deviceScaleFactor=1, mobile=False,
        )


async def launch():
    proc = subprocess.Popen(
        [
            CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
            "--no-default-browser-check", "--force-color-profile=srgb",
            "--font-render-hinting=none",
            # The deck is shot in the light theme, and `Auto` follows this.
            "--blink-settings=preferredColorScheme=1",
            f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}", "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            targets = httpx.get(f"http://127.0.0.1:{PORT}/json/list", timeout=1).json()
            # NOT targets[0]: an installed extension's background_page sorts first, and
            # talking to it looks exactly like a page that renders nothing at all.
            pages = [t for t in targets if t["type"] == "page"]
            if pages:
                return proc, pages[0]["webSocketDebuggerUrl"]
        except Exception:
            pass
        await asyncio.sleep(0.5)
    proc.terminate()
    raise SystemExit("chrome never opened a page target")


def credentials():
    accounts = {}
    for line in CREDENTIALS.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split("\t")
        if len(parts) == 3:
            accounts.setdefault(parts[0], (parts[1], parts[2]))
    return accounts


async def sign_in(tab, role, creds):
    email, password = creds[role]
    with httpx.Client(base_url=API, timeout=30) as client:
        login = client.post("/auth/login", json={"email": email, "password": password})
        login.raise_for_status()
        account = client.get("/auth/me", cookies=login.cookies).json()
        cookies = dict(login.cookies)
    await tab.send("Network.clearBrowserCookies")
    for name, value in cookies.items():
        await tab.send(
            "Network.setCookie", name=name, value=value,
            domain="localhost", path="/", httpOnly=True,
        )
    await tab.goto(ORIGIN + "/", settle=2.0)
    # The cookies are the credential; this is the identity `lib/auth.ts` reads
    # synchronously in order to render. Without it the shell renders signed out.
    await tab.js(
        f"localStorage.setItem('hirelens.session', {json.dumps(json.dumps(account))});"
        f"localStorage.setItem('hirelens.theme', 'light');"
    )


async def capture(tab, name, frame, *, pad=14, scale=1.25, max_ratio=None):
    box = await tab.js(
        f"""(() => {{ window.scrollTo(0, 0);
                      const e = {frame}; if (!e) return null;
                      const b = e.getBoundingClientRect();
                      return {{x: b.x + scrollX, y: b.y + scrollY,
                               w: b.width, h: b.height}}; }})()"""
    )
    if not box:
        print(f"  !! {name}: frame not found -- {frame}")
        return
    await asyncio.sleep(0.8)
    width, height = box["w"] + pad * 2, box["h"] + pad * 2
    if max_ratio and height > width * max_ratio:
        height = width * max_ratio
    data = (await tab.send(
        "Page.captureScreenshot",
        format="png",
        captureBeyondViewport=True,
        clip={"x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad),
              "width": width, "height": height, "scale": scale},
    ))["data"]
    SHOTS.mkdir(parents=True, exist_ok=True)
    png = SHOTS / f"{name}.png"
    png.write_bytes(base64.b64decode(data))
    image = Image.open(png).convert("RGB")
    image.save(SHOTS / f"{name}.webp", "WEBP", quality=88, method=6)
    png.unlink()
    print(f"  {name}.webp  {image.size[0]}x{image.size[1]}")


async def main(wanted):
    creds = credentials()
    with httpx.Client(base_url=API, timeout=30) as client:
        job_id = client.get("/careers/postings").json()[0]["id"]
    proc, ws_url = await launch()

    def want(name):
        return not wanted or name in wanted

    try:
        async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
            tab = Tab(ws)
            for method in ("Page.enable", "Network.enable", "Runtime.enable"):
                await tab.send(method)

            if want("board") or want("posting"):
                print("public")
                await tab.viewport(1440, 980)
                await tab.goto(ORIGIN + "/", settle=2)
                await tab.js("localStorage.setItem('hirelens.theme','light')")
                if want("board"):
                    await tab.goto(f"{ORIGIN}/careers")
                    await capture(tab, "board", "document.querySelector('main')", scale=1.55)
                if want("posting"):
                    await tab.goto(f"{ORIGIN}/careers/{job_id}")
                    await capture(tab, "posting", "document.querySelector('main')", scale=1.55)

            if want("ranking") or want("verdicts") or want("dropped"):
                print("recruiter")
                await tab.viewport(1440, 1100)
                await sign_in(tab, "recruiter", creds)
                await tab.goto(f"{ORIGIN}/hire/jobs/{job_id}", settle=6)
                if want("ranking"):
                    await capture(tab, "ranking", "window.__card('Ranking')", scale=1.6)
                if want("verdicts") or want("dropped"):
                    await tab.js("document.querySelector('table tbody tr').click()")
                    await asyncio.sleep(5)
                    await tab.js(HELPERS)
                    if want("verdicts"):
                        await capture(
                            tab, "verdicts",
                            "window.__card('Source document').closest('.grid')",
                            pad=0, scale=1.6,
                        )
                    if want("dropped"):
                        # Needs FAKE_MODE=hallucinating and a screening run under it;
                        # the README's provenance section says how that is forced.
                        # Narrower viewport so the pane spans a column, not half of one.
                        await tab.viewport(1000, 1400)
                        await asyncio.sleep(1)
                        await capture(
                            tab, "dropped", "window.__text('could not be traced')",
                            pad=10, scale=2.0,
                        )

            if want("receipt"):
                print("candidate")
                await tab.viewport(1440, 1000)
                await sign_in(tab, "candidate", creds)
                await tab.goto(f"{ORIGIN}/me")
                await tab.js(
                    "[...document.querySelectorAll('button,a')]"
                    ".find(e => /Screening result/i.test(e.textContent))?.click()"
                )
                await asyncio.sleep(4)
                await tab.js(HELPERS)
                await capture(tab, "receipt", "window.__card('Applied')",
                              scale=2.1, max_ratio=1.22)
    finally:
        proc.terminate()
    print("\nrun `python docs/pitch/build.py` to inline them into deck.html")


if __name__ == "__main__":
    asyncio.run(main(set(sys.argv[1:])))
