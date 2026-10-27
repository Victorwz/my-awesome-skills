"""Find single-frame 'pops' (generation artifacts, ghosting, decoder chunk seams) and make contact sheets.

  python frame_pops.py video.mp4 [--from 46 --to 49] [--z 4] [--sheet out.jpg] [--period]

A frame is flagged when its difference to the previous frame is far above the local median
(robust z-score > --z) AND the frame after it snaps back (A-B-A shape), which separates real pops from
fast motion.  --period prints whether flagged frames repeat at a fixed interval (e.g. every 1.0 s at
x.17 s): that is a chunk seam in the generator, so place short shots *between* seams instead of trying
to repair them.  --sheet writes a labelled grid of every frame in the window so you can look yourself —
always look before deleting anything.
"""
import argparse, cv2, numpy as np

ap = argparse.ArgumentParser(); ap.add_argument("video")
ap.add_argument("--from", dest="t0", type=float, default=0.0); ap.add_argument("--to", dest="t1", type=float, default=1e9)
ap.add_argument("--z", type=float, default=4.0); ap.add_argument("--sheet"); ap.add_argument("--cols", type=int, default=8)
ap.add_argument("--period", action="store_true")
A = ap.parse_args()
cap = cv2.VideoCapture(A.video); fps = cap.get(cv2.CAP_PROP_FPS) or 24
cap.set(cv2.CAP_PROP_POS_FRAMES, int(A.t0 * fps))
frames, idx = [], int(A.t0 * fps)
while True:
    ok, f = cap.read()
    if not ok or idx / fps > A.t1: break
    frames.append((idx, f)); idx += 1
small = [cv2.resize(f, (320, 180)).astype(np.float32) for _, f in frames]
d = np.array([0.0] + [np.abs(small[i] - small[i - 1]).mean() for i in range(1, len(small))])
flags = []
for i in range(1, len(d) - 1):
    lo, hi = max(1, i - 24), min(len(d), i + 25)
    med = np.median(d[lo:hi]); mad = np.median(np.abs(d[lo:hi] - med)) + 1e-3
    z = (d[i] - med) / (1.4826 * mad)
    back = np.abs(small[i + 1] - small[i - 1]).mean()     # does i+1 look like i-1 again?
    if z > A.z and back < d[i] * 0.8:
        flags.append(i)
        print(f"frame {frames[i][0]:6d}  t={frames[i][0] / fps:7.3f}s  diff={d[i]:6.2f}  z={z:5.1f}  snapback={back:6.2f}")
if not flags: print("no pops above threshold")
if A.period and len(flags) > 2:
    ts = np.array([frames[i][0] / fps for i in flags]); gaps = np.diff(ts)
    print(f"gaps: median {np.median(gaps):.3f}s  std {gaps.std():.3f}s  phase {np.median(ts % np.median(gaps)):.3f}s")
if A.sheet:
    tw_, th_ = 320, 180; cols = A.cols; rows = (len(frames) + cols - 1) // cols
    sheet = np.zeros((rows * (th_ + 22), cols * tw_, 3), np.uint8)
    for k, (fi, f) in enumerate(frames):
        r, c = divmod(k, cols); y, x = r * (th_ + 22), c * tw_
        sheet[y + 22:y + 22 + th_, x:x + tw_] = cv2.resize(f, (tw_, th_))
        col = (60, 60, 255) if k in flags else (230, 230, 230)
        cv2.putText(sheet, f"{fi} {fi / fps:.2f}s", (x + 4, y + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1)
    cv2.imwrite(A.sheet, sheet, [cv2.IMWRITE_JPEG_QUALITY, 90]); print("sheet", A.sheet)
