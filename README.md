# Dress Augmentation

A locally-hosted image pipeline that turns a photograph of a garment into
catalogue imagery: the dress is cut out from whatever it was shot against,
placed on a chosen backdrop, and exported web-ready — with its colour measured
against the original at every step.

**Subject: women's occasionwear.** Gowns, party dresses, lehengas, sarees,
anarkalis. Not casual, not menswear. That narrowness is the point.

This is the second pipeline in `Business 1/`. The first,
[`Image Augmentation`](../Image%20Augmentation/), does the same job for
silk-thread jewellery. Its architecture is inherited here deliberately, and so
is its scar tissue — see [TASK.md §2](TASK.md).

**Setting this up on a new machine to use it (not develop it)?** Use
[INSTALL.md](INSTALL.md) instead of this file — step-by-step, written for
someone who's never touched the codebase.

---

## Status

| Phase | State |
|---|---|
| **1 — Background removal** | **Built, in the app.** BiRefNet matting, soft alpha kept unthresholded |
| **2 — Relevant background** | **Built, in the app.** 1 plain preset + your own saved photo library |
| 3 — Recolour without changing design | Not started |
| 4 — Shaded / multi-tone colours | Not started |
| 5 — Design edits by prompt | Not started. First phase needing a generative model |
| 6 — Dress on a dummy | Not started. Needs a photographed dress form |

A stage belonging to an unbuilt phase **raises** rather than passing through,
so a run can never look more finished than it is.

**Verified 2026-09-11** — one garment across four backdrops, all gates passed,
ΔE2000 between 0.16 and 0.20 against a 3.0 budget. Comparison sheet in
`work-reports/phase1-2/`.

**Matting now prefers the GPU when one's available** (2026-09-20) — the
inference itself runs roughly 3x faster on this machine's GPU than on CPU
(~11s vs ~32s on a real photograph), with an automatic fallback to CPU if
the GPU ever runs out of memory mid-job. Per-image wall time is still
dominated by process/model-load overhead (~80-90s either way for a single
photo) -- the GPU's win compounds across a batch, not a single image. See
[TASK.md §1i](TASK.md).

**150 tests, one command:** `.venv\Scripts\python.exe tests\run_all.py`

---

## The app

```powershell
.\run.ps1
```

First time on this machine, or a fresh checkout: `.\install.ps1` first (creates
`.venv`, installs everything except torch -- see its own printed output for
why, and what background removal still needs). `run.ps1` stops any
already-running Dress Studio server before starting a new one -- a stale
server left over from an earlier session, still answering on the same port
with old code loaded, is a real way this app has looked "unfixed" after a
real fix (see [TASK.md §1o](TASK.md)) -- then opens `http://127.0.0.1:7860`
once it actually answers.

Upload a photograph, choose garment type, fabric, a backdrop (by name, or by
eye in the gallery -- clicking a thumbnail now actually selects it, fixed in
§1o), and export sizes; click Process. Recolour is shown, disabled, labelled
"coming soon" -- not built yet, and not hidden either.

**A backdrop photo you upload is saved.** Both the Process tab ("Or use your
own backdrop photo") and the Compare tab ("Also compare against your own
backdrop photos") save whatever you add to a small library on disk
(`data/backdrop_library/`, gitignored) -- it's offered by name and by eye in
every run after, across restarts, until you remove it. Before §1o this only
ever lasted the one run it was uploaded in.

**Exports land in `output/`, named after the file you uploaded** -- fixed
2026-09-19; every export used to be named `source--<preset>.jpg` regardless
of what was uploaded, so a second photograph silently overwrote the first's
result. See [TASK.md §1f](TASK.md).

**Accepts iPhone photos (.heic/.heif) directly**, added 2026-09-19 in two
parts. Pillow has never shipped a HEIF decoder, so every photo straight off
a phone failed on the server -- fixed. Separately, and found only after that
fix looked complete: the app's own upload widget was rejecting `.heic`
files in the *browser*, before Python ever saw them, because Windows
commonly reports no MIME type for the format and the widget's client-side
check refused anything that did not sniff as `image/*`. Fixed by switching
to an upload widget that validates by filename extension server-side
instead. See [TASK.md §1c](TASK.md) and [§1e](TASK.md).

---

## The one thing that makes this different from the jewellery pipeline

Jewellery is small, opaque and rigid. A gown is large, often **partly
transparent**, and its shape is carried by folds that are part of the product
rather than lighting error.

A bangle pixel is product or it is background. A chiffon dupatta or a tulle
skirt is genuinely both — and a matte that forces it to one or the other
either eats the hem or drags the old background through with it. Nearly every
threshold this project sets differently traces back to that one fact, and each
difference carries the reason in a comment next to it.

---

## Running it

```powershell
cd "e:\Claude Workspace\Business 1\Dress Augmentation"
$env:PYTHONPATH="src"

# one garment through phases 1 and 2
.venv\Scripts\python.exe -m dressaug.cli --path data\fixtures\0000-flat.png `
    --garment gown --background studio_ivory

# the test suite
.venv\Scripts\python.exe tests\run_all.py
```

`--garment` picks the fabric default; `--fabric` overrides it. `--background`
takes any name in `backgrounds.PRESETS` -- as of 2026-09-22 (§1v) that's
just `studio_ivory`, a plain white/neutral studio backdrop; real backdrop
variety now comes from your own photographed backdrop library instead (see
"A backdrop photo you upload is saved" above).

**Matting needs the torch interpreter shared with the sibling project** at
`Boutique Business/.venv-birefnet`. This project's own venv deliberately has
no torch, so the operator machine stays a numpy-and-PIL install. On a
machine that doesn't have that sibling project, set `DRESSAUG_TORCH_PYTHON`
to any Python interpreter with torch + transformers + torchvision installed
instead of editing source -- see [TASK.md §1o](TASK.md).

---

## Tested on real Indian ethnic wear, 2026-09-19

12 real sarees, kurtas and kurta sets — worn by real models, on Myntra retail
photography — went through background removal with **mean IoU 0.935** on the
person-preservation check and **max 2.5% head/hair region loss**. 7 went
through the full pipeline: **7 of 7 passed every gate**, ΔE2000 between 0.10
and 0.47 against a 3.0 budget. Full account, including two results that
needed investigating before being trusted rather than just quoted, in
[TASK.md §1b](TASK.md).

**Local testing only — never published.** `data/ethnic-fixtures/` is
gitignored; see its own `PROVENANCE.json`.

**Not yet tested: lehengas, gowns, party dresses specifically**, or anything
shot outside a studio. `data/` also holds development fixtures cut from a
public dataset of **casual tops at 512 px, not occasionwear** — useful for
exercising the algorithms, useless for tuning a threshold. Both are recorded
in [docs/01-datasets.md](docs/01-datasets.md). **The real input is still the
shop's own photographs** — [TASK.md §5](TASK.md) says what a useful first set
looks like.

---

## 6 more real photos, and the Pinterest board declined a third time, 2026-09-22

Asked directly to download from the `raahboutique/background` Pinterest
board plus general web search — declined again, unchanged reasoning
(re-hosted photography carries no licence information; a general web
search result isn't verifiably licensed either). Sourced 6 more real
photos from Pexels instead (4 Studio, 2 Nature), same vetting as the
original 12: no identifiable person as the main subject, 3000px+
resolution, added through the library's own `add()` so they carry a real
manifest entry rather than a raw file drop. **Library is now 18 real
photos.** Provenance in `data/backdrop_library/PROVENANCE.md`. Full
account in [TASK.md §1w](TASK.md).

## Library add/remove made visible, a removal preview, and Plain trimmed to one, 2026-09-22

Three requests, one thread. The add/remove backdrop-library UI already
existed (upload-and-auto-save, a "Your saved backdrop photos" dropdown
with Remove, both live with no restart) — the gap was that both lived
inside collapsed accordions on the Process tab and hadn't been found.
Fixed by opening both by default, plus a real **preview thumbnail** on
the removal dropdown so it's clear what's about to be deleted before
clicking Remove.

**The Plain procedural library was cut from 40 presets to 1**
(`studio_ivory`, white/neutral), asked for directly. Real backdrop variety
now comes from the operator's own photographed library, not the
procedural engine. Every UI surface that offers Plain backdrops iterates
`backgrounds.PRESETS` itself rather than a hardcoded count, so this needed
almost no plumbing changes — the real work was in the test suite, where a
handful of tests had hardcoded now-removed preset names or asserted a
luminance *spread* across the library that no longer exists by design.
Those were rewritten or removed outright, not patched around, with the
reasoning left in place rather than silently dropped. Full account in
[TASK.md §1v](TASK.md).

## Stronger shadow and finishing on custom backdrops, 2026-09-22

Direct continuation of the gap below: the two-layer contact shadow and the
whole-frame finishing pass both measured as present but read as invisible
against a busy, textured real photo (a gravel garden path). Fixed by going
in the *opposite* direction from the colour-tint/exposure pair, which is
already more cautious for an operator's own uploaded backdrop — the shadow
only ever darkens backdrop pixels (drawn into the canvas before the
subject is pasted), and grain is zero-mean, so neither has the
`colour_fidelity` reason the tint/exposure pair does to hold back. Contact
shadow opacity, finishing grain, and finishing vignette are now stronger
by default on a custom backdrop; contrast was left alone, deliberately —
it already had the least measured headroom under budget. Measured on the
real pipeline (the library's own tightest colour_fidelity case, a vivid
green lehenga, against a real textured Nature backdrop): dE2000 1.29
against the 3.0 budget, comfortable headroom. **3 new tests, 152 total.**
Full account in [TASK.md §1u](TASK.md).

## Closing the gap with an external AI tool, without needing it, 2026-09-22

Used an external tool (Gemini/"Nano Banana") as a diagnostic, not a
destination -- ran the same photo through it and compared the actual
crops against this pipeline's own output. Garment fidelity held on both
(same pattern, same embroidery, it recoloured rather than redesigned),
but its shadow was denser and more concentrated at the contact point,
and its whole frame had a uniform grain and a mild contrast/vignette this
pipeline never applied to anything but the subject region. Three real
fixes: a second, narrower shadow layer under the existing one (`maximum`
of a soft ambient ellipse and a dense core, closer to how a real contact
shadow actually falls off); a brand-new whole-frame finishing stage
(grain, contrast, vignette, one slider, applied to backdrop *and*
subject alike, independent of the placement checkbox from the start);
and a real regression caught by the existing test suite, not by hand --
the first contrast value broke a pinned end-to-end test outright
(dE2000 3.35 against the 3.0 budget), fixed by reducing it and
reverifying on the actual failing case rather than a different one.
**12 new tests, 149 total.** Full account, including the honest note
that colour margins are now genuinely tighter on saturated-garment/dark-
backdrop combinations, in [TASK.md §1t](TASK.md).

## A silently-ignored slider, a shadow floating in the gap, and a real depth-of-field blur, 2026-09-22

Reported again, after looking at real output: it still reads as
copy-pasted. Two real bugs, not a weak formula, turned out to be why.
**The exposure, tint, light-direction and seam-blur sliders had no effect
in the app's own recommended default state** -- all four lived behind the
"Place automatically" checkbox, which defaults to on, so moving the
Exposure Match slider the ordinary way changed nothing. Fixed: lighting
now applies regardless of whether placement is automatic or manual.
**The contact shadow was computing correctly and still looked wrong** --
zoomed and looked at directly, it sat as a disconnected blob in the gap
below a real flared saree hem rather than touching it, because it was
being pushed clear of the contact line even when nothing needed clearing.
Re-anchored; before/after in
`work-reports/shadow-fix-2026-09-22/`.

Also new: a real **depth-of-field background blur** -- sharp at and
around the figure, gently soft only genuinely far from it -- distinct
from the two whole-frame blurs already tried and rejected, which blurred
everything uniformly. And exposure matching is now a **directional
gradient** along the key light, not one flat number, at essentially the
same `colour_fidelity` cost as the flat version it replaces (measured:
dE2000 2.21 vs. 2.24 on the same real photo). **12 new tests, 137
total.** Full account in [TASK.md §1p](TASK.md).

## A stale server, a decorative gallery, and a persistent backdrop library, 2026-09-22

Reported after actually looking at the running app: a backdrop comparison
looked unchanged from the day before. It was -- not a regression in the
work below, but **stale server processes** never restarted after code
changed, exactly the failure CLAUDE.md's own discipline had named without
anything enforcing it. Fixed, and now automated: `run.ps1` kills any
already-running server before starting a fresh one, and this fix was
itself verified by fetching the live server's `/config` and confirming it
actually contains this session's new code, not just that a server
answered on the port.

Two real UI bugs fixed alongside it, not just polish: the backdrop
gallery's "pick by eye" never actually selected anything on click (fixed
with a real `gallery.select()` handler), and export results showed two
identically-captionless thumbnails per photo, which is exactly what "no
change happened" looks like even when it worked (now captioned by preset
and size).

**Backdrop photos now persist.** Every "use your own backdrop photo"
upload used to live only for the run it was uploaded in -- gone on the
next run, let alone the next session, which is why the gallery kept
showing only procedural colours no matter how many real photos had been
sent. A new `backdrop_library.py` (content-hashed, `data/backdrop_library/`,
gitignored) fixes that: a photo saved once is offered by name and by eye
in every run after, in both the Process and Compare tabs, across
restarts, until removed.

Also: `install.ps1` / `run.ps1` for setting this up and running it on
Windows, a `DRESSAUG_TORCH_PYTHON` env var so the previously-hardcoded
sibling-project interpreter path is no longer required for moving this to
a second machine, and the case against a single `.exe` for now (this
project deliberately splits into two Python environments -- see
[TASK.md §1o](TASK.md) for why bundling them into one file would make
things worse, not better). **20 new tests, 125 total.** Full account in
[TASK.md §1o](TASK.md).

## Exposure matching, missing overrides, and a Compare Backdrops tab, 2026-09-22

Closed the gaps flagged after moving away from paid AI tools. Two overrides
that were missing -- light direction, colour tint strength -- now exist
alongside the size/position/floor/blur ones from §1m. New: **exposure
matching**, the other half of "lit by the same room" beside colour tint --
measured against the library's actual (bimodal) luminance, not a naive
ratio, and checked against the colour_fidelity gate on real photographs
before trusting it (worst case: +0.46 dE2000, still 25% under budget). And
a real **Compare Backdrops** tab: upload one photo or many, get a contact
sheet per photo against all 11 presets (plus any backdrop photos you add),
automatically placed -- the same comparison built by hand in scratch
scripts all session, now a feature, and bulk-capable from the start (one
matte per photo, not one per backdrop). Full account in
[TASK.md §1n](TASK.md).

## No blur except the seam; a figure sized to the scene; overrides, 2026-09-21

Three things reported on real output. The backdrop is now **never blurred
as a whole** -- a sharp HD cutout on a uniformly soft scene reads as
pasted, not in focus -- only a small feathered patch where the hem meets
the ground, localised in both axes so it can't become a stripe across a
floor (calibrated by eye against five variants; sheets in
`work-reports/blur-calibration-2026-09-21/`). The figure is sized to the
scene from where the floor starts: a wide room gets a smaller figure than
a close drape. And the app places automatically by default with four
overrides -- size, horizontal position, floor line, seam softening --
mirrored on the CLI. Full account in [TASK.md §1m](TASK.md).

## Ground detection that knows what a floor is, 2026-09-20

`ground.py`: a scene-parsing model (SegFormer on ADE20K, pinned, in the
same shared CUDA interpreter as matting) reads a custom backdrop photo for
floor / grass / rug / stairs, plants the feet inside that region, and
refuses backdrops that are mostly sky or water, table-height, or a graphic
-- as a manifest warning, not an exception. Calibrated against 33 real
photographs whose floor lines and usable/unusable calls were recorded
*before* the model ran: 31/33 agree on usable; floor lines within 0.043
mean error. Known residual: a flat painting or a macro close-up is "wall"
to the model, same as a real plain wall -- those still need a glance.
Automatic by default in the UI, with the manual slider kept as override.
Full account in [TASK.md §1l](TASK.md).

## Depth of field and a per-backdrop floor line, 2026-09-20

Two fixes for the same complaint on real photographed backdrops: feet
looking planted in the air. `compose()` now softens the backdrop with a
light, subject-untouched blur before pasting -- real portraits have some
depth of field, and a perfectly sharp background was itself a "this is
composited" cue independent of colour or shadow. `place()` now takes an
optional `floor_frac`, so a photographed backdrop's own floor -- which can
sit anywhere in frame, unlike a procedural preset's -- can be set once per
backdrop (a UI slider, or `--floor-frac` on the CLI) and reused for every
garment composited onto it.

An automatic floor-line detector was prototyped and rejected: it couldn't
tell a real floor from a sea horizon or a painting's own brush strokes,
and shipping it would have been more confidently wrong at scale than
useful. Re-ran the curated real-photo batch below with both fixes: 27/27
still pass every gate, and the blur alone visibly closes most of the
remaining "looks edited" gap. Full account in [TASK.md §1k](TASK.md).

## Custom backdrop photos, 2026-09-20

An operator can upload **any photograph** as a backdrop now -- their own
venue, their own decor setup, or properly licensed stock -- instead of only
picking from the built-in procedural library. Wired through the UI (an "Or
use your own backdrop photo" upload, with an explicit licence note beside
it -- Pinterest/Instagram/search-engine images are not licensed for
commercial use) and the CLI (`--custom-backdrop PATH`). The same grounding,
shadow, and colour-fidelity checks run either way.

One real gate failure surfaced by an actual end-to-end test: a strongly
saturated custom backdrop pushed the §1h lighting-harmonisation nudge over
budget, because the built-in presets were designed with a muted palette
this project controls and an uploaded photo carries no such guarantee.
Fixed with separate, more cautious harmonisation bounds for custom
backdrops specifically. Full account in [TASK.md §1j](TASK.md).

## Matting on the GPU, measured before being trusted, 2026-09-20

Told to enable CUDA (§1h had found a GPU on this machine going unused) and
not to ask before continuing further work. Found a `.venv-cuda` already
sitting in the sibling project's folder, next to blank test frames from
2026-08-11 that are very likely the actual origin of this project's
existing "no fp16" rule -- never wired into any pipeline. No install
needed, just a decision to point production at what was already there, in
fp32.

**Measured, not assumed:** GPU and CPU output diffed pixel-for-pixel on a
real photograph (max difference 0.0039, within one 8-bit quantisation
step); peak VRAM use on a full frame measured at 3.35GB against a 4GB card
with ~3.4GB actually free -- tight enough that the worker script itself now
catches a CUDA out-of-memory error and retries on CPU rather than failing
the job. Full account, including why per-image wall time barely moved even
though inference itself is ~3x faster, in [TASK.md §1i](TASK.md).

## Lighting harmonisation, no new dependency, 2026-09-19

Asked to check for a free connector to push realism further before
building more; checked Higgsfield (still 0 credits) and confirmed the
machine's GPU (a real GTX 1650, previously unused -- the shared matting
interpreter is CPU-only torch) can't currently run a heavier open-source
harmonization/relighting model like Harmonizer or IC-Light without a ~2.5GB
CUDA upgrade to an interpreter shared with the sibling project -- a bigger
change than today's task needed.

Built the deterministic version instead: `harmonize_gain()` samples the
backdrop's own colour right where the subject is about to stand, and
`compose()` nudges the subject toward it in linear light, bounded to a
small range and normalising out the backdrop's own brightness (so it
doesn't mistake the cove floor's intentional brightness step for a colour
cast). No new gate needed -- it's checked against the `colour_fidelity`
dE2000 budget that already existed. Measured on four real photographs:
dE2000 moved from near-zero to 0.24-2.12, comfortably under the 3.0 budget,
proof the effect is real without being enough to change the garment's true
colour. Full account in [TASK.md §1h](TASK.md).

## Studio backdrops with a floor, 2026-09-19

Asked directly for backdrops that look like the subject was "actually
inside a studio, shot this photo" -- not a colour field. Built
procedurally, at zero cost (an image-generation connector was available but
had a zero balance, and the standing instruction was not to risk the free
tier): all 9 studio/occasion backdrops are now a `"cove"` -- a wall curving
into a lit floor with no seam, the way a real photography studio's
backdrop paper actually works. The 2 flat-lay presets, for a garment laid
on a table, are untouched.

**Two real bugs found while building it, both caught by measuring real
pixel values rather than eyeballing:** the first version made the floor's
lift invisible on dark presets (a linear-light ratio disappears into gamma
compression the darker the base colour is), and the fix for that produced
a floor measurably *darker* than the wall above it on every preset (a
lift derived from the wall's own already-darkening gradient just made it
less dark, not brighter). Both fixed and re-measured before being trusted.
Full account, including the exact numbers, in [TASK.md §1g](TASK.md).

## Grounding fix, 2026-09-19

Reported plainly: "looks like floating in air, definitely edited". Correct,
and two real causes, both fixed. A subject was placed **centred** in the
canvas -- equal empty backdrop above the head and below the feet, which no
real full-length photograph is framed like -- and had **no shadow at all**,
so nothing established contact with a surface. Fixed both: subjects now
anchor near the bottom of the frame with headroom above, and a soft contact
shadow is cast from wherever the subject's own alpha actually lands.

**Honest limit, stated rather than hidden:** grounding fixes what the
pipeline was doing wrong. It does not fix a source photograph of a genuine
mid-air jump looking like a mid-air jump, and it does not match a backdrop's
soft studio lighting to a subject photographed under hard outdoor sun --
that would need a relighting model, not deterministic placement. Full
account, including exact before/after pixel measurements on a real
photograph, in [TASK.md §1d](TASK.md).

## Halo fix, 2026-09-19

The pale edge that used to show around a garment on a dark backdrop is fixed.
Semi-transparent edge pixels carried a trace of the white studio background
they were cut from; `matte` now recovers each pixel's true colour before it
is placed on a new backdrop, the same technique ported from the sibling
project. Correct for sheer fabric as well as ordinary soft edges — see
[TASK.md §5](TASK.md) for why that is not a special case.

Reduced substantially, not to zero, by design: the very lowest-alpha rim
pixels keep a small residual bias on purpose, so dividing by a near-zero
alpha does not amplify noise into a wild colour.

---

## Licences

The two models this pipeline can reach are the sibling's, under the same terms
recorded in its
[THIRD-PARTY-NOTICES.md](../Image%20Augmentation/THIRD-PARTY-NOTICES.md).
No dataset image may reach a listing.
