"""Extract square thumbnails from many videos for promokit.Converge (thumbnail cloud -> product name).

  python thumbs.py manifest.json out_dir [--per 7] [--size 96]

manifest.json: [{"id": "rec01", "path": "/abs/video.mp4", "group": "FIRST-PERSON"}, ...]
Writes out_dir/<id>_<k>.png (centre-square crops spread evenly through each video) and
out_dir/labels.json {id: group}.  Leave out anything with IP / copyright / likeness risk before it gets
here — once it is a 17 px dot nobody will catch it in review.
"""
import argparse, json, os, subprocess, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from promokit import FF, probe_duration

ap = argparse.ArgumentParser(); ap.add_argument("manifest"); ap.add_argument("out")
ap.add_argument("--per", type=int, default=7); ap.add_argument("--size", type=int, default=96)
A = ap.parse_args()

def work(r):
    D = probe_duration(r["path"])
    for i in range(A.per):
        t = D * (i + 0.5) / A.per
        subprocess.run([FF, "-v", "error", "-ss", f"{t:.2f}", "-i", r["path"], "-frames:v", "1", "-vf",
                        f"crop=ih:ih,scale={A.size}:{A.size}", "-y", f"{A.out}/{r['id']}_{i}.png"])
    return r["id"], r["group"]

if __name__ == "__main__":
    os.makedirs(A.out, exist_ok=True)
    recs = json.load(open(A.manifest))
    with Pool(16) as p:
        res = p.map(work, recs)
    json.dump(dict(res), open(f"{A.out}/labels.json", "w"), indent=1)
    from collections import Counter
    print(len(res), "videos", Counter(g for _, g in res))
