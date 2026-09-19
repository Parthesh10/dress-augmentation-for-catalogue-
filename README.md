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

---

## Status

| Phase | State |
|---|---|
| **1 — Background removal** | **Built, in the app.** BiRefNet matting, soft alpha kept unthresholded |
| **2 — Relevant background** | **Built, in the app.** 11 procedural backdrops, occasionwear palette |
| 3 — Recolour without changing design | Not started |
| 4 — Shaded / multi-tone colours | Not started |
| 5 — Design edits by prompt | Not started. First phase needing a generative model |
| 6 — Dress on a dummy | Not started. Needs a photographed dress form |

A stage belonging to an unbuilt phase **raises** rather than passing through,
so a run can never look more finished than it is.

**Verified 2026-09-11** — one garment across four backdrops, all gates passed,
ΔE2000 between 0.16 and 0.20 against a 3.0 budget. Roughly 50-75 s per image
on CPU. Comparison sheet in `work-reports/phase1-2/`.

**31 tests, one command:** `.venv\Scripts\python.exe tests\run_all.py`

---

## The app

```powershell
$env:PYTHONPATH="src"
.venv\Scripts\python.exe -m dressaug.ui
```

Opens at `http://127.0.0.1:7860`. Upload a photograph, choose garment type, fabric, a backdrop (by name or by eye), and export sizes; click Process. Recolour is shown, disabled, labelled "coming soon" -- not built yet, and not hidden either.

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
    --garment gown --background midnight_velvet

# the test suite
.venv\Scripts\python.exe tests\run_all.py
```

`--garment` picks the fabric default; `--fabric` overrides it. `--background`
takes any of the 11 presets. Backdrops suit different stock: `studio_ivory`
and `studio_pearl` for the plain commercial shot, `champagne_silk` and
`blush_plaster` for bridal and party, `midnight_velvet`, `wine_drape` and
`emerald_drape` for evening gowns.

**Matting needs the torch interpreter shared with the sibling project** at
`Boutique Business/.venv-birefnet`. This project's own venv deliberately has
no torch, so the operator machine stays a numpy-and-PIL install.

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
