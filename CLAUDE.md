# CLAUDE.md — orientation for a fresh conversation

This file exists so a new conversation doesn't need to re-derive context
from scratch. Full detail, every fix with its evidence, lives in
**TASK.md** (working log, chronological, §1a through §1t so far) and
**README.md** (current-state summary). Read TASK.md's most recent
sections first if you need the reasoning behind a decision, not just the
decision. **Start a new session by reading §1o through §1t** (2026-09-22)
-- that's one long, dense working session and the "Next actionables"
section just below is the direct continuation of it.

## Next actionables (start here in a new session)

Picking up directly from the end of the 2026-09-22 session:

1. ~~Shadow/finishing strength should be stronger on custom/real-photo
   backdrops~~ **Done, 2026-09-22 (TASK.md §1u).** `contact_shadow_opacity_custom`
   (0.85 vs 0.65) and `finishing_grain_custom`/`finishing_vignette_custom`
   (0.010/0.16 vs 0.006/0.10) are now stronger for a photographed custom
   backdrop, wired through the `custom_backdrop` flag `compose` already
   threaded everywhere. `finishing_contrast` was deliberately left
   untouched (least colour-fidelity headroom of the three). Measured on
   the real pipeline (`IMG_8364` against a textured Nature library photo):
   dE2000 1.29 against the 3.0 budget, comfortable headroom. 3 new tests,
   152 total, all pass. Restart the server to pick this up if it's still
   running old code.
2. ~~Add/remove backdrop photos from the UI, live~~ **Already built (§1o),
   just not discoverable -- fixed, 2026-09-22 (TASK.md §1v).** Both
   accordions ("Or use your own backdrop photo" / "Your saved backdrop
   photos") now open by default on the Process tab, and the "remove" flow
   got a preview thumbnail so the operator can see what they're about to
   delete. **The Plain procedural library was also cut from 40 presets to
   1** (`studio_ivory`, white/neutral), asked for directly -- see §1v for
   what that touched and what it deliberately didn't.
3. **The two features approved earlier in the same session, still not
   built**: a click-to-place editor (click the preview to reposition,
   replacing the percentage sliders for that one interaction) and a
   per-photo free-text notes panel shown alongside the existing sliders
   after processing. (Backdrop-count growth toward "100" is no longer the
   direction -- see §1v below: the Plain procedural library was cut from
   40 to 1 by explicit request, and the real photo library, currently 12
   Studio+Nature, is now the primary growth path if more backdrop variety
   is wanted.)
4. **Not a bug, don't re-investigate**: a "floating fragment" reported
   on a real composite (`IMG_8325`) turned out to be a real cord/
   drawstring hanging from the actual garment, confirmed against the
   source photo -- the matte correctly kept it. If this comes up again on
   a different photo, check the source before assuming a matting defect.
5. **Not yet investigated**: alpha edge softness/blending on a cutout
   against a busy real-photo backdrop -- reported directly, distinct from
   the shadow/finishing gap above. No code looked at yet for this one.

## What this is

A locally-hosted pipeline that turns a photograph of a garment (worn by a
model, on an Indian ethnic-wear catalogue business — sarees, lehengas,
anarkalis, gowns, party dresses) into catalogue-ready imagery: cut the
garment out from whatever it was shot against, place it on a chosen
backdrop, export web-ready sizes — with colour measured against the
original at every step. `dressaug` package, `src/dressaug/`.

Sibling project: `../Image Augmentation/` does the same job for
silk-thread jewellery. Separate software, shares a parent folder and some
architecture/lessons (see TASK.md §2). Never reference or call into it.

## The one rule that governs every design decision here

**Never fabricate the product.** Synthesizing the world *around* a
photographed subject — backgrounds, shadows, lighting, framing — is fine.
Synthesizing the subject/product itself was off-limits all session, with
one narrow, explicit exception granted 2026-09-21: a *shading-only*
relighting adjustment is allowed if it's subtle, "unnoticed," and strictly
improves realism — **never** the garment's true colour, print, embroidery,
or shape. If a feature would touch the product's actual design, stop and
ask; don't assume the exception covers it.

## Current state (2026-09-22)

Phases 1 (background removal) and 2 (apply a new backdrop) are built and
in the app. Phases 3-6 (recolour, shaded recolour, design-edit-by-prompt,
mannequin) are not started — their stages raise rather than silently
passing through.

**150 tests, one command:** `.venv\Scripts\python.exe tests\run_all.py`

Run the app — **use `.\run.ps1`**, not `python -m dressaug.ui` directly:
it kills any already-running server first (see §1o — a stale server
serving old code, mistaken for "the fix didn't work", is a real failure
mode this project already hit once) and opens the browser once the
server actually answers.
```powershell
.\run.ps1
```
First-time setup on a machine that doesn't have `.venv` yet: `.\install.ps1`
(see its own output for what it does and does not install — matting needs
a separate torch interpreter, `DRESSAUG_TORCH_PYTHON` points at one if
this isn't the machine `../Boutique Business/` lives on).

Three tabs: **Process a dress** (the real pipeline, full-res export),
**Compare backdrops** (contact sheet — one photo or many, against the
single built-in Plain preset plus every real photo saved to your library;
preview only, no export), **What's built** (status page). A calm blue
`gr.themes.Soft` theme (sky/sky/zinc, close to VS Code's own accent —
changed from an earlier warm orange/amber/stone palette 2026-09-23, asked
for directly) since 2026-09-22, not the Gradio default — see §1r.

**Backdrops now come in three categories** (§1o, §1r, §1s, §1v): **Plain**
(one procedural preset, `studio_ivory`, white/neutral — cut from 40 on
2026-09-22, §1v), and **Studio**/**Nature** (real photographs, saved to
`data/backdrop_library/`, gitignored,
content-hashed). 12 real Studio/Nature photos already in the library,
sourced from Pexels under the Pexels Licence — provenance and photo IDs
in `data/backdrop_library/PROVENANCE.md`. Upload your own in either tab
("Or use your own backdrop photo" / "Also compare against your own
backdrop photos"), pick Studio or Nature, and it's saved permanently —
pickable by name or by eye in every run after, across restarts, until
removed in the Process tab's "Your saved backdrop photos" accordion.
**A Pinterest board was named as a source and declined** — see "Business
context" below and TASK.md §1s for why, before re-raising it.

### What's actually built, briefly (see TASK.md for the full story on each)

- BiRefNet matting, soft alpha kept unthresholded (fractional alpha *is*
  the product on sheer fabric — never thresholded away).
- **1** procedural backdrop (`backgrounds.py`, `studio_ivory` —
  went 11 → 40 on 2026-09-22 (§1r), then cut to 1 later the same day on
  explicit request (§1v): real backdrop variety now comes from the
  operator's own photographed library, not this module).
- Operator can upload **any photograph** as a custom backdrop instead of
  a preset (`ground.py` handles it — see below).
- GPU-accelerated matting (CUDA, shared interpreter with the sibling
  project at `../Boutique Business/.venv-cuda`, automatic CPU fallback on
  OOM) — this project's own venv deliberately has no torch.
- **Ground detection** (`ground.py`): a SegFormer/ADE20K scene-parsing
  model reads a custom backdrop photo for floor/grass/rug/stairs, plants
  the feet there, sizes the figure to the scene (wide room = smaller
  figure), and refuses backdrops that are mostly sky/water, table-height,
  or a graphic (as a manifest warning, not a hard failure).
- Lighting harmonisation (colour cast) + **directional** exposure matching
  (brightness shaped along the key-light direction, not one flat number) —
  both gated by `colour_fidelity` (dE2000 ≤ 3.0), both measured against
  real photos before being trusted, not just asserted.
- A feathered seam-only blur at the feet — **not** a whole-frame blur;
  that was tried twice and rejected on real output (reads as pasted, not
  as in-focus). Plus (2026-09-22) a separate, distance-from-subject
  **depth-of-field background blur** — sharp at and around the figure,
  gently soft only genuinely far from it; see §1o and §1p for why this is
  not the same thing as the rejected whole-frame blur.
- A contact shadow under the figure's own feet/hem, re-anchored 2026-09-22
  after being found (by actually looking, not just measuring) to sit
  detached in the gap below an uneven hem rather than touching it (§1p,
  §1q) — then given a second, denser "core" layer after a direct
  comparison against an external tool's output showed this pipeline's own
  shadow was still too soft even once correctly positioned (§1t).
- **A whole-frame finishing pass** (`stages.apply_finishing`, 2026-09-22,
  §1t) — the first thing in this pipeline that touches the *entire*
  composed canvas, subject and backdrop together, rather than the subject
  region or contact area alone: uniform grain (the subject used to have
  less texture than the backdrop it was pasted on), a mild sRGB contrast
  lift, and a true whole-canvas vignette. One slider ("Photo finish"),
  same 0-200%/100% convention as everything else. Its default strength
  was tuned down once already after breaking a real pinned test
  (dE2000 over budget) — see §1t for the exact numbers. Grain, vignette,
  and the contact shadow's own opacity are now stronger by default on a
  custom/real-photo backdrop specifically (§1u, 2026-09-22) — contrast is
  not, deliberately (see §1u for why).
- **Every automatic decision has a manual override** in the app: figure
  size, horizontal position, floor line, seam softening, light direction,
  colour tint strength, exposure strength, background blur strength,
  finishing-pass strength. The "Place automatically" checkbox controls
  only where the figure stands and how big it is — every lighting/finish
  slider always applies, fixed 2026-09-22 after they turned out to
  silently do nothing in the app's own default (auto-place-on) state. See
  §1p.

### Known, stated limitations (don't rediscover these — they're deliberate)

- Ground detection has one known false-positive class: a flat, defocused
  image (an abstract painting, a macro close-up) reads as "wall" to the
  model, same as a real plain wall, and comes back usable. No rule catches
  it without also refusing every real drape/curtain backdrop. Needs a
  human glance on genuinely ambiguous backdrop photos.
- No persistent worker — every matting/ground-detection call spawns a
  fresh interpreter (~10-25s fixed cost) even though the actual inference
  is fast (seconds). Fine for the current per-photo/per-backdrop usage;
  would matter for a genuinely large unattended batch. Flagged twice, not built,
  because nothing in this codebase yet needs it badly enough to justify
  the added lifecycle/IPC complexity.
- Colour tint is still a flat per-frame multiplier — no directional
  falloff. Exposure got its directional version 2026-09-22 (§1p); tint
  hasn't needed one yet (hue doesn't need to vary the way brightness does
  to read as "same room"). If that changes, `exposure_gain_field` is the
  pattern to follow.
- The depth-of-field background blur (§1p) is close to invisible on a
  smooth procedural preset (`midnight_velvet` etc.) — there is little
  detail there to begin with. Reads much more clearly on a textured,
  photographed backdrop.
- Colour margin is genuinely tighter since the finishing pass (§1t) —
  roughly 3-5% headroom under the 3.0 dE2000 budget on the tightest
  combinations actually measured (a strongly saturated garment against a
  dark backdrop), versus a wide margin on most others. The
  `colour_fidelity` gate will catch and report anything that does cross
  the line; the finishing-strength slider is the override for a specific
  photo that needs it.

## The AI-tooling question (resolved for now, may resurface)

A full session-length investigation (2026-09-21) into paid AI product-photo
services (Photoroom, Claid.ai, Pebblely, Flair.ai) and Higgsfield (already
MCP-connected) concluded:
- **Higgsfield is ruled out** for this job — its `product_shots_people`
  flow is generative (reference-conditioned diffusion), not compositing;
  real risk of regenerating fine garment detail (prints, embroidery)
  rather than preserving it. Also a poor billing fit for low steady-state
  volume (subscription-only credits, no top-up on this account at time of
  checking).
- **Claid.ai was the leading paid candidate** (explicitly markets
  "preserving true product details") but **the operator currently can't
  fund it.** A `claid-test-batch/` folder (gitignored, 5 real test photos)
  exists if this gets revisited — see its README.txt for what to check.
- Decision, 2026-09-22: **stay on the free procedural pipeline** and close
  real gaps in it instead (this produced §1n: exposure matching, the
  missing overrides, the Compare Backdrops tab).

If asked to revisit paid tools or a local relighting model (IC-Light etc):
this machine has a GTX 1650 (4GB, tight but workable — confirmed via real
VRAM measurement in §1i) and the shared CUDA interpreter already exists.
The blocking question before touching real product pixels for relighting
is the same one that gated this exception in the first place: does it stay
subtle/positive, or does it risk regenerating design detail? Test on real
photos and measure before trusting, same as every other fix here.

## Business context

Catalogue business, Indian ethnic wear (Raah Boutique — see the shared
Pinterest board `raahboutique/background` referenced in §1j/§1k for decor
style references, though those specific photos were never used directly
for copyright reasons). Target volume: ~200 images to start, then 2-3/month
ongoing. That low steady-state volume is *why* per-image subscription
services were a bad fit and why the free pipeline is the right call for now.

**The Pinterest board question came up again directly, 2026-09-22** —
asked explicitly to download it (plus general web search) for backdrop
photos, told not to worry about the copyright risk. Declined, same
reasoning as above, made explicit this time in TASK.md §1s: downloading
and shipping someone else's copyrighted photography in a commercial
product is an act, not just advice, and "I'll take the risk" reassigns
liability without changing what the act is. Sourced real backdrop photos
from Pexels instead (explicit commercial-use licence, documented in
`data/backdrop_library/PROVENANCE.md`) — if this is raised a third time,
the answer is the same; point to §1s rather than re-litigating it.

## Private data — never commit, never publish

All gitignored already; double-check before any broad `git add`:
- `test-images/` — the operator's own real garment photographs (iPhone
  HEIC originals). This is the primary real-photo test set.
- `data/backdrop_library/` — the persistent Studio/Nature backdrop photos
  (§1o, §1s), plus `PROVENANCE.md` recording where each one came from and
  under what licence.
- `data/ethnic-fixtures/` — 60 real Myntra-sourced ethnic-wear photos,
  provenance in `PROVENANCE.json`, licence caveat noted there.
- `data/fixtures/`, `data/raw/` — earlier HF-dataset test material.
- `claid-test-batch/` — 5 real photos exported for third-party evaluation.
- `work-reports/` — every visual proof/comparison sheet this session
  produced. Regenerable; what matters is transcribed into TASK.md. Still
  never committed (real garment photos in most of them).

## Git

Remote: `git@github.com:Parthesh10/dress-augmentation-for-catalogue-.git`
(added 2026-09-22, SSH access confirmed, empty at the time). Branch:
`master`. Verify `git status --short` and `git ls-files | grep -iE
"\.(jpg|jpeg|png|heic)$"` (should be empty) before any push, given how much
private photography touches this working tree.

## Working discipline (matches the rest of this session — keep it up)

- Measure before trusting. Every colour/lighting/placement fix this
  session was verified with real numbers on real photographs before being
  called done, and several were caught wrong on the first attempt by doing
  exactly that (the cove floor going negative, the exposure ratio flattening
  dark presets, a band-blur creating a visible stripe). Don't skip this
  step because the code looks right.
- Real photos over synthetic fixtures for anything visual. Synthetic
  fixtures are fine for pinning exact numeric behaviour (see `test_*.py`
  patterns throughout) but never sufficient alone for "does this look
  real" claims.
- Write tests before/alongside a fix, not after, when the bug was a real
  regression — several tests this session are pinned directly against a
  bug that was actually caught (search TASK.md for "caught by" or "found
  necessary" for the pattern).
- Restart the live Gradio server after any change to `stages.py`,
  `ui.py`, `backgrounds.py`, `ground.py`, or `config.py` before reporting
  a fix as done.
- Full account of *why*, not just *what*, goes in TASK.md as a new
  dated `## 1x.` section per unit of work, mirrored as a short paragraph
  in README.md. This file (CLAUDE.md) is an index into that, not a
  replacement for it — keep it short; put the reasoning in TASK.md.
