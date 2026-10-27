# Footage QA

Generated footage has failure modes that ordinary stock footage does not. Run these checks while
choosing clips, not after the user spots something.

## 1. Quality variant audit
For every clip used, record which file it came from. If a record has several decodes (an HD/super-res
decoder output, a preview decode, overlay vs pre-overlay), use the best one *without* baked-in UI. Some
records have only one file whose metadata names the HD decoder: that counts, so note it. List any clip
whose provenance you cannot confirm (for example an eval-output path) and ask. Don't assume.

## 2. Do the controls in the overlay match the picture?
The HUD claims "this key moved the camera" or "this prompt caused this". Viewers and the user check
that claim against the picture.
- Read the per-turn metadata: turn boundaries, prompt text, whether a turn had camera control. Don't
  invent a control type for a stretch that had none. If the user asks "was that really camera
  control?", answer from the record.
- Run `motion.py clip.mp4 --from t0 --to t1` over each camera turn and compare with the key intervals:
  W/S should show zoom +/−, A/D horizontal truck (`par`), ←/→ yaw (`dx`), ↑/↓ tilt (`dy`). In one
  batch the logs had W/S and ←/→ **mirrored** relative to the video on every case. The fix was a remap
  table in the build, applied to that batch only. Also look for presses that end before the visible
  motion stops, or start after it, and trim the interval to what is visible.
- Weak control response (the camera barely moves) is a reason to fold that turn into a neighbour or
  pick another case. Don't advertise it.
- Text turns: watch the window and check the prompt describes what happens. If the model didn't follow
  the prompt (for example "flip the cup upside down" but the cup is just moved aside), change the
  displayed prompt to what the video shows. Ask if the edit is substantive.

## 3. Single-frame artifacts
Symptoms: a pole goes semi-transparent for 2 frames, a trunk smears, a texture pops. Users notice these
at 1× in a hero clip.
1. `frame_pops.py clip.mp4 --from A --to B --sheet sheet.jpg` flags A-B-A spikes and writes a labelled
   grid. Then **look at the sheet**, since some flagged frames are just fast motion and a person walking
   out of frame is not an artifact.
2. `clean_frames.py clip.mp4 clip_clean.mp4 --drop f1,f2 --soften A:B`. Dropping 1–2 frames at 24 fps is
   invisible, and a 3-tap blend over the second hides what remains. Write to a new file and keep the
   original.
3. For fast-forward, build the blended N× file from the cleaned clip.
4. Report frame numbers and timestamps of what you removed, so the user can tell you if you hit the
   wrong spot.

## 4. Periodic chunk seams
Some generators produce a visible jump at a fixed interval (for example at every x.17 s).
`frame_pops.py --period` reports the gap and phase. Don't repair these. Place short shots (montage
1 s) between seams, and cut at a seam rather than across one.

## 5. Burned-in text in reused footage
`erase_glyphs(im, box)` masks only the pixels that deviate from the local median and inpaints them. The
first approach tried, repainting the whole box with a top-to-bottom gradient, looked fine over a blurred
dark shot and turned into a visible rectangle with vertical seams once a colourful scene passed behind
it. Check the erased region over every background in that segment's time range, with contrast boosted
(`eq=contrast=2`) if needed. If glyph strokes of *other* text touch the box, shrink the box or mask them.

## 6. Content risk
Skip clips showing recognisable IP (franchise characters, branded games, famous superheroes), real
people's likeness, or anything the metadata flags. This includes the tiny sprites in `Converge`, since
nobody will catch a 17 px dot in review. Tell the user what you skipped.

## 7. Final cut check
- Contact sheet of every segment at 3–4 time points; zoom crops on HUD text.
- ffprobe duration equals the sum of the segments (`build.py list`), with audio present and the same length.
- First and last frames are not black by accident, and nothing freezes because a source ended early.
- Text never overlaps text: pills vs prompts, translated strings vs neighbours.
