---
name: promo-video
description: Build a launch / promo / demo-reel video for an AI model or product from a folder of generated demo clips, entirely in code (Python + PIL compositing piped into ffmpeg). Covers the narrative arc (intro, slogan montage, typing into the real website, capability sections with title cards, control HUD overlays for text prompts and keyboard/camera input, long-generation fast-forward, multi-style wall, thumbnails converging into the product name, open-source outro and CTA), procedural BGM, footage QA (artifact frames, control logs that do not match the motion, burned-in text), bilingual builds and review sharing. Use this whenever the user wants a 宣传片 / 宣传视频 / promo / sizzle reel / launch trailer / demo video cut from model outputs, wants to redo or iterate on such a video (swap clips, change slogans, translate it, fix artifacts, re-time music), or mentions a reference promo like Genie 3 to imitate, even if they never say "skill" or name a tool.
---

# Promo video from generated demo clips

You are acting as editor, motion designer and QA for a short (≈1.5–2.5 min) promo that shows off what
a model can do. Everything is rendered by code: each segment is a Python class that draws one frame at a
time on top of decoded source frames. That is slower to start than a GUI editor, but every change the
user asks for ("change this word", "swap the third clip", "remove that tag", "make a Chinese version")
becomes a one-line edit and a re-render of one segment, and that loop is what these projects are made of.

Bundled resources (paths relative to this file):

| Path | Use it for |
|---|---|
| `scripts/promokit.py` | The renderer library: Reader/Writer, text/pill/HUD helpers, and segment classes `Card`, `Montage`, `DemoClip`, `SessionClip`, `FastForward`, `StartEnd`, `Wall`, `Converge`, `Outro`, `BrowserScene`, plus `main()` (parallel render, concat, music mux) and `erase_glyphs()` |
| `scripts/example_build.py` | Starting point for the project's `build.py`. `--selftest` renders every segment type against generated test footage |
| `scripts/record_site.py` | Playwright drives the real website frame by frame (typing, clicks, select, pressed button) for `BrowserScene` |
| `scripts/bgm.py` | Procedural upbeat BGM whose sections and swells are keyed to segment start times |
| `scripts/motion.py` | Optical-flow camera motion per 0.5 s, to check control logs against the actual video |
| `scripts/frame_pops.py` | Finds single-frame artifacts and periodic chunk seams, and makes contact sheets |
| `scripts/clean_frames.py` | Drops bad frames, softens a window, builds a blended N× fast-forward |
| `scripts/thumbs.py` | Thumbnail sprites for `Converge` |
| `scripts/serve.py` | Range-capable HTTP server so reviewers can open a link and scrub the cut |
| `references/segment-recipes.md` | How each segment type works, its timings and pitfalls. Read it before building or changing a section |
| `references/footage-qa.md` | Source-quality audit, verifying controls, artifact repair. Read it before choosing clips |
| `references/localization.md` | Second-language builds. Read it when a translated cut is requested |
| `references/environment.md` | No system ffmpeg, headless Chromium missing libs, fonts, scratch-dir hygiene |

## Workflow

### 1. Brief and reference
Read the brief file and every note the user points at. If they cite a reference promo (for example the
Genie 3 trailer), follow its structure and pacing. If you cannot fetch the reference (YouTube often
blocks downloads), say so and ask for a local clip or a timestamped description rather than guessing.
Sections of the reference the user calls out by timestamp are the ones they want imitated closely.

### 2. Inventory the footage before designing anything
Build a table of every candidate clip: id, path of **every quality variant** (for example a high-res
decoder output vs a preview decode, and with/without baked-in overlays), duration, per-turn prompts and
control type with timestamps, perspective/style tags, and any reviewer notes in the metadata ("not good",
"copyright", "no motion"). Then:
- Always use the highest-quality variant, and the version *without* baked-in overlays, because you draw
  your own HUD. Report any clip that has no high-quality variant instead of silently using a lower one.
  One user insisted on this repeatedly ("一定要用这个，这个高清").
- Exclude clips with IP, likeness or copyright risk (recognisable franchises, celebrities, branded games)
  and clips the metadata marks as bad. List what you excluded and why.
- Record which control actually drives each stretch of each clip, from the logs and not from your memory
  of the brief. A segment labelled "camera control" that was really a text turn is the kind of error users
  catch and lose trust over ("是不是你自己硬加上去的").

### 3. Outline: capabilities → slogans → clips
Turn each capability the user wants to stress into a section: a short label, a punchy slogan, and 2–3
clips that show it unambiguously. Typical arc (adapt it, don't force it):

1. Intro / title (reuse the good seconds of an earlier draft if the user liked them)
2. Montage: 3–4 one-second shots, one short imperative phrase each, one per capability
3. Website transition: type the real demo URL, fill the real form, then bloom into the first demo
4. One section per capability: `Card`, then `DemoClip`/`SessionClip`s with HUD
5. Long-horizon generation: hero clip fast-forwarded with a running clock, then start-vs-end tiles
6. Diversity: one video spreads into a 3×3 then 5×5 wall of styles/subjects (placed late)
7. Brand beat: hundreds of thumbnails cluster by category and converge into the product name
8. Outro: what is open-sourced (get the real list from the user) + "Try it" + URL + invite

Give the outline with timings, then start building. Don't block on details. Use clearly marked
placeholders for facts only the user knows (release contents, URL, final wording) and list them in your
report. Never present invented release contents as fact.

### 4. Build
Copy `scripts/example_build.py` into the project folder as `build.py`, import promokit from this skill's
`scripts/` dir (or copy it in), and define `SEGMENTS`. Keep every user-visible string in the `SEGMENTS`
list or one table, because wording changes are the most frequent request. Keep build scripts, cleaned
clips, recordings and music in the **project** folder: scratch dirs get wiped, and the user will later ask
"where is the version with the English overlay?"

`python build.py list` prints segment start times. `seg <names>` re-renders only what changed and
`concat` re-muxes. A full render of a ~2 min cut takes about a minute on 12 cores.

### 5. QA before showing anything
For every segment, pull a contact sheet (ffmpeg `select`+`tile`) and look at it, and read
`references/footage-qa.md` for the checks. The ones that bit hardest in past projects:
- HUD keys / prompts do not match what happens on screen (mirrored key logs, wrong timestamps, prompt
  says "flip the cup" but the video sets it aside). Fix the overlay or the prompt text to match the
  video. Never leave a mismatch.
- Single-frame artifacts (ghosting, smears). Find them with `frame_pops.py`, drop 1–2 frames and soften
  the window with `clean_frames.py`, and use the blended fast-forward for long clips.
- Burned-in text from reused footage. Use `erase_glyphs()` and check it over **every** backdrop that
  passes behind it.
- HUD flicker at cuts between consecutive turns of one session (`fade=False` on continuing clips).
- Text legibility on bright frames (scrim + translucent pill fill).

### 6. Music
Generate with `bgm.py`, using `--sections`/`--hits` from `build.py list` so risers land on section cuts.
You cannot listen to it: say so, and offer to drop in a licensed track (replace the wav, run `concat`).

### 7. Deliver and share
Write the final mp4 into the project folder, start `serve.py` if the user wants a link for others, and
report: path, duration, link, a section/time table, what you could not verify (audio, a clip's quality
variant), placeholders still open, and anything you excluded.

### 8. Iterate
Expect many small rounds. For each request:
- Restate exactly which clip/turn/word you will change, quoting its current text, when there is any
  ambiguity. "Delete the second segment" has more than one reading: it could be the 2nd text turn or the
  2nd global turn. A wrong guess costs a full round trip.
- Change only what was asked. If the user said "leave the other capitalization for now", leave it.
- Back up `build.py` before larger edits (`build_vN_backup.py`) so a rejected direction can be reverted.
- If there are several language builds, apply the change to all of them, or say explicitly which ones
  you did not update.
- When a deliverable is a standalone clip (a segment without music, a variant without the tag, a still
  frame), copy it into the project folder and give the absolute path.

## Taste: what users of past promos asked for
These came from direct feedback. Treat them as defaults and let the user override them.

- **Monochrome UI.** No blue/orange accent colours. Build hierarchy from size and weight only, with one
  text colour. (promokit's palette is already like this.)
- **Minimal title cards.** A small label and a big slogan. No "01/02/…" numbers, no ALL-CAPS labels on
  cards, and no long small-print sentence under the slogan.
- **Short imperative slogans** that name the actual input the viewer would use (a verb and the input, then a payoff).
  Users edit wording a lot, so make each word change a one-line edit.
- **The website transition must look real.** A drawn mock-up of the site was rejected as ugly ("丑爆炸了").
  What worked: a frame-by-frame capture of the live site in a realistic dark browser window, with the
  URL typed in the omnibox, a drawn cursor, and a virtual camera pushing in on whatever is being typed.
  Leave the transition into the footage as a dip to black then bloom, not a double-exposure dissolve.
  Never actually submit a form on a real site (hold the button down, don't release).
- **Pacing.** Speeding a session up is fine, but each turn must stay readable on screen for roughly 3–5 s,
  long enough to read the prompt and see the result. One-second flashes per turn were rejected.
- **Continuity over cutting.** If one turn of a continuous session is weak, fold its footage into the
  neighbouring turn and relabel the timeline instead of cutting it out. A cut inside one rollout reads as
  a jump. When a turn *is* removed, renumber the timeline (T2 T3 T4, not T2 T4 T5).
- **Long-video section.** The most impressive long clip goes big and fast-forwarded first, then the
  section splits into start/end comparisons.
- **Proper names stay untranslated** (model and product names). Everything else on screen gets
  translated, including the text typed into the simulated website.

## What not to put in the skill's outputs
This skill is generic. Product names, URLs, clip ids, slogans and release lists come from the user's
brief and footage for each project. Don't carry them over from a previous project.
