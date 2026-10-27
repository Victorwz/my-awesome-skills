"""Procedural light/upbeat BGM keyed to the video timeline (no samples -> no licensing questions).

120 BPM, D major, I-V-vi-IV: pad + 16th arpeggio plucks + kick/clap/hat/shaker + pumping offbeat bass +
a bell motif that breathes (8 bars on / 8 off), shimmer in 'lift', risers into and impacts on every hit.

  python bgm.py out.wav --dur 141.4 \
      --sections intro:0,montage:4,web:8,main:19,lift:114.4,outro:131.4 \
      --hits 19,100.2,114.4,131.4 [--web-drums-from 15] [--seed 7]

Section kinds (any order, each starts at its time and runs to the next):
  intro   pad + sparse plucks, no drums          montage  everything but melody, drums in
  web     filtered (dark) plucks, kick only until --web-drums-from, then full drums
  main    full groove, melody on/off             lift     full groove + high shimmer
  outro   drums drop out 4 s before the end, pad + plucks, fade
Get hit times from `python build.py list` (segment starts) so swells land on cuts.
This is a placeholder-quality track: always tell the user to listen and offer to swap in a licensed one.
"""
import argparse, numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

ap = argparse.ArgumentParser()
ap.add_argument("out"); ap.add_argument("--dur", type=float, required=True)
ap.add_argument("--sections", default="intro:0,main:4,outro:-10")
ap.add_argument("--hits", default="")
ap.add_argument("--web-drums-from", type=float, default=None)
ap.add_argument("--bpm", type=float, default=120.0)
ap.add_argument("--seed", type=int, default=7)
A = ap.parse_args()

SR = 44100; BEAT = 60.0 / A.bpm; BAR = 4 * BEAT; DUR = A.dur
N = int(DUR * SR) + SR
L = np.zeros(N); R = np.zeros(N)
rng = np.random.default_rng(A.seed)
SECS = []
for tok in A.sections.split(","):
    k, v = tok.split(":"); v = float(v); SECS.append((v if v >= 0 else DUR + v, k))
SECS.sort()
HITS = [float(x) for x in A.hits.split(",") if x.strip()]

def section(t):
    cur = SECS[0][1]
    for t0, k in SECS:
        if t >= t0: cur = k
    return cur

def sec_range(kind):
    out = []
    for i, (t0, k) in enumerate(SECS):
        if k == kind: out.append((t0, SECS[i + 1][0] if i + 1 < len(SECS) else DUR))
    return out

def midi(n): return 440.0 * 2 ** ((n - 69) / 12)

def add(sig, t0, gain=1.0, pan=0.0):
    i = int(t0 * SR)
    if i >= N or i < 0: return
    sig = sig[: N - i]
    l = np.cos((pan + 1) * np.pi / 4); r = np.sin((pan + 1) * np.pi / 4)
    L[i:i + len(sig)] += sig * gain * l * 1.414
    R[i:i + len(sig)] += sig * gain * r * 1.414

def env_adsr(n, a, d, s, rel, length):
    t = np.arange(n) / SR
    e = np.where(t < a, t / max(a, 1e-4), s + (1 - s) * np.exp(-(t - a) / max(d, 1e-4)))
    return np.where(t > length, e * np.exp(-(t - length) / max(rel, 1e-4)), e)

def lp(x, fc, order=2): return sosfilt(butter(order, min(fc, SR / 2 - 100) / (SR / 2), btype="low", output="sos"), x)
def hp(x, fc, order=2): return sosfilt(butter(order, fc / (SR / 2), btype="high", output="sos"), x)

PROG = [[62, 66, 69, 74], [61, 64, 69, 73], [59, 62, 66, 71], [59, 62, 67, 71]]   # D A/C# Bm G/B
BASS = [38, 33, 35, 31]
def chord_at(t): return int(t // BAR) % 4

def pad_note(f, dur):
    n = int((dur + 0.6) * SR); t = np.arange(n) / SR; s = np.zeros(n)
    for det in (-0.12, 0.0, 0.11):
        s += 2 * ((t * f * 2 ** (det / 12) + rng.random()) % 1.0) - 1
    return lp(s / 3, 1800) * env_adsr(n, 0.35, 0.8, 0.8, 0.5, dur)

def pluck(f, dur=0.35, bright=4500):
    n = int(dur * SR); t = np.arange(n) / SR
    s = (2 * ((t * f) % 1.0) - 1) * 0.6 + np.sin(2 * np.pi * f * t) * 0.6 + 0.25 * np.sin(4 * np.pi * f * t)
    return lp(s, bright) * np.exp(-t * 11) * np.minimum(1, t / 0.003)

def bell(f, dur=0.9):
    n = int(dur * SR); t = np.arange(n) / SR
    mod = np.sin(2 * np.pi * f * 3.5 * t) * 1.2 * np.exp(-t * 6)
    return (np.sin(2 * np.pi * f * t + mod) + 0.3 * np.sin(2 * np.pi * f * 2 * t)) * np.exp(-t * 3.2) * np.minimum(1, t / 0.004)

def bass_note(f, dur):
    n = int(dur * SR); t = np.arange(n) / SR
    return lp(np.sin(2 * np.pi * f * t) + 0.35 * (2 * ((t * f) % 1.0) - 1), 700) * env_adsr(n, 0.005, 0.12, 0.6, 0.03, dur - 0.03)

def kick():
    n = int(0.35 * SR); t = np.arange(n) / SR
    ph = 2 * np.pi * np.cumsum(48 + 110 * np.exp(-t * 32)) / SR
    return np.sin(ph) * np.exp(-t * 9) + 0.15 * np.exp(-t * 200) * rng.standard_normal(n)

def clap():
    n = int(0.25 * SR); t = np.arange(n) / SR
    e = np.exp(-t * 22)
    for o in (0.0, 0.011, 0.022):
        e += 0.6 * np.exp(-np.clip(t - o, 0, None) * 120) * (t >= o)
    return hp(lp(rng.standard_normal(n), 6000), 900) * e * 0.5

def hat(open_=False):
    n = int((0.18 if open_ else 0.05) * SR); t = np.arange(n) / SR
    return hp(rng.standard_normal(n), 7000) * np.exp(-t * (14 if open_ else 70))

def shaker():
    n = int(0.08 * SR); t = np.arange(n) / SR
    return hp(rng.standard_normal(n), 5000) * np.sin(np.pi * t / t[-1]) ** 2

def riser(dur):
    n = int(dur * SR); t = np.arange(n) / SR; x = rng.standard_normal(n); out = np.zeros(n); seg = int(0.05 * SR)
    for i in range(0, n, seg):
        out[i:i + seg] = lp(x[max(0, i - 2048):i + seg], 400 + 9000 * (i / n) ** 2)[-len(out[i:i + seg]):]
    return out * (t / dur) ** 2

def impact():
    n = int(1.5 * SR); t = np.arange(n) / SR
    return lp(rng.standard_normal(n), 2500) * np.exp(-t * 3) * 0.6 + np.sin(2 * np.pi * 45 * t) * np.exp(-t * 4)

G_PAD = {"intro": 0.10, "montage": 0.07, "web": 0.08, "main": 0.06, "lift": 0.08, "outro": 0.09}
G_ARP = {"intro": 0.10, "montage": 0.11, "web": 0.08, "main": 0.10, "lift": 0.12, "outro": 0.10}
nbars = int(DUR / BAR) + 1
for b in range(nbars):
    t0 = b * BAR
    if t0 >= DUR: break
    for k, nn in enumerate(PROG[b % 4]):
        add(pad_note(midi(nn), BAR), t0, G_PAD.get(section(t0), 0.07), pan=-0.4 + 0.27 * k)

ARP = [0, 1, 2, 3, 2, 1, 2, 3, 0, 2, 1, 3, 2, 3, 1, 2]
for i in range(int(DUR / (BEAT / 4))):
    t0 = i * BEAT / 4; sec = section(t0)
    if sec == "intro" and i % 2: continue
    nn = PROG[chord_at(t0)][ARP[i % 16]] + 12
    add(pluck(midi(nn), bright=2500 if sec == "web" else 5000), t0,
        G_ARP.get(sec, 0.1) * (1.0 if i % 4 == 0 else 0.7), pan=0.35 if i % 2 else -0.35)

web_drums = A.web_drums_from if A.web_drums_from is not None else float("inf")
for i in range(int(DUR / (BEAT / 2))):
    t0 = i * BEAT / 2; sec = section(t0)
    if sec == "intro" or (sec == "outro" and t0 > DUR - 6): continue
    beat_i, off = i // 2, i % 2
    drums = sec in ("montage", "main", "lift") or (sec == "web" and t0 >= web_drums)
    if not off:
        if drums or sec == "web": add(kick(), t0, 0.55 if drums else 0.35)
        if drums and beat_i % 2 == 1: add(clap(), t0, 0.32, pan=0.05)
    elif drums:
        add(hat(open_=(beat_i % 4 == 3)), t0, 0.10, pan=0.25)
    if drums: add(shaker(), t0 + BEAT / 4, 0.05, pan=-0.3)
    if sec in ("montage", "main", "lift", "outro") and off:
        add(bass_note(midi(BASS[chord_at(t0)] + 12), BEAT / 2 * 0.95), t0, 0.22)

MOTIF = [(0, 3, 1), (1, 2, 0.5), (1.5, 3, 0.5), (2, 1, 1.5), (4, 3, 1), (5, 2, 0.5), (5.5, 1, 0.5), (6, 2, 2)]
for b in range(0, nbars, 2):
    t0 = b * BAR; sec = section(t0)
    if sec not in ("main", "lift", "montage"): continue
    if sec == "main" and (b // 8) % 2 == 1: continue          # breathe
    for bo, idx, ln in MOTIF:
        add(bell(midi(PROG[(b + (1 if bo >= 4 else 0)) % 4][idx] + 12), ln * BEAT + 0.6), t0 + bo * BEAT, 0.07, pan=0.1)

for a, b in sec_range("lift"):
    for i in range(int(a / (BEAT / 2)), int(b / (BEAT / 2))):
        t0 = i * BEAT / 2
        add(bell(midi(PROG[chord_at(t0)][(i * 3) % 4] + 24), 0.5), t0, 0.035, pan=-0.5 if i % 2 else 0.5)

for tt in HITS:
    add(riser(2.0), tt - 2.0, 0.10); add(impact(), tt, 0.18)
first_non_intro = next((t0 for t0, k in SECS if k != "intro"), None)
if first_non_intro: add(impact(), first_non_intro, 0.2)

t = np.arange(N) / SR
pump = 1 - 0.18 * np.exp(-(t % BEAT) * 12)
if first_non_intro: pump[t < first_non_intro] = 1
L *= pump; R *= pump
fade = np.ones(N)
fi = int(0.6 * SR); fade[:fi] = np.linspace(0, 1, fi)
fo0, fo1 = int((DUR - 4.0) * SR), int(DUR * SR)
fade[fo0:fo1] = np.linspace(1, 0, fo1 - fo0) ** 1.5; fade[fo1:] = 0
L *= fade; R *= fade
st = np.stack([L, R], 1)[: int(DUR * SR)]
st = hp(st.T, 30).T
st = np.tanh(st * 1.2) / np.tanh(1.2)
st = st / (np.abs(st).max() + 1e-9) * 0.89
wavfile.write(A.out, SR, (st * 32767).astype(np.int16))
print("wrote", A.out, f"{DUR:.2f}s", "sections", SECS, "hits", HITS)
