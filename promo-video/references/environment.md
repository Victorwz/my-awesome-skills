# Environment notes

## ffmpeg
Shared Linux boxes often have no system ffmpeg. `pip install --user imageio-ffmpeg` ships a static
binary with libx264 and aac. promokit finds it automatically, or set `PROMO_FFMPEG=/path/to/ffmpeg`.
That binary may be old (4.x), so stick to common filters (scale, crop, setpts, fps, select, tile, eq).

Encoding: rawvideo rgb24 → libx264 `-crf 17 -preset medium -pix_fmt yuv420p`, keyint 2 s. All segments
share codec and parameters, so `concat` can stream-copy them. Mux music with `-c:a aac -b:a 192k -shortest
-movflags +faststart` (faststart matters for browser playback over the review server).

## Python deps
numpy, Pillow, scipy (bgm), opencv-python (motion, frame_pops, clean_frames, erase_glyphs), and
playwright for the site recording. Put Playwright in a venv in the scratch dir and run
`playwright install chromium`.

## Headless Chromium on minimal images
Typical error: missing `libgbm.so.1` / `libwayland-server.so.0`. Without root:
```
yumdownloader mesa-libgbm libwayland-server   # or: apt-get download libgbm1 libwayland-server0
rpm2cpio *.rpm | cpio -idm                     # or: dpkg -x *.deb .
LD_LIBRARY_PATH=$PWD/usr/lib64:$LD_LIBRARY_PATH python record_site.py cfg.json rec/
```
Use `wait_until="load"`, not `"networkidle"`, which can time out on pages with polling or analytics.

## Fonts
Bundled in `assets/fonts`: Inter, Inter Display, JetBrains Mono (SIL OFL, licence files included). For
CJK, download Noto Sans SC (OFL) Regular/Medium/Bold/Black `.otf` into a dir and set `PROMO_CJK_DIR`.

## Files and hygiene
- Scratch dirs are temporary. Keep `build.py`, configs, cleaned clips, site recordings, thumbnails,
  music and every deliverable in the project folder (for example `<project>/build/`), with paths in one
  config block at the top of `build.py`.
- Name deliverables by version (`promo_draft_v2.mp4`, `final_zh.mp4`). Keep previous versions until the
  user says otherwise.
- Parallel rendering: `Pool(12)` with one ffmpeg decoder per Reader. Segments with many Readers (Wall
  has 25) are the slowest, so render them first or alone if memory is tight.

## Sharing for review
`nohup python scripts/serve.py <public_dir> 8081 > serve.log 2>&1 &` serves with HTTP Range support,
which browsers need to seek in mp4. Put an `index.html` with a `<video controls>` per cut in the dir,
or symlinks to the cuts. Give the user `http://<host-ip>:8081/` (`hostname -I`). It is reachable by
anyone on that network, so mention that, and how to stop it (`pkill -f serve.py`).
