# TASK — state of play

Working log, written so a fresh conversation needs none of this one's context.
Started **2026-09-11**.

> **Sibling project.** This is the second pipeline in `Business 1/`. The first,
> `Image Augmentation/`, does the same job for silk-thread jewellery and has
> been running for weeks. Its architecture, and more importantly its scar
> tissue, is inherited here on purpose — see §2.

---

## 1. The roadmap, as agreed

Six phases, in order. Two are built.

| # | Phase | State |
|---|---|---|
| **1** | **Background removal** | **Built.** BiRefNet matting, soft alpha kept unthresholded. **In the UI** |
| **2** | **Putting a relevant background** | **Built.** 11 procedural backdrops, occasionwear palette. **In the UI** |
| 3 | Change dress colour without changing design | Not started — stage registered and raises |
| 4 | Handle shaded / multi-tone colours | Not started — stage registered and raises |
| 5 | Change design a little, by prompt or button | Not started. **The first phase that needs a generative model** |
| 6 | Mock the dress on a dummy | Not started. Needs a photograph of a real dress form |

**Subject, fixed:** women's occasionwear — gowns, party dresses, lehengas,
sarees, anarkalis. **Not casual.** That narrowness is deliberate; the sibling's
numbers are trustworthy precisely because they were measured against one
catalogue rather than assumed from a general one.

A stage for an unbuilt phase **raises** rather than passing the context
through. A run that looks complete but silently skipped a step is the most
expensive kind of wrong in a pipeline whose whole claim is that its output can
be trusted.

---

## 1a. The UI, 2026-09-19

**A single app now exists.** `dressaug.ui` -- upload a photograph, pick garment
type, fabric, a backdrop (by name or by eye in a thumbnail gallery), export
sizes, click Process, get files back with the same colour/framing checks the
CLI reports. Recolour is shown as a disabled, clearly-labelled "coming soon"
control rather than hidden, so what the app does today is visible by looking
at it.

Run it:

```powershell
$env:PYTHONPATH="src"
.venv\Scripts\python.exe -m dressaug.ui
```

Verified three ways before being called done, not just imported:
1. the underlying `process()` generator run directly against a real
   fixture -- 2 files produced, gates reported, warnings surfaced;
2. the three guard paths (no image / no backdrop / no export size) checked --
   each refuses before touching the pipeline;
3. the server actually **launched** and answered HTTP 200, then closed
   cleanly -- not just "the Python imports without error".

One real bug found in the process: `_PRESET_LABEL_TO_NAME`, the lookup that
turns a checkbox label back into an export-preset name, was filled only as a
side effect of Gradio constructing its widgets. Calling `process()` directly
-- which is what the first verification step above does, and what
`tests/test_ui.py` does on every run -- raised `KeyError` on every preset,
because the widgets that would have populated it hadn't been built yet.
Fixed by building the map at import time instead of at UI-construction time.
`test_the_preset_label_map_is_populated_without_building_the_ui` pins it.

**10 new tests**, one of them running the real pipeline end-to-end through the
UI's own code path rather than through a mock. 25 tests total (later 29, once
the halo fix below added its own).

---

## 2. What was inherited, and why

| Taken | From | Why |
|---|---|---|
| `color.py`, verbatim | `imgaug/color.py` | CIEDE2000 is colour science and knows nothing about the subject. Conformance-tested there against Sharma, Wu & Dalal |
| `pipeline.py`, near-verbatim | `imgaug/pipeline.py` | Registry, context, runner, manifest. None of it knows what a product is |
| Backdrop **engine** | `imgaug/backgrounds.py` | Procedural, ~50 ms, deterministic, no weights. The **presets are new** |
| Model revision pinning | its `test_backends_pinning.py` | `trust_remote_code=True` executes Hub code; an implicit `main` runs what was pushed, not what was reviewed |
| No fp16 | its `modal_app.py` | BiRefNet's Swin backbone overflows and returns an all-NaN alpha. Not offered here at all |
| UTF-8 console setup | its `cli.use_utf8_console` | A cp1252 console kills a finished run in `print`. It cost the sibling a seven-case regression run |
| Bounding placement by **width as well as height** | its decor bug | A wide subject scaled by height alone came out at 128% of the canvas, clipped both edges, silently. A spread-out saree is that shape |

**Deliberately not inherited:** the Modal backend (its workspace has been
disabled since 2026-08-25, so it is a second code path that does not run), and
the skin-inclusion warning (it measures large smooth regions, and a plain
fabric garment is smooth by construction — it would fire on everything, which
is the same as never).

---

## 3. What is different, and it is one thing

Jewellery is small, opaque and rigid. A gown is large, often **partly
transparent**, and its shape is carried by folds that are part of the product.

Almost every number that differs from the sibling traces to that:

- `alpha_solid` **0.90**, not 0.98 — on chiffon almost nothing reaches 0.98, and
  at that cutoff the colour gate measures only the lining and seams.
- `alpha_floor` **0.04** — a real tulle hem has a true alpha of 0.1-0.2 and a
  higher floor amputates it.
- `min_partial_alpha_on_sheer` — a *new* check. A hardened matte of a net skirt
  looks tidy and has thrown the skirt away, so a garment declared sheer whose
  cutout comes back hard-edged gets warned about.
- `min_short_edge_warn` **1400**, not 1024 — a gown is photographed whole, so a
  lace hem occupies far fewer pixels than a bangle's stonework does.
- `garment_fill` **0.88** — a gown is the subject of the photograph, not an
  object placed in one.
- Export presets are **portrait-first**. A gown at 1:1 is either cropped at the
  hem or floating in side margins.

---

## 4. Verified working, 2026-09-11

One garment, four backdrops, on `local_cpu`:

| Backdrop | ΔE2000 | budget |
|---|---:|---:|
| `studio_ivory` | 0.16 | 3.0 |
| `champagne_silk` | 0.18 | 3.0 |
| `midnight_velvet` | 0.20 | 3.0 |
| `emerald_drape` | 0.20 | 3.0 |

All gates passed. Comparison sheet: `work-reports/phase1-2/`.

Roughly 50-75 s per image on CPU.

**Re-verified 2026-09-19** after the decontamination fix, same garment, same
four backdrops -- colour fidelity held (dE 0.29-0.38, still well inside the
3.0 budget) while the edge halo dropped substantially. Comparison sheet:
`work-reports/phase1-2-after-fix/`; zoomed before/after:
`work-reports/halo-zoom-compare.jpg`.

---

## 5. Open, in priority order

### P0 — a real defect, fixed 2026-09-19

- [x] **Edge decontamination, ported from the sibling.** `stages.decontaminate`
      estimates the old background colour from pixels the matte calls empty,
      then inverts the compositing equation at every semi-transparent pixel
      to recover the garment's true colour before it is placed on a new
      backdrop. `matte` now sets `ctx.product` from this rather than from the
      raw source, so both the preview composite and every exported file get it.

      **This is correct for sheer fabric too, and that took working through
      rather than assuming.** A net or chiffon pixel is not an edge artefact
      to be cleaned up -- the fabric really is partly see-through there. But
      the physics is the same equation (`observed = true_colour*a +
      background*(1-a)`), so recovering `true_colour` is exactly what correct
      alpha compositing needs regardless of *why* a pixel is fractional.
      Skipping sheer fabric would have been the bug, not an exception to it.

      **Measured, not just eyeballed:** a synthetic edge reproducing the halo
      showed a 45%+ reduction in colour error against a dark backdrop
      (`tests/test_pipeline.py::test_decontamination_makes_a_dark_backdrop_composite_closer_to_true_colour`),
      and a real photograph on `midnight_velvet` shows the same thing zoomed
      in: a visibly tighter, darker edge where the pale fringe was.

      **Reduced, not eliminated, and that is by design rather than an
      unfinished job.** `decontaminate` floors alpha at 0.12 before dividing,
      on purpose -- dividing by a near-zero alpha would amplify sensor noise
      into wild colours at the very tip of the rim. Those lowest-alpha pixels
      keep a small residual bias. If a future photograph still shows a visible
      fringe on a very dark backdrop, this floor is the first thing to
      revisit, not a sign the fix did not work.

### P1 — the dataset problem, stated honestly

- [ ] **There is no public dataset of women's occasionwear at production
      resolution with a usable licence.** Ten were checked on 2026-09-11;
      `docs/01-datasets.md` records each and why it was rejected. Two were
      downloaded and inspected rather than judged from their cards.
      What is on disk now is 60 development fixtures cut from casual tops at
      512×512 — honest for exercising the algorithms, useless for tuning any
      threshold. **The real input is your own photographs**, exactly as it was
      for the sibling.
- [ ] Photograph 20-30 real garments from stock and put them in
      `data/incoming/`. That, not a bigger download, is what unblocks tuning.

### P2 — the next phases

- [ ] **Phase 3, recolour without changing design.** The whole of it is: move
      hue and chroma, leave lightness alone. Folds, embroidery and shadow are
      all lightness, and `max_recolour_luma_shift` already exists to police it.
- [ ] **Phase 4, shaded colours.** A garment with an ombre or shot-silk finish
      is not one colour, so a single hue rotation destroys the gradient.
      `shaded_hue_spread_deg` is the trigger for treating it as a distribution
      to be mapped rather than one hue to rotate.
- [ ] **Phase 5, design edits by prompt.** The first genuinely generative step,
      and the first that needs a decision the sibling never had to make: the
      sibling forbids generated subject matter outright (its ARCHITECTURE §13),
      because an invented measurement is indistinguishable from a real one.
      A dress whose *neckline was altered by a model* is a different product
      from the one in the photograph. **Before building this, decide what the
      listing is allowed to claim.**
- [ ] **Phase 6, dress on a dummy.** Structurally the sibling's wrist plate:
      a photographed dress form, its geometry measured once, garments placed
      against it. Blocked on the same kind of thing — one real photograph.

### P3

- [ ] Kaggle training. Nothing here trains a model yet and nothing needs to.
      The case for it is phase 1: a garment-specific matting model would beat
      a general salient-object one on lace and net. That is a real project and
      should start only once there are real garment photographs to train and
      validate against.

---

## 6. Running it

```powershell
cd "e:\Claude Workspace\Business 1\Dress Augmentation"
$env:PYTHONPATH="src"

# one garment, phases 1 and 2
.venv\Scripts\python.exe -m dressaug.cli --path data\fixtures\0000-flat.png `
    --garment gown --background midnight_velvet

# the whole test suite
.venv\Scripts\python.exe tests\run_all.py

# re-cut development fixtures from the parquet shard
.venv\Scripts\python.exe -c "from dressaug.dataset import cut_fixtures; cut_fixtures(60)"
```

Matting needs the torch interpreter shared with the sibling at
`Boutique Business/.venv-birefnet`. This project's own venv deliberately has
no torch, so the operator machine stays a numpy-and-PIL install.
