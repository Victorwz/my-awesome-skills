"""promokit: a small frame-compositing kit for product promo / demo videos.

Every frame is drawn with PIL on top of decoded source frames and piped into ffmpeg (libx264).
A video is a list of named segments; each segment renders to its own mp4 in parallel, then the
segments are concatenated (stream copy) and muxed with a music track.

    import promokit as pk
    SEGMENTS = [("01_card", lambda: pk.Card("Section label", "Big slogan.", bg="a.mp4", bg_t=3.0)), ...]
    if __name__ == "__main__":
        pk.main(SEGMENTS, out="promo.mp4", bgm="bgm.wav", workdir="segs")

CLI provided by pk.main:  all | seg <name>... | concat | list
Environment:
  PROMO_FFMPEG      path to an ffmpeg binary (else PATH, else imageio_ffmpeg's bundled binary)
  PROMO_FONT_DIR    extra font directory searched before the bundled assets/fonts
  PROMO_CJK_DIR     directory with NotoSansSC-{Regular,Medium,Bold,Black}.otf (used when a CJK language is set)
"""
import os, re, sys, json, math, shutil, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
W, H, FPS = 1920, 1080, 24

# ---------------------------------------------------------------- ffmpeg
def find_ffmpeg():
    p = os.environ.get("PROMO_FFMPEG") or shutil.which("ffmpeg")
    if p: return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise SystemExit("no ffmpeg: install one, `pip install imageio-ffmpeg`, or set PROMO_FFMPEG")
FF = find_ffmpeg()

def probe_duration(path):
    o = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", o)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0

# ---------------------------------------------------------------- style (monochrome by default)
# Hierarchy comes from size and weight, not colour. Users of past promos rejected blue/orange accents.
BG = (6, 6, 8)
FG = (245, 245, 245)
MUTED = FG
ACCENT = FG

# ---------------------------------------------------------------- language
_LANG = {"table": {}, "rules": [], "cjk": False}

def set_language(table=None, rules=None, cjk=False):
    """table: exact string -> translation; rules: [(regex, replacement)] for templated strings.
    cjk=True swaps Inter* fonts for Noto Sans SC and centres pill labels vertically (CJK glyphs sit
    differently on the baseline, so top-anchored text looks off-centre in rounded boxes)."""
    _LANG.update(table=table or {}, rules=rules or [], cjk=cjk)

def tr(s):
    t = _LANG["table"]
    if not t and not _LANG["rules"]: return s
    if s in t: return t[s]
    for pat, rep in _LANG["rules"]:
        if re.match(pat, s): return re.sub(pat, rep, s)
    return s

def is_cjk(): return _LANG["cjk"]

_CJK_WEIGHT = {"Light": "Regular", "Regular": "Regular", "Medium": "Medium", "SemiBold": "Bold", "Bold": "Bold",
               "ExtraBold": "Black"}
_fc = {}
def font(name, size):
    """name like 'Inter-SemiBold', 'InterDisplay-Bold', 'JetBrainsMono-Medium'."""
    k = (name, size, is_cjk())
    if k in _fc: return _fc[k]
    if is_cjk() and name.startswith("Inter"):
        w = name.split("-", 1)[1]
        d = os.environ.get("PROMO_CJK_DIR", "")
        _fc[k] = ImageFont.truetype(os.path.join(d, f"NotoSansSC-{_CJK_WEIGHT.get(w, 'Regular')}.otf"), size)
        return _fc[k]
    for d in (os.environ.get("PROMO_FONT_DIR"), os.path.join(HERE, "..", "assets", "fonts")):
        if d and os.path.exists(os.path.join(d, f"{name}.ttf")):
            _fc[k] = ImageFont.truetype(os.path.join(d, f"{name}.ttf"), size)
            return _fc[k]
    raise FileNotFoundError(f"font {name}")

# ---------------------------------------------------------------- easing
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def ease_out(x): x = clamp(x); return 1 - (1 - x) ** 3
def ease_io(x): x = clamp(x); return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2
def ramp(t, t0, t1): return clamp((t - t0) / max(t1 - t0, 1e-6))

def keyframes(ks, t, log_last=False):
    """piecewise ease_io between (t, v0, v1, ...) rows; log_last interpolates the last value
    geometrically (use for zoom so a 1x->2x push feels constant-speed)."""
    for a, b in zip(ks, ks[1:]):
        if a[0] <= t <= b[0]:
            u = ease_io((t - a[0]) / max(b[0] - a[0], 1e-6))
            out = [x + (y - x) * u for x, y in zip(a[1:], b[1:])]
            if log_last:
                out[-1] = math.exp(math.log(a[-1]) + (math.log(b[-1]) - math.log(a[-1])) * u)
            return out
    return list(ks[-1][1:] if t > ks[0][0] else ks[0][1:])

# ---------------------------------------------------------------- video IO
class Reader:
    """Decode `path` from `start` (source seconds) at FPS, cover-scaled and centre-cropped to `size`.
    speed>1 fast-forwards by dropping frames; for long fast-forwards prefer a pre-blended file
    (see clean_frames.py) so residual generation pops read as motion blur instead of flicker."""
    def __init__(self, path, start=0.0, size=(W, H), speed=1.0, dur=None):
        self.w, self.h = size
        vf = (f"setpts=(PTS-STARTPTS)/{speed},fps={FPS},"
              f"scale={self.w}:{self.h}:force_original_aspect_ratio=increase:flags=bicubic,crop={self.w}:{self.h}")
        cmd = [FF, "-v", "error", "-ss", f"{start:.3f}", "-i", path]
        if dur is not None:
            cmd += ["-t", f"{dur * speed + 1.0:.3f}"]
        cmd += ["-vf", vf, "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 8)
        self.last = None

    def read(self):
        n = self.w * self.h * 3
        b = self.p.stdout.read(n)
        if len(b) == n:
            self.last = Image.frombuffer("RGB", (self.w, self.h), b, "raw", "RGB", 0, 1)
        elif self.last is None:
            self.last = Image.new("RGB", (self.w, self.h), BG)
        return self.last          # past the end: hold the last frame

    def close(self):
        try:
            self.p.stdout.close(); self.p.kill()
        except Exception:
            pass

class Writer:
    def __init__(self, path, crf=17):
        cmd = [FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
               "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
               "-x264-params", f"keyint={FPS * 2}", path]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def write(self, im):
        if im.mode != "RGB": im = im.convert("RGB")
        self.p.stdin.write(im.tobytes())

    def close(self):
        self.p.stdin.close(); self.p.wait()

# ---------------------------------------------------------------- drawing helpers
def layer(): return Image.new("RGBA", (W, H), (0, 0, 0, 0))

def with_alpha(c, a): return (c[0], c[1], c[2], int(255 * clamp(a)) if a <= 1 else int(a))

def text(d, xy, s, f, fill=FG, a=1.0, anchor="la"):
    d.text(xy, tr(s), font=f, fill=with_alpha(fill, a), anchor=anchor)

def tw(s, f): return f.getlength(tr(s))

def wrap(s, f, maxw):
    s = tr(s)
    if re.search(r"[぀-ヿ一-鿿]", s):   # CJK: break between characters
        lines, cur = [], ""
        for ch in s:
            if tw(cur + ch, f) <= maxw or not cur: cur += ch
            else: lines.append(cur); cur = ch
        return lines + ([cur] if cur else [])
    lines, cur = [], ""
    for w_ in s.split():
        t = (cur + " " + w_).strip()
        if tw(t, f) <= maxw or not cur: cur = t
        else: lines.append(cur); cur = w_
    return lines + ([cur] if cur else [])

def shadow_text(base, xy, s, f, a=1.0, anchor="mm", blur=18, strength=0.75):
    """big words over busy footage: soft dark halo first, then the glyphs."""
    sh = layer(); text(ImageDraw.Draw(sh), (xy[0], xy[1] + 6), s, f, (0, 0, 0), strength * a, anchor)
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(sh); base.alpha_composite(sh)
    text(ImageDraw.Draw(base), xy, s, f, FG, a, anchor)

def blur_bg(im, radius=18, dark=0.5):
    small = im.resize((W // 4, H // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(radius / 4))
    return Image.blend(small.resize((W, H), Image.BILINEAR), Image.new("RGB", (W, H), BG), dark)

_grad = {}
def bottom_gradient(h0=430, strength=0.78, top=True):
    """dark scrim under the HUD (and a lighter one at the top for tags) so white text reads on any frame."""
    k = (h0, strength, top)
    if k not in _grad:
        ys = np.arange(H)
        a = np.clip((ys - (H - h0)) / h0, 0, 1) ** 1.6 * 255 * strength
        if top:
            a = np.maximum(a, np.clip((260 - ys) / 260, 0, 1) ** 2 * 255 * 0.55)
        g = Image.new("RGBA", (W, H), BG + (0,))
        g.putalpha(Image.fromarray(np.repeat(a[:, None], W, 1).astype(np.uint8)))
        _grad[k] = g
    return _grad[k]

def pill(d, x, y, label, color=FG, a=1.0, f=None, pad=(14, 7), filled=False):
    """rounded tag. Outline pills get a translucent BG fill so they stay legible on bright frames.
    Returns the box so callers can place text after it (never hard-code the pill width)."""
    f = f or font("Inter-Bold", 22)
    box = (x, y, x + tw(label, f) + 2 * pad[0], y + f.size + 2 * pad[1])
    if is_cjk():
        xy, anchor = (x + pad[0], (box[1] + box[3]) / 2), "lm"
    else:
        xy, anchor = (x + pad[0], y + pad[1] - 1), "la"
    r = (box[3] - box[1]) // 2
    if filled:
        d.rounded_rectangle(box, radius=r, fill=with_alpha(color, a))
        text(d, xy, label, f, BG, a, anchor=anchor)
    else:
        d.rounded_rectangle(box, radius=r, fill=with_alpha(BG, 0.62 * a), outline=with_alpha(color, 0.9 * a), width=2)
        text(d, xy, label, f, color, a, anchor=anchor)
    return box

def caret(d, x, y, h, t, color=FG, a=1.0):
    if int(t * 2.2) % 2 == 0:
        d.rectangle((x + 3, y, x + 6, y + h), fill=with_alpha(color, a))

def rounded_paste(dst, tile, xy, radius=16, a=1.0):
    m = Image.new("L", tile.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, tile.size[0], tile.size[1]), radius=radius, fill=int(255 * a))
    dst.paste(tile, (int(xy[0]), int(xy[1])), m)

def fade_black(im, f):
    return im if f >= 1 else Image.blend(Image.new("RGB", im.size, (0, 0, 0)), im.convert("RGB"), clamp(f))

def erase_glyphs(im, box, thresh=10, dilate=7, radius=9, grow=(20, 10)):
    """Remove text burned into reused footage (an old draft's tagline, a watermark) inside `box`.
    Masks only pixels that deviate from the local median backdrop and inpaints those. Do not repaint
    the whole box with a top-to-bottom ramp: on a busy backdrop that leaves a visible rectangle with
    vertical seams. Check the result on every background that passes behind the box, not just the first."""
    import cv2
    a = np.asarray(im.convert("RGB")).copy()
    x0, y0, x1, y1 = box; x0, y0, x1, y1 = max(0, x0 - grow[0]), max(0, y0 - grow[1]), x1 + grow[0], y1 + grow[1]
    roi = a[y0:y1, x0:x1]
    dev = np.abs(roi.astype(np.int16) - cv2.medianBlur(roi, 31).astype(np.int16)).max(-1)
    m = cv2.dilate((dev > thresh).astype(np.uint8) * 255, np.ones((dilate, dilate), np.uint8))
    a[y0:y1, x0:x1] = cv2.inpaint(roi, m, radius, cv2.INPAINT_TELEA)
    return Image.fromarray(a)

# ---------------------------------------------------------------- keyboard HUD
KEY_LAYOUT = {"W": (1, 0), "A": (0, 1), "S": (1, 1), "D": (2, 1),
              "ArrowUp": (4.6, 0), "ArrowLeft": (3.6, 1), "ArrowDown": (4.6, 1), "ArrowRight": (5.6, 1)}
KEY_GLYPH = {"ArrowUp": "↑", "ArrowLeft": "←", "ArrowDown": "↓", "ArrowRight": "→"}

def key_hud(base, x, y, active, a=1.0, u=64, gap=10, labels=("MOVE", "LOOK")):
    """WASD + arrows; pressed keys are filled with a soft glow. Returns (w, h)."""
    d = ImageDraw.Draw(base)
    f = font("Inter-Bold", int(u * 0.42)); fl = font("Inter-SemiBold", int(u * 0.24))
    for k, (cx, cy) in KEY_LAYOUT.items():
        kx = x + cx * (u + gap); ky = y + cy * (u + gap)
        if k in active:
            glow = Image.new("RGBA", (u + 60, u + 60), (0, 0, 0, 0))
            ImageDraw.Draw(glow).rounded_rectangle((30, 30, 30 + u, 30 + u), radius=14, fill=with_alpha(FG, 0.85 * a))
            base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)), (int(kx - 30), int(ky - 30)))
            d.rounded_rectangle((kx, ky, kx + u, ky + u), radius=14, fill=with_alpha(FG, a))
            text(d, (kx + u / 2, ky + u / 2), KEY_GLYPH.get(k, k), f, BG, a, anchor="mm")
        else:
            d.rounded_rectangle((kx, ky, kx + u, ky + u), radius=14, fill=(255, 255, 255, int(28 * a)),
                                outline=(255, 255, 255, int(90 * a)), width=2)
            text(d, (kx + u / 2, ky + u / 2), KEY_GLYPH.get(k, k), f, FG, 0.85 * a, anchor="mm")
    if labels:
        text(d, (x + 1.5 * (u + gap) - gap / 2, y + 2 * (u + gap) + 4), labels[0], fl, MUTED, a, anchor="ma")
        text(d, (x + 5.1 * (u + gap) - gap / 2, y + 2 * (u + gap) + 4), labels[1], fl, MUTED, a, anchor="ma")
    return (6.6 * (u + gap), 2 * (u + gap) + 30)

def active_keys(intervals, t):
    """intervals: [{code, start, end}] in source seconds; codes like 'KeyW' or 'ArrowLeft'."""
    return {iv["code"].replace("Key", "") for iv in intervals if iv["start"] <= t < iv["end"]}

def key_intervals(events, t0=0.0, remap=None, unit=1000.0):
    """press/release events [{t, code, pressed}] (t in ms relative to t0) -> intervals.
    remap fixes logs whose key sense disagrees with the rendered motion (verify with motion.py first)."""
    remap = remap or {}; down = {}; out = []
    for e in sorted(events, key=lambda e: e["t"]):
        ts = t0 + e["t"] / unit; code = remap.get(e["code"], e["code"])
        if e["pressed"]: down[code] = ts
        elif code in down: out.append({"code": code, "start": down.pop(code), "end": ts})
    return out

# ---------------------------------------------------------------- turn timeline
TURN_LABEL = {"INIT": "START", "TEXT": "TEXT", "CAM": "CAMERA"}

def turn_timeline(d, turns, total, now, a=1.0, x0=96, x1=W - 96, y=1032):
    """turns: [(kind, t0, t1)] on the session clock. Shows which control drives each stretch."""
    for i, (kind, t0, t1) in enumerate(turns):
        xa = x0 + (x1 - x0) * t0 / total + 3; xb = x0 + (x1 - x0) * t1 / total - 3
        done = clamp((now - t0) / max(t1 - t0, 1e-6))
        d.rounded_rectangle((xa, y, xb, y + 6), radius=3, fill=with_alpha(FG, 0.28 * a))
        if done > 0:
            d.rounded_rectangle((xa, y, xa + (xb - xa) * done, y + 6), radius=3, fill=with_alpha(FG, a))
        cur = t0 <= now < t1
        text(d, (xa, y - 26), f"T{i + 1} · {TURN_LABEL.get(kind, kind)}",
             font("Inter-Bold" if cur else "Inter-Medium", 17), FG, a * (1 if cur else 0.7))
    px = x0 + (x1 - x0) * clamp(now / total)
    d.ellipse((px - 7, y - 4, px + 7, y + 10), fill=with_alpha(FG, a))

# ================================================================ segments
class Seg:
    dur = 1.0
    def setup(self): pass
    def frame(self, t): raise NotImplementedError
    def close(self): pass

class Card(Seg):
    """Section title: small label + big slogan over a blurred, darkened still-moving background."""
    def __init__(self, label, slogan, bg=None, bg_t=0.0, dur=2.0, x=170):
        self.label, self.slogan, self.bg, self.bg_t, self.dur, self.x = label, slogan, bg, bg_t, dur, x
    def setup(self):
        self.r = Reader(self.bg, self.bg_t, size=(W // 4, H // 4), dur=self.dur + 0.5) if self.bg else None
    def frame(self, t):
        if self.r:
            v = self.r.read().filter(ImageFilter.GaussianBlur(5)).resize((W, H), Image.BILINEAR)
            im = Image.blend(v, Image.new("RGB", (W, H), BG), 0.62).convert("RGBA")
        else:
            im = Image.new("RGBA", (W, H), BG + (255,))
        L = layer(); d = ImageDraw.Draw(L)
        e1, e2 = ease_out(ramp(t, 0.0, 0.5)), ease_out(ramp(t, 0.12, 0.65))
        out = 1 - ramp(t, self.dur - 0.18, self.dur)
        d.rectangle((self.x, 420, self.x + 56 * e1, 424), fill=with_alpha(ACCENT, out))
        text(d, (self.x, 442 + 12 * (1 - e1)), self.label, font("Inter-SemiBold", 34), ACCENT, e1 * out)
        text(d, (self.x - 4, 500 + 24 * (1 - e2)), self.slogan, font("InterDisplay-Bold", 92), FG, e2 * out)
        im.alpha_composite(L)
        return im

class Montage(Seg):
    """Fast cut of N shots, one big word/phrase per shot (the classic one-phrase-per-capability opener)."""
    def __init__(self, shots, per=1.0, dim=0.28, size=132):
        self.shots, self.per, self.dim, self.size = shots, per, dim, size    # shots: [(path, start, words)]
        self.dur = per * len(shots)
    def setup(self):
        self.rs = [Reader(p, s, dur=self.per + 0.2) for p, s, _ in self.shots]
    def frame(self, t):
        i = min(int(t / self.per), len(self.shots) - 1); lt = t - i * self.per
        im = Image.blend(self.rs[i].read(), Image.new("RGB", (W, H), BG), self.dim).convert("RGBA")
        e = ease_out(lt / 0.35)
        shadow_text(im, (W / 2, H / 2 + 30 * (1 - e)), self.shots[i][2], font("InterDisplay-ExtraBold", self.size), e)
        return im

class DemoClip(Seg):
    """One window of a demo video with the control HUD.

    kind TEXT: prompt typed out with a caret after a filled TEXT pill.
    kind CAM : 'Keyboard control · ↑' line + key HUD (or one big HUD bottom-right with big_hud=True).
    turns/total draw the session timeline; tag draws a top-left pill (set tag=None to hide it, and
    counter=False to hide 'Turn x of n').  fade=False for a clip that continues the previous one,
    otherwise the HUD visibly blinks at the cut.
    """
    def __init__(self, path, src, dur, kind="TEXT", prompt=None, turns=None, total=None, turn_idx=1,
                 tag=None, counter=True, keys=None, big_hud=False, fade=True, speed=1.0, tl_shift=0.0):
        self.path, self.src, self.dur, self.kind, self.prompt = path, src, dur, kind, prompt
        self.turns, self.total, self.turn_idx, self.tag, self.counter = turns or [], total, turn_idx, tag, counter
        self.ivs, self.big_hud, self.fade, self.speed, self.tl_shift = keys or [], big_hud, fade, speed, tl_shift
    def setup(self):
        self.r = Reader(self.path, self.src, speed=self.speed, dur=self.dur + 0.5)
    def frame(self, t):
        a = ease_out(ramp(t, 0, 0.3)) if self.fade else 1.0
        return self.render(self.r.read(), t, self.src + t * self.speed, a)
    def render(self, im, t, st, a):
        """t: seconds since this prompt started (output clock); st: source seconds."""
        im = im.convert("RGBA"); im.alpha_composite(bottom_gradient())
        L = layer(); d = ImageDraw.Draw(L)
        if self.tag:
            pill(d, 72, 60, self.tag, ACCENT, a)
            if self.counter and len(self.turns) > 1:
                text(d, (74, 108), f"Turn {self.turn_idx} of {len(self.turns)}", font("Inter-Medium", 22), FG, 0.8 * a)
        if self.turns:
            turn_timeline(d, self.turns, self.total or self.turns[-1][2], st - self.tl_shift, a)
        if self.kind == "TEXT" and self.prompt:
            fp = font("Inter-Medium", 34)
            lines = wrap(self.prompt, fp, 1280)
            total_chars = sum(len(l) for l in lines)
            nshow = int(total_chars * ease_io(ramp(t, 0.15, min(1.3, self.dur * 0.45))))
            y = 940 - 46 * (len(lines) - 1)
            pb = pill(d, 96, y - 6, "TEXT", FG, a, f=font("Inter-Bold", 20), filled=True)
            x = pb[2] + 18; shown = 0
            for li, ln in enumerate(lines):
                seg = ln[: max(0, min(len(ln), nshow - shown))]
                text(d, (x, y + li * 46), seg, fp, FG, a, anchor="la")
                if shown <= nshow < shown + len(ln) or (li == len(lines) - 1 and nshow >= total_chars):
                    caret(d, x + fp.getlength(seg), y + li * 46 + 2, 34, t, FG, a)
                shown += len(ln)
        elif self.kind == "CAM":
            act = active_keys(self.ivs, st)
            if self.big_hud:
                u = 76
                key_hud(L, W - 96 - 6.6 * (u + 12), 1032 - 60 - 2 * (u + 12) - 30, act, a, u=u, gap=12)
            else:
                pb = pill(d, 96, 934, "CAMERA", FG, a, f=font("Inter-Bold", 20), filled=True)
                seq = " ".join(KEY_GLYPH.get(k, k) for k in sorted(act)) if act else "—"
                fl = font("Inter-Medium", 34)
                text(d, (pb[2] + 18, 934), "Keyboard control", fl, FG, a)
                text(d, (pb[2] + 18 + tw("Keyboard control", fl) + 24, 936), f"· {seq}", font("Inter-Bold", 34), FG, a)
                key_hud(L, W - 96 - 6.6 * 74, 800, act, a)
        im.alpha_composite(L)
        return im

class SessionClip(DemoClip):
    """A whole multi-turn session played continuously (sped up); the HUD follows the live turn.
    prompts: {turn_no: text}.  cut=(c0, c1) removes source seconds c0..c1 (turns/total then describe the
    edited session).  Prefer folding a weak turn into its neighbour (relabel turns) over cutting: a hard
    cut inside one continuous rollout reads as a jump."""
    def __init__(self, path, src, speed, turns, total, prompts, keys=None, tag=None, counter=True,
                 type_first=True, fade=False, cut=None):
        super().__init__(path, src, (total - src) / speed, "TEXT", None, turns, total, 1, tag, counter, keys,
                         big_hud=False, fade=fade, speed=speed)
        self.prompts, self.type_first, self.cut = prompts, type_first, cut
    def setup(self):
        self.r = Reader(self.path, self.src, speed=self.speed, dur=self.dur + 0.5)
        self.r2 = Reader(self.path, self.cut[1], speed=self.speed, dur=self.dur + 0.5) if self.cut else None
    def frame(self, t):
        et = min(self.src + t * self.speed, self.total - 1e-3)
        after = self.cut is not None and et >= self.cut[0]
        self.tl_shift = self.cut[1] - self.cut[0] if after else 0.0
        st = et + self.tl_shift
        i = next((i for i, (_, a, b) in enumerate(self.turns) if a <= et < b), len(self.turns) - 1)
        kind, t0, _ = self.turns[i]
        self.turn_idx, self.kind, self.prompt = i + 1, "CAM" if kind == "CAM" else "TEXT", self.prompts.get(i + 1)
        lt = (et - t0) / self.speed
        if i == 0 and self.src > 0:
            lt = t if self.type_first else 99.0
        im = self.r2.read() if after else self.r.read()
        return self.render(im, lt, st, ease_out(ramp(t, 0, 0.3)) if self.fade else 1.0)

class FastForward(Seg):
    """Long rollout fast-forwarded with a running clock + progress bar ('m:ss of 1:00 generated')."""
    def __init__(self, path, speed, total, dur, tag=None, sub=None, ticks=10, pre_sped=False):
        self.path, self.speed, self.total, self.dur, self.tag, self.sub, self.ticks = path, speed, total, dur, tag, sub, ticks
        self.pre_sped = pre_sped   # path is already the blended N× file from clean_frames.py
    def setup(self):
        self.r = Reader(self.path, 0.0, speed=1.0 if self.pre_sped else self.speed, dur=self.dur)
    def frame(self, t):
        im = self.r.read().convert("RGBA"); im.alpha_composite(bottom_gradient())
        L = layer(); d = ImageDraw.Draw(L)
        src = min(self.total, t * self.speed); a = ease_out(ramp(t, 0, 0.3))
        if self.tag: pill(d, 72, 60, self.tag, ACCENT, a)
        if self.sub: text(d, (74, 108), self.sub, font("Inter-Medium", 22), FG, 0.8 * a)
        tm = int(self.total)
        text(d, (W - 96, 70), f"{int(src // 60)}:{int(src % 60):02d}", font("InterDisplay-Bold", 96), FG, a, anchor="ra")
        text(d, (W - 100, 180), f"of {tm // 60}:{tm % 60:02d} generated", font("Inter-Medium", 24), MUTED, a, anchor="ra")
        x0, x1, y = 96, W - 96, 1020
        d.rounded_rectangle((x0, y, x1, y + 8), radius=4, fill=(255, 255, 255, int(50 * a)))
        d.rounded_rectangle((x0, y, x0 + (x1 - x0) * src / self.total, y + 8), radius=4, fill=with_alpha(ACCENT, a))
        for m in range(0, int(self.total) + 1, self.ticks):
            text(d, (x0 + (x1 - x0) * m / self.total, y - 30), f"{m}s", font("Inter-Medium", 18), MUTED, a, anchor="ma")
        im.alpha_composite(L)
        return im

class StartEnd(Seg):
    """Rows of (path, start_t, end_t): START and END tiles side by side to prove long-range consistency."""
    def __init__(self, rows, title, dur=6.0):
        self.rows, self.title, self.dur = rows, title, dur
        n = len(rows); self.TH = min(461, (H - 170 - 22 * (n - 1)) // n); self.TW = int(self.TH * 16 / 9)
    def setup(self):
        self.rs = [(Reader(p, a, (self.TW, self.TH), dur=self.dur), Reader(p, b, (self.TW, self.TH), dur=self.dur))
                   for p, a, b in self.rows]
    def frame(self, t):
        im = Image.new("RGBA", (W, H), BG + (255,)); L = layer(); d = ImageDraw.Draw(L)
        text(d, (W / 2, 62), self.title, font("InterDisplay-Bold", 46), FG, ease_out(ramp(t, 0, 0.4)), anchor="ma")
        gx = (W - 2 * self.TW - 60) // 2
        for ri, ((ra, rb), (_, s0, s1)) in enumerate(zip(self.rs, self.rows)):
            y = 150 + ri * (self.TH + 22)
            for ci, (fr, lab, tt) in enumerate([(ra.read(), "START", s0 + t), (rb.read(), "END", s1 + t)]):
                x = gx + ci * (self.TW + 60); k = ri * 2 + ci
                e = ease_out(ramp(t, 0.1 + 0.15 * k, 0.6 + 0.15 * k))
                rounded_paste(im, fr, (x, y + int(20 * (1 - e))), 16, e)
                pill(d, x + 18, y + 18, f"{lab}  {int(tt // 60)}:{int(tt % 60):02d}", FG, e, f=font("Inter-Bold", 20), filled=True)
            text(d, (W / 2, y + self.TH / 2), "→", font("Inter-Bold", 44), FG, 0.8, anchor="mm")
        im.alpha_composite(L)
        return im

class Wall(Seg):
    """One video full-screen -> shrinks to the centre of a 3x3 grid -> grid becomes the centre of a 5x5.
    center=(path, t); ring1: 8 (path, t, label); ring2: 16 (path, t, label). Labels sit on their own layer
    (drawing translucent text straight onto an RGBA base replaces pixels instead of blending)."""
    def __init__(self, center, ring1, ring2, cap_start, cap_end, cap_sub="", tag=None, dur=8.0):
        self.center, self.ring1, self.ring2, self.dur = center, ring1, ring2, dur
        self.cap_start, self.cap_end, self.cap_sub, self.tag = cap_start, cap_end, cap_sub, tag
    def setup(self):
        self.c = Reader(self.center[0], self.center[1], dur=self.dur)
        self.r1 = [Reader(p, s, (640, 360), dur=self.dur) for p, s, _ in self.ring1]
        self.r2 = [Reader(p, s, (384, 216), dur=self.dur) for p, s, _ in self.ring2]
        self.pos3 = [(i, j) for j in range(3) for i in range(3) if (i, j) != (1, 1)]
        self.pos5 = [(i, j) for j in range(5) for i in range(5) if not (1 <= i <= 3 and 1 <= j <= 3)]
    def frame(self, t):
        im = Image.new("RGBA", (W, H), BG + (255,)); LB = layer(); dl = ImageDraw.Draw(LB)
        cf = self.c.read(); f1 = [r.read() for r in self.r1]; f2 = [r.read() for r in self.r2]
        g = 10
        pA = ease_io(ramp(t, 0.8, 2.0)); pB = ease_io(ramp(t, 3.6, 4.8)); zo = 1 + 0.04 * ramp(t, 4.8, self.dur)
        cw = (W / 3 + (W / 5 - W / 3) * pB) / zo; ch = (H / 3 + (H / 5 - H / 3) * pB) / zo
        ox, oy = W / 2 - 1.5 * cw, H / 2 - 1.5 * ch
        def put(fr, x, y, label, a=1.0):
            if cw < 4 or a <= 0: return
            tile = fr.resize((max(1, int(cw - g)), max(1, int(ch - g))), Image.BILINEAR)
            rounded_paste(im, tile, (x + g / 2, y + g / 2), max(2, int(12 * cw / 384)), a)
            if label and cw > 200:
                pill(dl, x + g / 2 + 10, y + g / 2 + 10, label, FG, a * 0.95, f=font("Inter-Bold", 15), pad=(9, 4))
        for idx, (i, j) in enumerate(self.pos5):
            fx, fy = W / 2 + (i - 2) * cw - cw / 2, H / 2 + (j - 2) * ch - ch / 2
            dl_ = 0.04 * (abs(i - 2) + abs(j - 2)) + 0.02 * idx
            e = ease_out(ramp(t, 3.7 + dl_, 4.7 + dl_))
            if e > 0 and idx < len(f2):
                sx, sy = W / 2 - cw / 2, H / 2 - ch / 2
                put(f2[idx], sx + (fx - sx) * e, sy + (fy - sy) * e, self.ring2[idx][2], e)
        for idx, (i, j) in enumerate(self.pos3):
            e = ease_out(ramp(t, 1.4 + 0.036 * idx, 2.4 + 0.036 * idx))
            if e > 0 and idx < len(f1):
                sx, sy = ox + cw, oy + ch
                put(f1[idx], sx + (ox + i * cw - sx) * e, sy + (oy + j * ch - sy) * e, self.ring1[idx][2], e)
        if pA < 1:
            x, y = (ox + cw) * pA, (oy + ch) * pA
            im.paste(cf.resize((int(W + (cw - W) * pA - g * pA), int(H + (ch - H) * pA - g * pA)), Image.BILINEAR),
                     (int(x + g / 2 * pA), int(y + g / 2 * pA)))
        else:
            put(cf, ox + cw, oy + ch, None)
            x, y = ox + cw + g / 2, oy + ch + g / 2
            ImageDraw.Draw(im).rounded_rectangle((x - 3, y - 3, x + cw - g + 3, y + ch - g + 3), radius=14,
                                                 outline=with_alpha(ACCENT, 1), width=4)
        im.alpha_composite(LB)
        L = layer(); d = ImageDraw.Draw(L)
        a0 = 1 - ramp(t, 0.6, 1.0)
        if a0 > 0:
            L.alpha_composite(Image.blend(layer(), bottom_gradient(), a0))
            if self.tag: pill(d, 72, 60, self.tag, ACCENT, a0)
            text(d, (96, 930), self.cap_start, font("InterDisplay-Bold", 56), FG, a0)
        a1 = ease_out(ramp(t, 5.2, 5.8))
        if a1 > 0:
            L.alpha_composite(Image.blend(layer(), bottom_gradient(360, 0.95), a1))
            text(d, (W / 2, H - 112), self.cap_end, font("InterDisplay-Bold", 48), FG, a1, anchor="ma")
            if self.cap_sub: text(d, (W / 2, H - 50), self.cap_sub, font("Inter-Medium", 24), MUTED, a1, anchor="ma")
        im.alpha_composite(L)
        return im

class Converge(Seg):
    """Hundreds of circular thumbnails orbit in labelled clusters, then fly (quadratic bezier through a
    horizontal band) into a dot-matrix rendering of `word`.  thumbs: dir of PNGs from thumbs.py with
    labels.json {record_id: group}.  Extra particles dissolve; missing ones are duplicated."""
    def __init__(self, thumbs, word, groups, head=("", ""), foot="", dur=7.0, cell=20, dot=17, t_go=2.0, t_land=4.6):
        self.thumbs, self.word, self.groups, self.head, self.foot = thumbs, word, groups, head, foot
        self.dur, self.CELL, self.DOT, self.T_GO, self.T_LAND = dur, cell, dot, t_go, t_land
    def targets(self):
        ss = 12
        f = font("InterDisplay-Bold", 17 * ss)
        bw = int(f.getlength(self.word)) + 4 * ss
        m = Image.new("L", (bw, 25 * ss), 0)
        ImageDraw.Draw(m).text((2 * ss, 2 * ss), self.word, font=f, fill=255)
        g = np.asarray(m.resize((bw // ss, m.height // ss), Image.BOX)) / 255.0
        pts = [(c, r) for r in range(g.shape[0]) for c in range(g.shape[1]) if g[r, c] > 0.42]
        on = set(pts)
        pts = [(c, r) for c, r in pts if sum((c + a, r + b) in on for a in (-1, 0, 1) for b in (-1, 0, 1)) - 1 >= 2]
        cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2; cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
        return [(W / 2 + (c - cx) * self.CELL, H / 2 + 10 + (r - cy) * self.CELL) for c, r in pts]
    def setup(self):
        rng = np.random.default_rng(3)
        labels = json.load(open(os.path.join(self.thumbs, "labels.json")))
        files = sorted(f for f in os.listdir(self.thumbs) if f.endswith(".png"))
        groups = {g: [] for g in self.groups}
        for fn in files:
            lab = labels.get(fn.rsplit("_", 1)[0])
            if lab in groups: groups[lab].append(fn)
        def sprite(fn):
            im = Image.open(os.path.join(self.thumbs, fn)).convert("RGB").resize((4 * self.DOT,) * 2, Image.LANCZOS)
            mk = Image.new("L", im.size, 0); ImageDraw.Draw(mk).ellipse((2, 2, im.size[0] - 2, im.size[1] - 2), fill=255)
            sp = im.convert("RGBA"); sp.putalpha(mk)
            ImageDraw.Draw(sp).ellipse((2, 2, im.size[0] - 2, im.size[1] - 2), outline=(255, 255, 255, 150), width=4)
            return sp.resize((self.DOT, self.DOT), Image.LANCZOS)
        n = len(self.groups); top = (n + 1) // 2
        cpos = [(W * (i + 0.5) / top, 420) for i in range(top)] + \
               [(W / 2 + (i - (n - top - 1) / 2) * 480, 760) for i in range(n - top)]
        self.parts, self.labels = [], []
        for gi, gname in enumerate(self.groups):
            cx, cy = cpos[gi]
            for k, fn in enumerate(groups[gname]):
                self.parts.append(dict(sp=sprite(fn), g=gi, c=(cx, cy), r=12.5 * math.sqrt(k + 0.5), ang=k * 2.39996))
            self.labels.append((gname, cx, cy + 12.5 * math.sqrt(len(groups[gname])) + 34))
        tg = sorted(self.targets(), key=lambda p: p[0] + rng.normal(0, 30))
        idx = sorted(range(len(self.parts)), key=lambda i: self.parts[i]["c"][0] + rng.normal(0, 60))
        for n_, i in enumerate(idx):
            p = self.parts[i]
            p.update(tg=tg[n_] if n_ < len(tg) else None, delay=rng.uniform(0, 0.75), band=540 + rng.normal(0, 70),
                     pop=rng.uniform(0, 0.5))
        for extra in tg[len(idx):]:
            q = dict(self.parts[int(rng.integers(len(self.parts)))])
            q.update(tg=extra, delay=rng.uniform(0, 0.75), band=540 + rng.normal(0, 70), pop=1.6)
            self.parts.append(q)
    def frame(self, t):
        im = Image.new("RGBA", (W, H), (4, 5, 9, 255)); L = layer(); d = ImageDraw.Draw(L)
        for p in self.parts:
            cx, cy = p["c"]; a = p["ang"] + 0.12 * t * (1 if p["g"] % 2 else -1)
            sx, sy = cx + p["r"] * math.cos(a), cy + p["r"] * math.sin(a)
            appear = ease_out(ramp(t, p["pop"], p["pop"] + 0.4))
            if appear <= 0: continue
            u = ease_io(ramp(t, self.T_GO + p["delay"], self.T_LAND - 0.75 + p["delay"]))
            if p["tg"] is None:
                x, y = sx + (sx - W / 2) * 0.4 * u, sy + (p["band"] - sy) * u; alpha = appear * (1 - u)
            else:
                tx, ty = p["tg"]; mx, my = (sx + tx) / 2, p["band"]
                x = (1 - u) ** 2 * sx + 2 * (1 - u) * u * mx + u ** 2 * tx
                y = (1 - u) ** 2 * sy + 2 * (1 - u) * u * my + u ** 2 * ty; alpha = appear
            if alpha <= 0.02: continue
            sp = p["sp"]
            if alpha < 1:
                sp = sp.copy(); sp.putalpha(Image.eval(sp.getchannel("A"), lambda v, a_=alpha: int(v * a_)))
            L.alpha_composite(sp, (int(round(x - self.DOT / 2)), int(round(y - self.DOT / 2))))
        la = ease_out(ramp(t, 0.3, 0.8)) * (1 - ramp(t, self.T_GO, self.T_GO + 0.4))
        for name, x, y in self.labels:
            text(d, (x, y), name, font("Inter-Bold", 17), MUTED, la, anchor="ma")
        h1 = ease_out(ramp(t, 0.0, 0.5)); h2 = ease_out(ramp(t, self.T_LAND, self.T_LAND + 0.5))
        fh = font("InterDisplay-Bold", 56)
        text(d, (96, 104), self.head[0], fh, FG, h1)
        text(d, (96 + tw(self.head[0] + " ", fh), 104), self.head[1], fh, ACCENT, h2)
        if self.foot:
            text(d, (W / 2, 760), self.foot, font("Inter-Medium", 32), MUTED,
                 ease_out(ramp(t, self.T_LAND + 0.4, self.T_LAND + 1.0)), anchor="ma")
        im.alpha_composite(L)
        return fade_black(im, 1 - ramp(t, self.dur - 0.25, self.dur))

class Outro(Seg):
    """Phase 1: '<X> is open source.' + item cards.  Phase 2: 'Try it yourself.' + URL typed in a pill + invite.
    items: [(title, one-line description)] — get the real list from the user, never invent what is released."""
    def __init__(self, headline, subline, items, cta, url, invite, bg=None, bg_t=0.0, logo=None, brand="", dur=10.0):
        self.headline, self.subline, self.items, self.cta, self.url, self.invite = headline, subline, items, cta, url, invite
        self.bg, self.bg_t, self.logo_p, self.brand, self.dur = bg, bg_t, logo, brand, dur
    def setup(self):
        self.r = Reader(self.bg, self.bg_t, size=(W // 4, H // 4), dur=self.dur) if self.bg else None
        self.logo = Image.open(self.logo_p).convert("RGBA") if self.logo_p else None
    def _logo(self, L, size, xy, a):
        if not self.logo: return
        lg = self.logo.resize((size, size)); lg.putalpha(Image.eval(lg.getchannel("A"), lambda x: int(x * a)))
        L.alpha_composite(lg, (int(xy[0]), int(xy[1])))
    def frame(self, t):
        if self.r:
            v = self.r.read().filter(ImageFilter.GaussianBlur(8)).resize((W, H), Image.BILINEAR)
            im = Image.blend(v, Image.new("RGB", (W, H), BG), 0.78).convert("RGBA")
        else:
            im = Image.new("RGBA", (W, H), BG + (255,))
        L = layer(); d = ImageDraw.Draw(L)
        fade = 1 - ramp(t, self.dur - 0.8, self.dur); split = self.dur * 0.54
        p1 = (1 - ramp(t, split - 0.2, split + 0.2)) * fade
        e2 = ease_out(ramp(t, 0.2, 0.8))
        text(d, (W / 2, 280 + 20 * (1 - e2)), self.headline, font("InterDisplay-ExtraBold", 104), FG, e2 * p1, anchor="ma")
        text(d, (W / 2, 420 + 10 * (1 - e2)), self.subline, font("Inter-Regular", 32), MUTED, e2 * p1, anchor="ma")
        n = len(self.items); cw_, chh, gap = min(380, (W - 192 - 28 * (n - 1)) / max(n, 1)), 210, 28
        x0 = (W - n * cw_ - (n - 1) * gap) / 2
        for i, (h_, s_) in enumerate(self.items):
            ei = ease_out(ramp(t, 1.0 + 0.25 * i, 1.6 + 0.25 * i)) * p1
            if ei <= 0: continue
            x = x0 + i * (cw_ + gap); y = 560 + 30 * (1 - ei)
            d.rounded_rectangle((x, y, x + cw_, y + chh), radius=18, fill=(255, 255, 255, int(16 * ei)),
                                outline=(255, 255, 255, int(60 * ei)), width=2)
            d.ellipse((x + 30, y + 34, x + 46, y + 50), fill=with_alpha(ACCENT, ei))
            text(d, (x + 30, y + 78), h_, font("InterDisplay-Bold", 38), FG, ei)
            for li, ln in enumerate(wrap(s_, font("Inter-Regular", 24), cw_ - 60)):
                text(d, (x + 30, y + 134 + li * 32), ln, font("Inter-Regular", 24), MUTED, ei)
        q = ease_out(ramp(t, split + 0.2, split + 0.8)) * fade
        if q > 0:
            if self.brand:
                fb = font("InterDisplay-Bold", 48); bw = tw(self.brand, fb) + (80 if self.logo else 0)
                self._logo(L, 64, (W / 2 - bw / 2, 250), q)
                text(d, (W / 2 - bw / 2 + (80 if self.logo else 0), 282), self.brand, fb, FG, q, anchor="lm")
            text(d, (W / 2, 390 + 20 * (1 - q)), self.cta, font("InterDisplay-ExtraBold", 120), FG, q, anchor="ma")
            fm = font("JetBrainsMono-Medium", 40)
            nch = int(len(self.url) * ease_io(ramp(t, split + 0.9, split + 2.4)))
            bw = fm.getlength(self.url) + 150; bx0, by0 = W / 2 - bw / 2, 600
            d.rounded_rectangle((bx0, by0, bx0 + bw, by0 + 92), radius=46, fill=BG + (int(235 * q),),
                                outline=with_alpha(ACCENT, q), width=3)
            d.text((bx0 + 60, by0 + 46), self.url[:nch], font=fm, fill=with_alpha(FG, q), anchor="lm")
            if t < split + 2.8:
                caret(d, bx0 + 60 + fm.getlength(self.url[:nch]), by0 + 24, 44, t, ACCENT, q)
            text(d, (W / 2, 760), self.invite, font("Inter-Medium", 36), ACCENT,
                 ease_out(ramp(t, split + 2.5, split + 3.1)) * fade, anchor="ma")
        im.alpha_composite(L)
        return fade_black(im, fade)

class BrowserScene(Seg):
    """Screen-recording style website transition.

    rec_dir: output of record_site.py (f_####.jpg captured at 2x + timeline.json with cursor/clicks).
    Draws a dark Chrome-like window: the URL is typed into the omnibox with a suggestion row, Enter, then
    the real page frames play under a drawn arrow cursor.  A virtual camera (cam keyframes on the 2x
    canvas: (t, cx, cy, zoom)) pushes in on whatever is being typed.  At t_dip the page dips to black and
    `next_video` blooms in from the dark — dip-then-bloom reads cleaner than a cross-dissolve, which
    double-exposes UI over footage.
    """
    SC = 2
    WL, WT, CH = 1600, 900, 84
    OX, OY = 320, 180
    def __init__(self, rec_dir, url, tab_title, cam, dur=9.0, t_type=(0.45, 1.65), t_enter=1.8,
                 t_dip=None, next_video=None, next_t=0.0, favicon=None, new_tab="New Tab",
                 placeholder="Search Google or type a URL"):
        self.rec, self.url, self.title, self.CAM, self.dur = rec_dir, url, tab_title, cam, dur
        self.T_TYPE0, self.T_TYPE1, self.T_ENTER = t_type[0], t_type[1], t_enter
        self.t_dip = t_dip if t_dip is not None else dur - 1.45
        self.next_video, self.next_t, self.fav, self.new_tab, self.placeholder = next_video, next_t, favicon, new_tab, placeholder
    def setup(self):
        self.tl = json.load(open(os.path.join(self.rec, "timeline.json")))
        self.fidx = sorted(int(k) for k in self.tl["frames"])
        self.favicon = Image.open(self.fav).convert("RGBA") if self.fav else None
        self.r = Reader(self.next_video, self.next_t, dur=self.dur - self.t_dip + 0.5) if self.next_video else None
        self._shot = {}
    def P(self, x, y): return (x * self.SC, y * self.SC)
    def R(self, x0, y0, x1, y1): return (x0 * self.SC, y0 * self.SC, x1 * self.SC, y1 * self.SC)
    def F(self, name, size): return font(name, size * self.SC)
    def shot(self, fi):
        fi = min(max(fi, self.fidx[0]), self.fidx[-1])
        if fi not in self._shot:
            self._shot = {fi: Image.open(os.path.join(self.rec, f"f_{fi:04d}.jpg")).convert("RGB")}
        return self._shot[fi]
    def omnibox_text(self, d, s, x, fu, t, focus):
        d.text(self.P(x, 62), s, font=fu, fill=(232, 234, 237), anchor="lm")
        if focus and int(t * 2.2) % 2 == 0:
            cx = x + fu.getlength(s) / self.SC + 1
            d.rectangle(self.R(cx, 53, cx + 1.2, 71), fill=(232, 234, 237))
    def window(self, t):
        sc = self.SC
        win = Image.new("RGBA", (self.WL * sc, self.WT * sc), (32, 33, 36, 255)); d = ImageDraw.Draw(win)
        loaded = t >= self.T_ENTER + 0.1; ic = (170, 172, 176)
        for i in range(3):
            d.ellipse(self.R(16 + i * 20, 15, 28 + i * 20, 27), fill=(95, 97, 102))
        d.rounded_rectangle(self.R(84, 7, 330, 48), radius=10 * sc, fill=(53, 54, 58))
        if loaded and self.favicon:
            win.alpha_composite(self.favicon.resize((16 * sc, 16 * sc), Image.LANCZOS), self.P(98, 18))
        else:
            d.ellipse(self.R(99, 19, 113, 33), outline=ic, width=2 * sc)
        text(d, self.P(122, 26), self.title if loaded else self.new_tab, self.F("Inter-Medium", 13), (226, 227, 230), 1, anchor="lm")
        text(d, self.P(312, 26), "×", self.F("Inter-Regular", 16), ic, 1, anchor="mm")
        text(d, self.P(350, 26), "+", self.F("Inter-Regular", 20), ic, 1, anchor="mm")
        d.rectangle(self.R(0, 40, self.WL, self.CH), fill=(53, 54, 58))
        text(d, self.P(24, 62), "←", self.F("Inter-Regular", 18), ic, 1, anchor="mm")
        text(d, self.P(56, 62), "→", self.F("Inter-Regular", 18), (110, 112, 116), 1, anchor="mm")
        d.arc(self.R(81, 55, 95, 69), 300, 240, fill=ic, width=2 * sc)
        focus = self.T_TYPE0 - 0.15 <= t < self.T_ENTER + 0.1
        d.rounded_rectangle(self.R(116, 48, 1500, 76), radius=14 * sc, fill=(32, 33, 36),
                            outline=(200, 202, 206) if focus else None, width=2 * sc)
        fu = self.F("Inter-Regular", 15)
        if loaded:
            dom, _, path = self.url.partition("/")
            d.text(self.P(140, 62), dom, font=fu, fill=(232, 234, 237), anchor="lm")
            if path:
                d.text(self.P(140 + fu.getlength(dom) / sc, 62), "/" + path, font=fu, fill=(154, 160, 166), anchor="lm")
            d_ = int(round(t * FPS)); win.paste(self.shot(d_), (0, self.CH * sc))
        else:
            n = int(len(self.url) * ramp(t, self.T_TYPE0, self.T_TYPE1)); s = self.url[:n]
            if n >= 3:   # suggestion dropdown under the omnibox
                d.rounded_rectangle(self.R(116, 48, 1500, 120), radius=14 * sc, fill=(41, 42, 45), outline=(200, 202, 206), width=2 * sc)
                d.rounded_rectangle(self.R(116, 48, 1500, 76), radius=14 * sc, fill=(32, 33, 36), outline=(200, 202, 206), width=2 * sc)
                if t >= self.T_ENTER - 0.05:
                    d.rectangle(self.R(118, 78, 1498, 116), fill=(60, 61, 65))
                d.ellipse(self.R(138, 90, 152, 104), outline=ic, width=2 * sc)
                fb = self.F("Inter-SemiBold", 15)
                d.text(self.P(166, 97), s, font=fb, fill=(232, 234, 237), anchor="lm")
                d.text(self.P(166 + fb.getlength(s) / sc, 97), self.url[n:], font=fu, fill=(232, 234, 237), anchor="lm")
            if s:
                self.omnibox_text(d, s, 140, fu, t, focus)
            else:
                text(d, self.P(140, 62), self.placeholder, fu, (154, 160, 166), 1, anchor="lm")
                self.omnibox_text(d, "", 140, fu, t, focus)
        d.ellipse(self.R(1556, 50, 1580, 74), fill=(95, 97, 102))
        fr = self.tl["frames"].get(str(int(round(t * FPS))))
        if fr is None and t > self.tl["t_end"]:
            fr = self.tl["frames"][str(self.fidx[-1])]
        if loaded and fr and fr["cursor"]:
            x, y = fr["cursor"]; y += self.CH
            press = any(0 <= t - c < 0.14 for c in self.tl["clicks"]) or fr["down"]
            k = 0.88 if press else 1.0
            pts = [(0, 0), (0, 17), (4.2, 13.2), (7, 19.5), (9.6, 18.4), (6.9, 12.3), (12.3, 12.3)]
            poly = [((x + px * k * 1.25) * sc, (y + py * k * 1.25) * sc) for px, py in pts]
            sh = Image.new("RGBA", win.size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).polygon([(a + 3, b + 4) for a, b in poly], fill=(0, 0, 0, 110))
            win.alpha_composite(sh.filter(ImageFilter.GaussianBlur(4)))
            d.polygon(poly, fill=(255, 255, 255), outline=(0, 0, 0), width=2)
        m = Image.new("L", win.size, 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, win.size[0], win.size[1]), radius=12 * sc, fill=255)
        win.putalpha(m)
        return win
    def frame(self, t):
        cv = Image.new("RGBA", (W * 2, H * 2), BG + (255,)); win = self.window(t)
        sh = Image.new("RGBA", cv.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((self.OX, self.OY + 30, self.OX + win.size[0], self.OY + win.size[1] + 30),
                                             radius=24, fill=(0, 0, 0, 170))
        cv.alpha_composite(sh.filter(ImageFilter.GaussianBlur(40))); cv.alpha_composite(win, (self.OX, self.OY))
        cx, cy, z = keyframes(self.CAM, t, log_last=True)
        cw, chh = W * 2 / z, H * 2 / z
        cx = min(max(cx, cw / 2), W * 2 - cw / 2); cy = min(max(cy, chh / 2), H * 2 - chh / 2)
        im = cv.crop((int(cx - cw / 2), int(cy - chh / 2), int(cx + cw / 2), int(cy + chh / 2))).resize((W, H), Image.LANCZOS)
        fi = ease_out(ramp(t, 0.0, 0.35))
        if fi < 1: im = Image.blend(Image.new("RGBA", (W, H), BG + (255,)), im, fi)
        dark = ease_io(ramp(t, self.t_dip, self.t_dip + 0.3))
        if dark > 0:
            im = Image.blend(im.convert("RGB"), Image.new("RGB", (W, H), BG), dark).convert("RGBA")
        va = ease_out(ramp(t, self.t_dip + 0.3, self.t_dip + 0.9))
        if va > 0 and self.r:
            s = 0.94 + 0.06 * ease_out(ramp(t, self.t_dip + 0.3, self.dur))
            vv = self.r.read().resize((int(W * s), int(H * s)), Image.BILINEAR).convert("RGBA"); vv.putalpha(int(255 * va))
            im = im.convert("RGBA"); im.alpha_composite(vv, ((W - vv.size[0]) // 2, (H - vv.size[1]) // 2))
        return im

# ================================================================ build driver
_STATE = {}

def _render(name):
    seg = dict(_STATE["segments"])[name]()
    seg.setup()
    out = os.path.join(_STATE["workdir"], f"{name}.mp4")
    w = Writer(out)
    n = int(round(seg.dur * FPS))
    for i in range(n):
        w.write(seg.frame(i / FPS))
    w.close(); seg.close()
    return name, n / FPS

def concat(segments, workdir, out, bgm=None):
    lst = os.path.join(workdir, "list.txt")
    with open(lst, "w") as f:
        for name, _ in segments:
            f.write(f"file '{os.path.abspath(os.path.join(workdir, name + '.mp4'))}'\n")
    cmd = [FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst]
    if bgm:
        cmd += ["-i", bgm, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    else:
        cmd += ["-c:v", "copy"]
    subprocess.run(cmd + ["-movflags", "+faststart", out], check=True)
    print("wrote", out, f"{probe_duration(out):.2f}s")

def schedule(segments):
    """start time of every segment — use it to key music hits to cuts (bgm.py --hits)."""
    t, rows = 0.0, []
    for name, mk in segments:
        d = mk().dur; rows.append((name, round(t, 3), round(d, 3))); t += d
    return rows, t

def main(segments, out, bgm=None, workdir="segs", procs=12, argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.makedirs(workdir, exist_ok=True)
    _STATE.update(segments=segments, workdir=workdir)
    cmd = argv[0] if argv else "all"
    if cmd == "list":
        rows, total = schedule(segments)
        for n, t0, d in rows: print(f"{t0:8.2f}  {d:6.2f}  {n}")
        print(f"total {total:.2f}s"); return
    if cmd in ("all", "seg"):
        from multiprocessing import Pool
        names = [n for n, _ in segments] if cmd == "all" else argv[1:]
        with Pool(max(1, min(procs, len(names)))) as p:
            for r in p.imap_unordered(_render, names):
                print("done", r, flush=True)
        if cmd == "all":
            concat(segments, workdir, out, bgm)
    elif cmd == "concat":
        concat(segments, workdir, out, bgm)
    else:
        raise SystemExit(__doc__)
