# Localized builds (e.g. Chinese)

## Mechanism
`pk.set_language(table={...}, rules=[(regex, repl)], cjk=True)` translates every string at draw time
(`text`, `tw`, `wrap`, `pill` all go through `tr()`), so `SEGMENTS` stays in the source language. Choose
the language with an env var (`PROMO_LANG=zh`) and give each language its own segment dir and output
file, so the builds never overwrite each other. Strings missing from the table fall through untranslated.
Grep the rendered frames, or log `tr()` misses, to catch them.

With `cjk=True`, `Inter-*` fonts map to Noto Sans SC (`PROMO_CJK_DIR`, weights Regular/Medium/Bold/Black)
and pill labels are vertically centred with the `lm` anchor. CJK glyphs sit differently on the baseline,
and top-anchored labels looked visibly off-centre in the rounded tag ("左上角的小圆角方框中文字不太居中").
`wrap()` breaks CJK text per character.

## What to translate
- Slogans, section labels, card text, HUD words (TEXT/CAMERA/MOVE/LOOK, "Turn x of n" via rules),
  timeline labels, captions, the outro.
- The prompts shown in demo clips.
- The text typed into the simulated website. Re-record the site with translated field text and
  translated browser placeholders ("New Tab", the omnibox hint).
- Burned-in English in reused intro footage. Erase it (`erase_glyphs`) and redraw it in the target language.

## What not to translate
Model names, product names, company names, URLs, key glyphs (W A S D ↑ ↓ ← →).

## Translation quality
- Write for the screen, not word for word: short, parallel, idiomatic slogans. The user's own term
  choices override yours. Users often replace several literal renderings with their own terms. Keep a
  glossary of these overrides in the build and reuse it.
- Prompts must still describe what happens in the clip (same rule as the source language).
- After any wording change in one language, ask whether the other build needs the same change, or
  just make it.

## Rebuild
Re-render only the segments whose strings changed (`seg ...`), then `concat`. Check the localized cut's
duration matches the source-language cut exactly: same segments, same timings, same music.
