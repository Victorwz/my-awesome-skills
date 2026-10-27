# Segment recipes

All classes live in `scripts/promokit.py`. Canvas: 1920×1080 @ 24 fps. Segment times are seconds from the
segment start. Source times are seconds in the source clip.

## Contents
- Shared conventions
- Card (section title)
- Montage (opening phrases)
- DemoClip (one window with HUD)
- SessionClip (a whole multi-turn session, sped up)
- BrowserScene + record_site.py (typing into the real site)
- FastForward + StartEnd (long-horizon generation)
- Wall (one video spreads into many)
- Converge (thumbnails become the product name)
- Outro (open source + call to action)
- Reusing an old draft's intro
- Typical timing budget

## Shared conventions
- Draw text on a separate transparent `layer()` and `alpha_composite` it. Drawing translucent shapes
  straight onto an RGBA frame *replaces* pixels instead of blending them, which once made a whole set of
  tile labels vanish.
- Anything placed after a pill or a word must use the box/width returned by `pill()` or `tw()`, never a
  hard-coded x. Changing the font or translating the label otherwise causes overlaps.
- `bottom_gradient()` sits under every HUD. White text on raw generated footage fails on snow, sky and
  sand scenes.
- Fade in the overlay only on the first clip of a session (`fade=True`). Continuing clips use
  `fade=False`, or the HUD visibly blinks at every cut.
- Every `Reader` should be given `dur` so ffmpeg stops decoding early. Readers hold the last frame past
  the end of the source, so a too-short source freezes instead of crashing. Check the durations.

## Card
`Card(label, slogan, bg, bg_t, dur=2.0)`: blurred, darkened moving background, a small label with a
short rule, and a big slogan. 2.0–2.2 s is enough. Pick a background frame from the section's own
footage so the card previews it. Keep it to label + slogan. See the taste notes in SKILL.md.

## Montage
`Montage([(path, start, words), ...], per=1.0)`: one shot per phrase, phrase centred with a blurred
shadow, and the footage dimmed by `dim`. If a phrase is unreadable on a bright shot, raise `dim` or pick
another shot. Don't shrink the type. If the source has periodic chunk seams (see footage-qa.md), choose
`start` so the 1 s window sits between two seams.

## DemoClip
`DemoClip(path, src, dur, kind, prompt, turns, total, turn_idx, tag=, counter=, keys=, big_hud=, fade=)`

- `kind="TEXT"`: a filled TEXT pill, then the prompt typed over ~45% of the clip with a blinking caret.
  The prompt should describe what visibly happens in *this* window.
- `kind="CAM"`: either the inline "Keyboard control · ↑ ←" line plus a small key HUD, or `big_hud=True`
  for one large WASD/arrow HUD bottom-right. Use the big one for camera-only sections. Keys come from
  `keys=[{code,start,end}]` in **source** seconds. `pk.key_intervals()` converts press/release logs and
  can remap mirrored keys.
- `turns=[(kind, t0, t1)]` draws the session timeline (T1 · START, T2 · TEXT, T3 · CAMERA …) so viewers
  see where text and camera alternate. `tl_shift` keeps it right when source seconds were cut out.
- `tag=None` hides the top-left section pill and `counter=False` hides "Turn x of n". Users sometimes
  want clean variants of single clips for other uses.
- To present one turn of a mixed session as a pure-camera example, start the clip at that turn's start
  and give it a one-turn timeline.

## SessionClip
`SessionClip(path, src, speed, turns, total, prompts, keys=, type_first=True, cut=None)` plays a whole
session and switches the HUD (TEXT prompt or CAM keys) to whichever turn is live. Choose `speed` so each
turn lasts about 3–5 s on screen: `speed = longest_turn / 4` is a good start. If the clip is entered
mid-turn (for example right after the website bloom), `type_first=True` types the first prompt as the
clip opens.

To drop a weak turn, prefer *relabelling* `turns` so its footage belongs to the previous turn. Use `cut`
only when the user asks for a removal. Then also renumber, and confirm which turn by quoting its prompt.

## BrowserScene + record_site.py
1. Inspect the live page (Playwright `page.content()` or a screenshot) to find selectors for the input
   fields, dropdowns and the main button.
2. Write a config (see `record_site.py` docstring) whose times are on the **segment** clock: URL typed
   ≈0.45–1.65 s, Enter 1.8 s, page load from `t_nav`≈1.9, then field clicks and typing, the select, and
   finally `press` on the button (held, never released, so nothing is submitted).
3. `python record_site.py cfg.json rec_dir`, then `BrowserScene(rec_dir, url, tab_title, cam, next_video=...)`.
4. Camera keyframes `(t, cx, cy, zoom)` on the 3840×2160 canvas (the window spans x 320–3520,
   y 180–1980; the omnibox is near y≈300). Pattern: wide → push to the omnibox while typing → pull back
   on load → push to each field as it is typed → slight pull → push to the button. Zoom 1.8–2.4 on
   fields is readable. Interpolation is eased and zoom changes geometrically, so pushes feel even.
5. Ending: the page dips to black (`t_dip`, 0.3 s), then the first demo blooms in (scale 0.94→1). Start
   the next segment's source exactly where the bloom left it so the motion continues.
Keep the cursor parked off the text being typed (record_site does this). A cursor covering the typed
text was an explicit complaint. Typed site text must be translated in localized builds, so record once
per language.

## FastForward + StartEnd
Run `clean_frames.py src.mp4 x10.mp4 --ff 10` first. Taking every Nth frame turns every residual
artifact into a flash, while a 4-tap blend reads as motion blur. Then use
`FastForward(x10.mp4, speed=10, total=60, dur=6, pre_sped=True, tag=..., sub=...)`, which shows a big
"0:42 of 1:00 generated" clock and a tick bar. Follow it with
`StartEnd([(path, 0.5, 53.5), ...], title)` (1–2 rows), which plays START and END tiles side by side to
show the same character and world a minute apart. Use the single best long clip for FastForward and
add the second row only in StartEnd.

## Wall
`Wall(center, ring1[8], ring2[16], cap_start, cap_end, cap_sub)`: centre clip full screen (0.8–2.0 s
shrinks into a 3×3 grid), ring 1 flies out, then (3.6–4.8 s) the 3×3 shrinks into the middle of a 5×5 as
ring 2 arrives. Label tiles with style tags (REAL / ANIME / CG / GAME) from metadata. Choose ring clips
for variety of style *and* subject, and don't repeat the clips used in earlier sections where possible.
Place it near the end, before the brand beat.

## Converge
Learned from a reference ending: `thumbs.py manifest.json thumbs/` builds 7 crops per clip (≈400–500
sprites) with a group label each (perspective, style, duration class …). Then
`Converge(thumbs, word, groups, head=("<first half>", "<second half>"))`: clusters spin in place with
labels (0–2 s), particles fly along bezier paths through a horizontal band (2–4.6 s) into a dot-matrix of
the product name, then the second half of the header and a tagline fade in. The dot count depends on
the word length. Extra sprites dissolve and missing ones are duplicated. Watch the word: with very long
names lower `cell`/`dot`.

## Outro
`Outro(headline, subline, items, cta, url, invite, bg=, logo=, brand=)`: phase 1 shows
"<Product> is open source." with up to 4 item cards (weights, code, report, demo… **ask the user for the
real list**), and phase 2 shows the brand, "Try it yourself.", the URL typed into a pill, and an invite
line. Then it fades to black. Ten seconds is comfortable.

## Reusing an old draft's intro
If the user likes the first seconds of a previous cut, reuse them as a `Reader` source instead of
rebuilding them. To change burned-in text in it, run `erase_glyphs()` on that box and draw the new text.
Check the erased box across every background that passes behind it (see footage-qa.md).

## Typical timing budget (~2:20)
intro 4 · montage 4 · card 2 · website 9 · section A ≈20 · card 2 · section B ≈20 ·
card 2 · section C ≈12 · card 2 · long-horizon 12 · (extra section ≈14) · card 2 · wall 8 ·
converge 7 · outro 10.
