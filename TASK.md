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

## 1b. Tested on real Indian ethnic wear, 2026-09-19

Everything before this point was tested on synthetic fixtures and casual
western tops at 512px -- honest for the algorithms, never a stand-in for the
real catalogue. This section is the first time real sarees, kurtas and kurta
sets went through the pipeline, and it answers two questions asked directly:
does this work on real Indian ethnic wear, and does a person wearing the
garment survive background removal.

### Where the real photographs came from

`benitomartin/fashion-product-images-small-900x1200` on Hugging Face -- a
re-upload, at usable resolution, of Param Aggarwal's Fashion Product Images
Dataset, itself scraped from Myntra listings. Full provenance and the
licence caveat are in `data/ethnic-fixtures/PROVENANCE.json`: the compiled
dataset is marked CC0 by the uploader, but the photographs are retail
product photography and CC0 on a compilation is not the same claim as CC0 on
each photo's copyright. **Local testing and development only. Never
published, never committed** -- `data/ethnic-fixtures/` is gitignored.

60 real garments were pulled (22 sarees, 14 kurtis, 11 kurta sets, 8 kurtas,
5 dupattas), all women's, all genuinely worn by a model against a studio
background -- this is on-model retail photography, not flat product shots,
which happens to be exactly the harder and more relevant case.

### Does a person survive background removal?

**Yes, measured on 12 real photographs, not assumed.** Method: a plain
whiteness threshold on the raw photo as ground truth for "this is the
subject" (valid because this dataset's backgrounds are genuinely near-pure
white), compared against BiRefNet's alpha mask.

| | |
|---|---|
| Mean IoU across 12 photographs | **0.935** |
| Head/hair region missed | mean **1.5%**, max **2.5%** |

Two of the twelve came back with a low overall IoU (0.70, 0.64) and both were
investigated by eye before being explained away, not dismissed. Both are
white or off-white garments against the white studio background: the
*ground truth itself* breaks there, because a white-on-white printed pattern
reads as "background" under the same whiteness threshold that correctly
identifies real background elsewhere. Diff visualisation confirmed it
directly -- the "missing" area was entirely the garment's own printed
pattern, correctly matted, misjudged by the test; the person's head, hair
and hands showed only a 1px anti-aliasing boundary, no real loss. Both are
recorded in `work-reports/person-preservation/*.diff.png` for anyone who
wants to check the reasoning rather than take it on trust.

**So the honest claim is: 12 for 12 on head/hair preservation, with the
measurement tool itself needing a caveat on 2 of them, not the matting.**

### Does it actually look right?

Seven real garments taken through the full pipeline -- matte, decontaminate,
composite -- across sarees, kurta sets, kurtis, kurtas and a dupatta, on
five different backdrops including two dark ones:

| Case | Backdrop | dE2000 | Framing | Cutout |
|---|---|---:|---|---|
| Grey/maroon saree | champagne_silk | 0.27 | 23.5% | 2.7% partial (sheer) |
| Maroon/gold saree | midnight_velvet | 0.47 | 26.1% | 5.7% partial (sheer) |
| Black/white saree | studio_ivory | 0.10 | 23.5% | 3.0% partial (sheer) |
| Black churidar suit | wine_drape | 0.34 | 18.2% | 2.3% partial (embellished) |
| Black kurti | studio_pearl | 0.21 | 35.0% | 2.7% partial (opaque) |
| White kurta | blush_plaster | 0.17 | 27.7% | 2.4% partial (opaque) |
| Orange dupatta over white kurta | studio_ivory | 0.29 | 36.2% | 2.4% partial (sheer) |

**7 of 7 passed every gate.** All well inside the 3.0 ΔE2000 budget -- the
worst is 0.47, more than six times under budget.

Looked at, not just measured -- zoomed crops in `work-reports/
real-ethnic-composites/`:

- **Hair against a dark backdrop** (maroon saree on `midnight_velvet`):
  individual strands hold, no white fringe. This is close to the hardest
  case background removal has -- fine dark hair against a dark backdrop --
  and it is where the 2026-09-19 halo fix mattered most.
- **The sheer pallu** on the same photograph: the pink fabric underneath is
  genuinely visible through the maroon net, with its embroidered motifs
  rendered crisply rather than smeared, and no residual white haze at the
  fabric's own soft inner edges.

### What this does and does not prove

It proves the pipeline holds up on real, on-model, worn Indian ethnic wear --
which is the actual catalogue this needs to serve, not a stand-in. It does
not prove coverage of every failure mode: 12 photographs is not exhaustive,
all 12 came from one dataset shot in one studio style, and none of them
tested a lehenga specifically (this shard had none) or a genuinely crowded,
low-light, non-studio photograph -- which is what a shop's own phone camera
will actually produce. `tests/test_person_preservation.py` keeps 3 of the 12
as a standing regression check, skipping gracefully when the fixtures are not
on disk, so this does not silently regress -- but it is not a substitute for
testing against the shop's own first real photographs once they exist.
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

### P1 — the dataset problem, partly closed 2026-09-19

- [x] **Real Indian ethnic wear found and tested against.** Not the
      women's-occasionwear-specifically search from 2026-09-11 (that still
      found nothing — see `docs/01-datasets.md`) but a Myntra-derived retail
      catalogue at real resolution, which does cover sarees, kurtas and kurta
      sets, at production resolution, worn by real models. §1b has the full
      account: 12 photographs measured for person-preservation, 7 taken
      through the full pipeline and looked at. **Local testing only, never
      published** — same licence caveat as every other dataset here.
- [ ] **Still missing: lehengas, gowns and party dresses specifically**, and
      anything shot outside a professional studio. This shard had zero
      lehengas. The real catalogue this project is for is still untested.
- [ ] Photograph 20-30 real garments from stock and put them in
      `data/incoming/`. That, not a bigger download, is what actually
      unblocks tuning against *this* shop's stock, lighting and camera.

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
