"""Drive a real web page frame-by-frame with Playwright and screenshot every output frame.

Why frame-by-frame instead of a screen recording: every frame lands exactly on the video clock, typing
speed is controlled, and nothing depends on headless real-time performance.  The compositor
(promokit.BrowserScene) draws the browser chrome, the cursor and the virtual camera on top.

  python record_site.py config.json out_dir

config.json:
{
  "url": "https://example.com/demo",
  "viewport": [1600, 816], "scale": 2, "fps": 24, "dark": true,
  "t_nav": 1.9, "t_end": 7.6,                 # segment seconds: page load starts / recording stops
  "cursor_start": [0.62, 0.75],              # fraction of viewport, cursor enters at the first action - 0.4s
  "actions": [
    {"type": "type",   "selector": "#field-a", "text": "…", "click": 2.75, "t0": 2.85, "t1": 4.65},
    {"type": "type",   "selector": "#field-b", "text": "…", "click": 5.0,  "t0": 5.1,  "t1": 6.3},
    {"type": "select", "selector": "#mode", "label": "First person", "click": 6.65},
    {"type": "press",  "selector": "button.primary", "click": 7.3}      # mouse down only, never released
  ]
}
After each click the pointer drifts down-right off the field so it never covers the text being typed.
'press' holds the button in its pressed state without releasing, so nothing is actually submitted.

Output: out_dir/f_####.jpg (frame index on the segment clock) + timeline.json (cursor per frame, clicks).
Headless Chromium on minimal Linux images may miss libgbm / libwayland-server: see references/environment.md.
"""
import asyncio, json, os, sys
from playwright.async_api import async_playwright

CFG = json.load(open(sys.argv[1])); OUT = sys.argv[2]
FPS = CFG.get("fps", 24); VW, VH = CFG.get("viewport", [1600, 816])

def ease(x):
    x = max(0.0, min(1.0, x)); return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2

async def main():
    os.makedirs(OUT, exist_ok=True)
    acts = sorted(CFG["actions"], key=lambda a: a["click"])
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=CFG.get("scale", 2),
                                  color_scheme="dark" if CFG.get("dark", True) else "light")
        pg = await ctx.new_page()
        # warm-up load to learn element boxes (same layout as the recorded load); 'load' not 'networkidle',
        # which can hang forever on pages with long-polling or analytics
        await pg.goto(CFG["url"], wait_until="load"); await pg.wait_for_timeout(3000)
        boxes = {}
        for a in acts:
            bb = await pg.locator(a["selector"]).first.bounding_box()
            boxes[a["selector"]] = [bb["x"], bb["y"], bb["width"], bb["height"]]
        await pg.goto("about:blank")

        def at(sel, fx, fy):
            x, y, w, h = boxes[sel]; return (x + w * fx, y + h * fy)
        start = (VW * CFG.get("cursor_start", [0.62, 0.75])[0], VH * CFG.get("cursor_start", [0.62, 0.75])[1])
        keys = [(acts[0]["click"] - 0.4, start)]
        for a in acts:
            tgt = at(a["selector"], 0.3 if a["type"] == "type" else 0.45, 0.45)
            if keys[-1][0] < a["click"] - 0.3:
                keys.append((a["click"] - 0.3, keys[-1][1]))        # rest, then glide in
            keys.append((a["click"], tgt))
            if a["type"] == "type":
                keys.append((a["click"] + 0.4, at(a["selector"], 0.86, 1.32)))   # park off the text
        def cursor_at(t):
            if t < keys[0][0]: return None
            for (t0, p0), (t1, p1) in zip(keys, keys[1:]):
                if t0 <= t < t1:
                    u = ease((t - t0) / max(t1 - t0, 1e-6))
                    return (p0[0] + (p1[0] - p0[0]) * u, p0[1] + (p1[1] - p0[1]) * u)
            return keys[-1][1]

        tl = {"viewport": [VW, VH], "frames": {}, "t_nav": CFG["t_nav"], "t_end": CFG["t_end"],
              "clicks": [a["click"] for a in acts], "boxes": boxes}
        done, typed, down, nav = set(), {}, False, False
        f0, f1 = int(round(CFG["t_nav"] * FPS)), int(round(CFG["t_end"] * FPS))
        for fi in range(f0, f1):
            t = fi / FPS
            if not nav:
                await pg.goto(CFG["url"], wait_until="commit"); nav = True
            cur = cursor_at(t)
            if cur: await pg.mouse.move(*cur)
            for i, a in enumerate(acts):
                if t >= a["click"] and i not in done:
                    done.add(i)
                    if a["type"] == "type":
                        await pg.mouse.click(*at(a["selector"], 0.3, 0.45))
                    elif a["type"] == "select":
                        await pg.select_option(a["selector"], label=a["label"])
                        await pg.locator(a["selector"]).blur()
                    elif a["type"] == "press" and not down:
                        await pg.mouse.move(*at(a["selector"], 0.45, 0.55)); await pg.mouse.down(); down = True
                if a["type"] == "type" and t >= a["t0"]:
                    want = int(len(a["text"]) * min(1, (t - a["t0"]) / (a["t1"] - a["t0"])))
                    if want > typed.get(i, 0):
                        await pg.keyboard.type(a["text"][typed.get(i, 0):want]); typed[i] = want
            if fi == f0: await pg.wait_for_timeout(120)
            elif fi < f0 + 14: await pg.wait_for_timeout(60)       # let the page paint while it loads
            await pg.screenshot(path=f"{OUT}/f_{fi:04d}.jpg", type="jpeg", quality=93)
            tl["frames"][fi] = {"t": t, "cursor": cur, "down": down}
        json.dump(tl, open(f"{OUT}/timeline.json", "w"), indent=1)
        await b.close()
        print("frames", f1 - f0, "boxes", boxes)

asyncio.run(main())
