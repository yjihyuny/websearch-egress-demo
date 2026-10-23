#!/usr/bin/env python3
"""Regenerate the README media (GIFs and screenshots) with a headless browser.

    python3 -m venv .venv-media && .venv-media/bin/pip install playwright pillow
    .venv-media/bin/playwright install chromium            # one-time browser download
    .venv-media/bin/python tools/record_demo.py            # replay GIFs from the saved traces (offline, no sandbox needed)
    .venv-media/bin/python tools/record_demo.py --live http://127.0.0.1:8890   # also screenshots of the Policy editor / Policy diff tabs

The GIFs replay REAL traces stored in web/langgraph_viewer.html (captured from a sandbox run); nothing is simulated.
--live only READS from the running live server (policy view); it never applies a policy change or starts an agent run.
"""
import argparse, io, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "media"
W, H = 1180, 900
HIDE = "#t-run > .card:first-child, #obs, details.card, .card:has(#wt){display:none!important}"   # hide the live-run form, keep the replay


def gif(frames, path, ms=1700, last_ms=3200):
    ims = [Image.open(io.BytesIO(b)).convert("RGB").quantize(colors=128, method=Image.Quantize.MEDIANCUT) for b in frames]
    ims[0].save(path, save_all=True, append_images=ims[1:], duration=[ms] * (len(ims) - 1) + [last_ms], loop=0, optimize=True)
    print(f"{path.relative_to(ROOT)}  {len(frames)} frames  {path.stat().st_size // 1024} KB")


def replay_frames(pg, idx):
    pg.select_option("#sel", index=idx)
    pg.wait_for_timeout(250)
    n = len(pg.query_selector_all(".st"))
    frames = []
    for i in range(n):
        frames.append(pg.screenshot())
        if i < n - 1:
            pg.click("#next"); pg.wait_for_timeout(200)
    return frames


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--live", help="URL of a running scripts/run.sh server, for policy-tab screenshots")
    a = ap.parse_args(); OUT.mkdir(parents=True, exist_ok=True)
    page = (ROOT / "web" / "langgraph_viewer.html").as_uri()
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": W, "height": H}); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(page); pg.add_style_tag(content=HIDE); pg.wait_for_timeout(500)
        names = [o.inner_text() for o in pg.query_selector_all("#sel option")]
        pick = lambda key: next(i for i, n in enumerate(names) if key in n)
        gif(replay_frames(pg, pick("fetch-allowed")) + replay_frames(pg, pick("fetch-denied")), OUT / "allowed-vs-denied.gif")
        gif(replay_frames(pg, pick("research: packages")), OUT / "research-partial.gif")
        pg.select_option("#sel", index=pick("fetch-denied"))
        for _ in range(3): pg.click("#next")
        pg.screenshot(path=str(OUT / "replay-denied.png"))
        if a.live:
            pg2 = b.new_page(viewport={"width": W, "height": 1100}); pg2.on("pageerror", lambda e: errs.append(str(e)))
            pg2.goto(a.live.rstrip("/") + "/langgraph_viewer.html"); pg2.wait_for_timeout(1500)
            pg2.screenshot(path=str(OUT / "viewer-live.png"))
            pg2.click("text=Policy editor"); pg2.wait_for_timeout(2500); pg2.screenshot(path=str(OUT / "policy-editor.png"), full_page=True)
            pg2.click("text=Policy diff"); pg2.wait_for_timeout(1500); pg2.screenshot(path=str(OUT / "policy-diff.png"))
        b.close()
    if errs: print("page errors:", errs); sys.exit(1)


if __name__ == "__main__":
    main()
