"""Repair a generated clip without touching the original: drop bad frames, soften a window, build a fast-forward.

  python clean_frames.py in.mp4 out.mp4 --drop 1130,1131,1143,1144
  python clean_frames.py in.mp4 out.mp4 --soften 47.0:48.0          # 3-tap [.25 .5 .25] temporal blend
  python clean_frames.py in.mp4 out_x10.mp4 --ff 10 [--taps 4]      # N× fast-forward, each kept frame = weighted
                                                                     # blend of `taps` consecutive frames
Order: drop -> soften -> ff.  Write to a new file and keep the source as is.

Why: a plain N× (keep every Nth frame) amplifies any residual pop into a visible flash; blending a few
consecutive frames makes it read as motion blur.  Dropping 1–2 frames at 24 fps is invisible; dropping
more starts to stutter, so combine a small drop with --soften instead of cutting a whole second.
"""
import argparse, subprocess, numpy as np, cv2, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from promokit import FF

ap = argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("out")
ap.add_argument("--drop", default=""); ap.add_argument("--soften", default="")
ap.add_argument("--ff", type=int, default=1); ap.add_argument("--taps", type=int, default=4)
ap.add_argument("--crf", type=int, default=16)
A = ap.parse_args()
cap = cv2.VideoCapture(A.src); fps = cap.get(cv2.CAP_PROP_FPS) or 24
drop = {int(x) for x in A.drop.split(",") if x.strip()}
fr = []; i = 0
while True:
    ok, f = cap.read()
    if not ok: break
    if i not in drop: fr.append((i, f))
    i += 1
print("read", i, "kept", len(fr))
if A.soften:
    s0, s1 = (float(x) for x in A.soften.split(":"))
    src = [f.astype(np.float32) for _, f in fr]; out = []
    for k, (fi, f) in enumerate(fr):
        if s0 <= fi / fps <= s1 and 0 < k < len(fr) - 1:
            f = (0.25 * src[k - 1] + 0.5 * src[k] + 0.25 * src[k + 1]).clip(0, 255).astype(np.uint8)
        out.append((fi, f))
    fr = out
frames = [f for _, f in fr]
if A.ff > 1:
    w = np.hanning(A.taps + 2)[1:-1]; w /= w.sum()
    frames = [sum(w[j] * frames[min(k + j, len(frames) - 1)].astype(np.float32) for j in range(A.taps)).clip(0, 255).astype(np.uint8)
              for k in range(0, len(frames), A.ff)]
h, w_ = frames[0].shape[:2]
p = subprocess.Popen([FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w_}x{h}", "-r", f"{fps}",
                      "-i", "-", "-c:v", "libx264", "-crf", str(A.crf), "-pix_fmt", "yuv420p", A.out], stdin=subprocess.PIPE)
for f in frames: p.stdin.write(f.tobytes())
p.stdin.close(); p.wait()
print("wrote", A.out, len(frames), "frames", f"{len(frames) / fps:.2f}s")
