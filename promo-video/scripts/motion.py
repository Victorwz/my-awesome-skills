"""Global camera motion per window from dense optical flow, to check control logs against what the video shows.

  python motion.py video.mp4 [--step 0.5] [--from 15 --to 30]

Columns: dx/dy = mean flow (px/frame at 320 px width; + = content moves right/down, i.e. camera pans
left/tilts up), zoom = divergence (+ = moving forward), par = bottom-minus-top dx (large |par| with small
dx = sideways truck with parallax rather than a pan).
Compare against the logged key intervals: if every W shows zoom<0 and every S zoom>0, or left/right yaw
is consistently reversed, the log is mirrored — remap the keys for the overlay rather than trusting the log.
"""
import argparse, cv2, numpy as np

ap = argparse.ArgumentParser(); ap.add_argument("video")
ap.add_argument("--step", type=float, default=0.5)
ap.add_argument("--from", dest="t0", type=float, default=0.0); ap.add_argument("--to", dest="t1", type=float, default=1e9)
A = ap.parse_args()
cap = cv2.VideoCapture(A.video); fps = cap.get(cv2.CAP_PROP_FPS) or 24
cap.set(cv2.CAP_PROP_POS_MSEC, A.t0 * 1000)
Hh, Ww = 176, 320
ys, xs = np.mgrid[0:Hh, 0:Ww]; xc, yc = xs - Ww / 2, ys - Hh / 2
prev, rows, i = None, [], int(A.t0 * fps)
while True:
    ok, f = cap.read()
    if not ok or i / fps > A.t1: break
    g = cv2.cvtColor(cv2.resize(f, (Ww, Hh)), cv2.COLOR_BGR2GRAY)
    if prev is not None:
        fl = cv2.calcOpticalFlowFarneback(prev, g, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        u, v = fl[..., 0], fl[..., 1]
        div = ((u * xc + v * yc) / (xc ** 2 + yc ** 2 + 1)).mean() * 100
        rows.append((i / fps, u.mean(), v.mean(), div, u[Hh // 2:].mean() - u[:Hh // 2].mean()))
    prev = g; i += 1
rows = np.array(rows)
for t0 in np.arange(rows[0, 0], rows[-1, 0], A.step):
    m = rows[(rows[:, 0] >= t0) & (rows[:, 0] < t0 + A.step)].mean(0)
    print(f"{t0:6.1f}  dx={m[1]:+5.2f} dy={m[2]:+5.2f} zoom={m[3]:+5.2f} par={m[4]:+5.2f}")
