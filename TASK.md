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
| **1** | **Background removal** | **Built.** BiRefNet matting, soft alpha kept unthresholded |
| **2** | **Putting a relevant background** | **Built.** 11 procedural backdrops, occasionwear palette |
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

---

## 5. Open, in priority order

### P0 — a real defect, visible in the output

- [ ] **Edge decontamination is missing.** On the dark backdrops there is a
      pale halo around the garment: the semi-transparent edge pixels still
      carry the white studio background they were cut from, and compositing
      them onto midnight blue drags that white through. The sibling solves
      this in its `matte` stage and the fix was **not** ported. This is the
      single most visible flaw in phase 1 today and it gets worse the darker
      the backdrop, which is exactly where evening gowns want to sit.

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
