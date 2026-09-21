# CLAUDE.md — orientation for a fresh conversation

This file exists so a new conversation doesn't need to re-derive context
from scratch. Full detail, every fix with its evidence, lives in
**TASK.md** (working log, chronological, §1a through §1n so far) and
**README.md** (current-state summary). Read TASK.md's most recent
sections first if you need the reasoning behind a decision, not just the
decision.

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

**105 tests, one command:** `.venv\Scripts\python.exe tests\run_all.py`

Run the app:
```powershell
$env:PYTHONPATH="src"
.venv\Scripts\python.exe -m dressaug.ui
```
Three tabs: **Process a dress** (the real pipeline, full-res export),
**Compare backdrops** (contact sheet — one photo or many, against all 11
built-in presets plus any backdrop photos you add; preview only, no
export), **What's built** (status page).

### What's actually built, briefly (see TASK.md for the full story on each)

- BiRefNet matting, soft alpha kept unthresholded (fractional alpha *is*
  the product on sheer fabric — never thresholded away).
- 11 procedural backdrops (`backgrounds.py`), studio-cove geometry with a
  real floor, not a flat gradient.
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
- Lighting harmonisation (colour cast) + exposure matching (brightness) —
  both small, both gated by `colour_fidelity` (dE2000 ≤ 3.0), both
  measured against real photos before being trusted, not just asserted.
- A feathered seam-only blur at the feet — **not** a whole-frame blur;
  that was tried twice and rejected on real output (reads as pasted, not
  as in-focus).
- **Every automatic decision has a manual override** in the app: figure
  size, horizontal position, floor line, seam softening, light direction,
  colour tint strength, exposure strength. One "auto" checkbox gates all
  of them together — manual means all the sliders, exactly as they read.

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
- Colour tint and exposure matching are both flat per-frame multipliers —
  no directional falloff (brighter on the lit side, darker on the shadow
  side). That's the harder "relighting" problem; see below.

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

## Private data — never commit, never publish

All gitignored already; double-check before any broad `git add`:
- `test-images/` — the operator's own real garment photographs (iPhone
  HEIC originals). This is the primary real-photo test set.
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
