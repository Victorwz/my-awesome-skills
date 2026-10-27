"""Template build script: copy next to the project, replace the placeholders, run.

  python build.py list               # segment start times (feed --hits / --sections of bgm.py)
  python build.py seg 05_demo        # re-render one segment while iterating
  python build.py all                # render everything in parallel, concat, mux music
  python build.py concat             # re-mux only (after changing music)

Run with --selftest to render every segment type against generated test footage (no assets needed).
Language: set PROMO_LANG=zh (or any key of LANGS) to build a localised cut into its own segs dir.
"""
import os, sys, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))   # or the skill's scripts/ dir
import promokit as pk

WORK = os.getcwd()          # outputs go where you run it, never into the skill folder
LANG = os.environ.get("PROMO_LANG", "en")
LANGS = {
    "zh": dict(table={"Phrase one.": "短语一", "Phrase two.": "短语二", "TEXT": "文本", "CAMERA": "相机",
                      "Keyboard control": "键盘控制", "MOVE": "移动", "LOOK": "视角"},
               rules=[(r"^Turn (\d+) of (\d+)$", r"第 \1 / \2 轮"), (r"^T(\d+) · TEXT$", r"T\1 · 文本"),
                      (r"^T(\d+) · CAMERA$", r"T\1 · 相机"), (r"^T(\d+) · START$", r"T\1 · 起始")],
               cjk=True),
}
if LANG in LANGS:
    pk.set_language(**LANGS[LANG])

SELFTEST = "--selftest" in sys.argv
if SELFTEST:
    sys.argv.remove("--selftest")
    T = os.path.join(WORK, "_selftest"); os.makedirs(T, exist_ok=True)
    SRC = os.path.join(T, "src.mp4")
    if not os.path.exists(SRC):
        subprocess.run([pk.FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24:duration=40",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", SRC], check=True)
    A = B = C = SRC
else:
    A, B, C = "/path/to/demo_a.mp4", "/path/to/demo_b.mp4", "/path/to/long_rollout.mp4"

turns = [("INIT", 0, 10), ("TEXT", 10, 20), ("CAM", 20, 30)]
keys = [{"code": "KeyW", "start": 21.0, "end": 24.0}, {"code": "ArrowLeft", "start": 23.0, "end": 26.0}]

SEGMENTS = [
    ("01_montage", lambda: pk.Montage([(A, 2.0, "Phrase one."), (B, 5.0, "Phrase two.")])),
    ("02_card", lambda: pk.Card("Section label", "One-line slogan.", A, 3.0)),
    ("03_text", lambda: pk.DemoClip(A, 11.0, 3.0, "TEXT", "A placeholder prompt being typed out.", turns, 30, 2,
                                    tag="SECTION TAG")),
    ("04_cam", lambda: pk.DemoClip(A, 21.0, 3.0, "CAM", turns=turns, total=30, turn_idx=3, keys=keys,
                                   big_hud=True, fade=False)),
    ("05_session", lambda: pk.SessionClip(B, 0.0, 6.0, turns, 30, {1: "Opening prompt.", 2: "Second prompt."}, keys=keys)),
    ("06_ff", lambda: pk.FastForward(C, 10, 40, 4.0, tag="LONG ROLLOUT", sub="One continuous rollout · 10×")),
    ("07_cmp", lambda: pk.StartEnd([(C, 0.5, 33.0)], "Same world, start and end.", dur=3.0)),
    ("08_wall", lambda: pk.Wall((A, 1.0), [(B, 2.0 + i, "STYLE") for i in range(8)],
                                [(C, 1.0 + i, "STYLE") for i in range(16)], "Start from one…", "…branch into many.")),
    ("09_outro", lambda: pk.Outro("Product is open source.", "Placeholder subline.",
                                  [("Item A", "What it is"), ("Item B", "What it is")],
                                  "Try it yourself.", "example.com/demo", "Placeholder invite.", bg=A, brand="Product")),
]

if __name__ == "__main__":
    base = os.path.join(WORK, "_selftest") if SELFTEST else WORK
    pk.main(SEGMENTS, out=os.path.join(base, f"promo_{LANG}.mp4"), bgm=None, workdir=os.path.join(base, f"segs_{LANG}"))
