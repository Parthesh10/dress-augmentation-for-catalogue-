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

## 1c. HEIC support, and a discovery worth flagging, 2026-09-19

### The bug

Every `.heic`/`.heif` photo failed at `ingest` with `UnidentifiedImageError:
cannot identify image file`. Pillow has never shipped a HEIF decoder — a
patent-licensing decision upstream, not an oversight — so any photo straight
off an iPhone (HEIC by default since iOS 11, 2017) failed before the pipeline
did anything.

### The fix, and why it lives in `__init__.py` specifically

`pillow_heif.register_heif_opener()` now runs at `import dressaug` time, in
the package's own `__init__.py` — not in `stages.py`, where the actual
`Image.open()` call for the CLI path lives. That placement matters: Gradio's
own upload handling calls `PIL.Image.open()` directly, with no format
allowlist beyond a special case for SVG (confirmed by reading
`gradio.image_utils.preprocess_image` rather than assumed). A HEIC file
uploaded through the app is decoded by *Gradio*, before `dressaug.ui`'s own
code ever sees it — registering downstream of that would fix the CLI and
leave the app broken. `import dressaug` is the one thing guaranteed to run
before either path touches an image.

**4 new tests** in `tests/test_heic.py`, all against a *synthetic* HEIC file
generated on the fly by `pillow_heif` itself — never a copy of the operator's
real photos. One pins the actual mechanism (the opener really is registered
in Pillow's table after nothing but `import dressaug`), one round-trips a
real HEIC through plain `PIL.Image.open()`, one runs the real `ingest` stage,
and one confirms HEIC support didn't accidentally bypass the existing
size-floor rejection.

### The discovery: real stock photography, already on disk

While reproducing the bug, `test-images/Photos_/` turned out to hold **136
real HEIC files and 31 JPGs** — genuine garment photography, not a synthetic
fixture or a public dataset. **This folder was not gitignored and was one
`git add -A` away from committing the operator's private stock into version
control.** Fixed immediately, before anything else, in the same commit as
the HEIC support: `test-images/` added to `.gitignore`, same discipline as
`data/incoming/` and every other private-photo folder this project touches.

One file (`IMG_8262.HEIC`) was run through the full pipeline as part of
verifying the fix, not left untested once it opened: 3024×4032, well above
the resolution floor, and it is **a lehenga** — full skirt, fitted blouse,
dupatta thrown out mid-motion — the one category every dataset search in
§1.6 came back empty on. Background removed cleanly, full person preserved
(hair, both extended arms, the whole spread of the skirt), composited onto
`studio_ivory` at ΔE2000 0.17. One honest warning worth keeping: it was run
with `garment=SAREE` as a guessed default (that field has to be set by
whoever runs it; the pipeline cannot see what a photograph contains) and the
sheer-fabric check correctly flagged that the actual fabric declared didn't
match what the matte found — the check working as designed, not a bug.

**This is the real catalogue this project has needed since 2026-09-11.** Not
processed further without being asked — 136 files at roughly a minute each
is well over two hours of unattended compute, and the operator should decide
whether and how to work through their own stock before more of it is run.
---

## 1d. "Looks like floating in air, definitely edited" — grounding, 2026-09-19

### The complaint, and why it was right

The champagne-backdrop render of `IMG_8364` (a real lehenga, mid-motion) was
shown and the reaction was immediate and correct: the subject read as pasted
on, not photographed. Two separate, real causes, both found by measuring the
actual pixels rather than guessing:

**1. No shadow at all.** `stages.py` had `place()` and `compose()` built from
scratch for this project and never got the sibling's contact-shadow logic
ported. Every composite before this was a subject on a flat gradient with
nothing establishing contact with a surface.

**2. Vertical centring.** `place()` centred the bounding box in the canvas —
`oy = ch/2 - nh/2` — which puts equal empty backdrop above the head and below
the feet. No real full-length photograph is framed that way; the convention
is a small margin below and the rest of the slack as headroom above. This
turned out to matter more than the shadow: a perfectly placed shadow under
feet that are themselves floating in the vertical middle of the canvas still
does not read as grounded, because there is visibly empty space beneath the
shadow too.

### The fixes

**`stages.contact_shadow`** (new): a soft, blurred shadow read off the
subject's *own* contact band — the bottom slice of its already-placed alpha —
rather than a floor line guessed independently of where the subject actually
landed. Two iterations, both measured on the real photograph before being
trusted:

- **v1** centred the shadow almost exactly on the contact line. Measured
  directly on the rendered output: only ~4-6% darkening at the point closest
  to the subject, because half the shadow's own Gaussian peak fell under the
  subject's opaque pixels and was overwritten when the product was pasted —
  invisible at normal viewing size.
- **v2** offsets the shadow by 85% of its own vertical radius below the
  contact line, and scales the blur to the shadow's own size rather than a
  fixed fraction of the canvas. Re-measured: the visible darkening roughly
  tripled and now extends over a wider band rather than fading immediately.
  `contact_shadow_opacity` raised from an initial 0.38 to 0.45 to match.

**`place()`'s vertical anchor**, changed from centring to
`oy = ch - nh - bottom_margin` — almost all slack goes above as headroom, a
small fixed margin (`THRESHOLDS.bottom_margin`, 5% of canvas height) stays
below. Horizontal centring is untouched; a garment is not asymmetric the way
a standing figure's headroom-vs-footroom is.

Both threaded the backdrop's own key-light direction through `composite()`
and `export()` (`ctx.extra["key_direction"]`, which existed already but was
never passed to `compose()`), so the shadow's slight horizontal offset agrees
with where the backdrop's light is supposed to be coming from rather than
being arbitrary.

**7 new tests**, all in `tests/test_pipeline.py`: the shadow appears near a
synthetic figure's feet and is genuinely visible outside the region the
product's own paste will overwrite (the specific failure v1 had); no shadow
appears far from the subject or when there is nothing at the frame's bottom
edge to ground; the offset direction responds to `key_dir`; both registered
stages actually thread `key_direction` through rather than falling back to
a default; and the bottom-anchoring itself, checked directly against
`THRESHOLDS.bottom_margin`.

### Re-verified on both real photographs, not just synthetic fixtures

`IMG_8364` (the original complaint — a lehenga in a dynamic mid-air spin) and
`IMG_8300` (a second, calmer photo of the same person in a Garba/dandiya
pose, skirt pooling on the ground) were both re-rendered after the fix. Gates
held: colour fidelity 0.18 and 0.06 respectively against a 3.0 budget,
framing and cutout-softness unaffected — the grounding fix touches placement
and the backdrop only, never the product's own pixels or colour.

**The improvement is real and visible on both, and it is honestly stronger on
the second.** `IMG_8300`'s calmer, weight-settled pose now reads as a
standing figure with normal headroom and a real shadow beneath the skirt.
`IMG_8364` is better than before — properly anchored near the bottom now,
which it was not — but a mid-air twirl with one foot barely visible is
genuinely one of the harder cases for *any* grounding technique, because part
of what makes it look "in the air" is that **the photograph is of a moment in
the air** — no compositing fix removes that, because it was never a
compositing problem alone. This is stated plainly rather than oversold:
grounding fixes the parts of "looks edited" that came from the pipeline;
a dynamic action shot will still look dynamic.

### What this means going forward, and what was not attempted

- **Calm, weight-settled, both-feet-grounded photographs will composite most
  convincingly.** This is now a real recommendation with evidence behind it,
  not a guess — the same conclusion the sibling project reached about
  photographing garments flat rather than worn.
- **Not attempted: relighting the subject to match the backdrop's light
  direction and hardness.** `IMG_8364` and `IMG_8300` were both shot outdoors
  under natural light with visible directional highlights on skin and fabric;
  the procedural backdrops are soft and evenly lit. That mismatch is a real,
  separate contributor to "looks composited" that grounding does not touch,
  and fixing it convincingly for a whole photographed person — not a small
  opaque product, which is what the sibling project's own `relight` stage
  does — is a substantially harder problem, most plausibly needing a
  generative relighting model rather than the deterministic arithmetic this
  pipeline is built from. Flagged as a real limitation, not solved here.
- **Not attempted: a literal floor plane in the backdrop** (visible ground
  texture, a horizon line). The shadow-only approach was chosen deliberately
  because a painted floor would need to be coordinated with wherever `place`
  puts the subject to avoid a worse mismatch (subject floating above or
  sinking below a floor line that does not agree with it) — the shadow is
  self-consistent with placement by construction, because it is measured
  from the same alpha. Worth revisiting only if the shadow alone proves
  insufficient across more real photographs.
---

## 1e. HEIC support that worked in tests and failed in the browser, 2026-09-19

### The gap the earlier fix missed

§1c's fix (`pillow_heif.register_heif_opener()` at `import dressaug` time)
made every HEIC test pass, including one specifically written to prove
Gradio's own upload path decodes correctly. It was still wrong: uploading a
real `.heic` through the app's actual drop zone in a browser was refused
before that decoder was ever reached, with *"Invalid file type only image/*
allowed."*

The two checks are different and live in different places. §1c fixed the
**server-side decode** — can Pillow open the bytes once they arrive.
This is the **client-side upload gate** — does the browser let the file be
sent at all. `gr.Image`'s upload widget checks the browser's own MIME sniff
of the selected file against `image/*`, in compiled frontend JS shipped
inside the `gradio` package, before any Python code runs. On Windows,
`.heic` commonly has no OS-level file association, so the browser reports
an empty MIME type for it, and the check fails silently for every HEIC file
regardless of what the server can decode.

No automated test in this project runs a real browser, so nothing caught
this — the exact reason it is recorded here rather than assumed fixed.

### The fix

The upload widget in `build_process_tab` is now `gr.File` with an explicit
`file_types=["image", ".heic", ".heif"]`, not `gr.Image`. Read
`gradio_client.utils.is_valid_file` rather than assumed: `gr.File` validates
**server-side, by filename extension**, unaffected by whatever the browser's
MIME sniff says. A separate read-only `gr.Image` shows the decoded preview
once the file has actually arrived — `load_upload()` opens it exactly the
way `stages.ingest` will (EXIF-transpose, then RGB), so what the operator
sees before clicking Process is honest about what the pipeline will see.

**3 new tests.** One decodes a real file from `test-images/` when present,
falling back to a synthetic HEIC (never committed) when it is not, so the
test means something on a machine with no private photos on it. One pins
the mechanism directly — asserts the upload widget really is `gr.File`, not
`gr.Image` — specifically so a future edit that reverts the widget silently
reintroduces this exact bug without any of the other tests noticing, since
every other test calls `load_upload`/`process` directly and would keep
passing regardless of which widget the real app uses.

**Re-verified through the actual app function**, not only through the
lower-level pipeline: `ui.load_upload()` on a real `.heic` from
`test-images/`, its result fed into `ui.process()` exactly as a real click
would, gates checked. Passed clean.
---

## 1f. Every export was named "source", 2026-09-19

Asked directly: "where is output image? file location?" — the honest answer
exposed a real bug rather than just a directory path. Every export from the
app landed at `output/source--<preset>.jpg`, regardless of what was
uploaded, because `process()` always wrote the decoded image to a hardcoded
`source.png` inside its temp directory and never looked at the original
filename. **A second photograph silently overwrote the first's export.**

The fix did not need a filename invented anywhere: `gr.File`'s upload route
already sanitises and preserves the original filename as the basename of its
own server-side cache entry (confirmed by reading
`gradio/route_utils.py::upload_fn` rather than assumed) — `process()` was
simply discarding information Gradio had already given it. `_export_stem()`
reads it back; `process()` now takes the upload's own path as a second
argument (`run_btn.click`'s `inputs` gained `upload` alongside `image`) and
writes the temp file under that name instead of a fixed one, so `export()`'s
`ctx.source_path.stem` — and therefore the actual filename on disk — reflects
what was uploaded.

**4 new tests**, one of them extending the existing slow real-pipeline test
rather than adding a separate one: it now asserts the export file actually
exists at the *expected named path* under `OUT_DIR`, not merely that some
gallery of the right length came back. A regression that silently reverted
to `source.png` would have passed the old version of that test and failed
this one.
---

## 1g. Studio backdrops with an actual floor, 2026-09-19

### The ask

Asked directly, after seeing the grounding fix on a real photo: the flat
gradient still didn't look like the subject was "actually inside a studio,
shot this photo". The specific request was studio-style backdrops -- a
floor to stand on, not a colour field -- and full authority to design,
build, test and ship it without checking back in.

**No paid generation was used.** The Higgsfield connector's balance was
checked first (`{"credits": 0, "subscription_plan_type": "free"}`, same as
recorded when it was checked from the sibling project) and, given the
standing instruction not to risk the free tier, nothing was spent against
it. Built procedurally instead -- ₹0 cost, deterministic, fully in this
project's control, and the same approach every backdrop in this library
already uses.

### What was built

**`_cove`** (new render kind, `backgrounds.py`): a wall that curves into a
lit floor, the way a real photography studio's seamless backdrop paper
actually works -- one continuous sweep from wall to floor with no seam,
not two flat planes glued together. The 9 studio/occasion presets
(`studio_ivory` through `emerald_drape`) are now `kind="cove"` with a
`horizon` (roughly 57% down the frame); the 2 flat-lay presets
(`linen_flatlay`, `marble_flatlay`) are untouched `"surface"` -- they have
no standing subject and no floor concept distinct from the tabletop itself.

The floor reads as a genuinely different, closer plane rather than the wall
continuing to darken, using a depth cue (brighter toward the bottom of the
frame, the way a real floor catches bounce light close to camera) blended
across a soft band at the horizon -- deliberately no hard seam, since real
backdrop paper has none either.

This sits alongside, not instead of, §1d's contact shadow: the shadow was
always correct in principle, and it reads far more convincingly landing on
an actual rendered floor than on an undifferentiated gradient. Neither one
alone was the fix; both together are.

### Two real bugs found while measuring it, not assumed away

Every step here was checked with real numbers before being trusted, the
same discipline as the rest of this session:

1. **The first working version made the floor invisible on dark presets.**
   Measured directly: `studio_ivory` showed a healthy 9-21 sRGB-unit
   difference between wall and floor; `midnight_velvet` and `wine_drape`
   showed only ~2.5. The floor lift was computed as a linear-light ratio,
   and that ratio all but disappears into gamma compression on an already
   dark base colour -- the same amount of *light* produces a much smaller
   *visible* step the darker the surface already is. Fixed by computing the
   lift as a fixed amount of **sRGB** lightness instead, which keeps the
   step comparable regardless of how dark the preset is.
2. **The fix for that produced a floor darker than the wall above it.**
   The corrected version based its lift on `_wall`'s own rendered output --
   but `_wall` already carries a real, intentional downward-darkening
   gradient (rooms get dimmer toward the floor as bounce light falls off),
   and lifting *from* an already-darkening curve just produced something
   less dark, not something visibly brighter. Measured: `champagne_silk`
   came back **-13.5** sRGB units -- the floor read darker than the wall,
   which is the wrong direction and would have looked actively broken.
   Fixed by basing the lift on `_surface`'s undarkened lighting instead of
   on `_wall`'s already-dimmed output, decoupling "the wall gets dimmer
   going down" from "the floor is a bright, close plane" -- two different
   physical facts the first version had conflated.

**A test bug was found alongside the second one.** The original test
asserted `abs(above - below) > threshold`, which would have passed on the
broken -13.5 version just as easily as on a correct one -- it checked that
wall and floor *differ*, not that the floor is *brighter*. Rewritten to
assert the sign, and a second test added specifically pinning that dark and
pale presets land in the same ballpark, since that is the exact regression
that was found and fixed.

**6 new tests** covering: the 9 studio presets are genuinely `cove` with a
real horizon; the 2 flat-lay presets were not swept in by mistake; the
floor is measurably brighter than the wall (not merely different); no hard
seam at the transition; dark presets are not left with an invisible floor;
and nothing renders out-of-range light on the darkest presets. 31 pipeline
tests total.

### Verified on three real photographs, including the case that broke first

Re-rendered after each fix, not just after the last one:

| Photo | Backdrop | dE2000 | Notes |
|---|---|---:|---|
| `IMG_8364` (dynamic lehenga spin) | `champagne_silk` | 0.15 | Floor visible; foot near frame edge limits how much shows |
| `IMG_8300` (calm Garba pose) | `studio_pearl` | 0.12 | Floor plane clearly visible with the plant/pot for scale |
| `06-sarees-red` (real Myntra photo) | `midnight_velvet` | 0.46 | The dark-preset case that was broken twice before landing right -- floor now visibly lighter than the wall above it |

All three passed every gate; colour fidelity was unaffected in every case,
because grounding touches only the backdrop and placement, never the
product's own pixels.

### What this does and does not claim

It gives every studio backdrop a real floor and a shadow that lands on it,
which is a substantial step toward "looks captured, not edited" and was
verified, by eye, to be one on all three real photographs above -- worth
sending the actual files for a direct look rather than taking the
description on trust. It does not add true camera perspective, depth of
field, or floor reflections of the subject, and it does not touch the
lighting-direction/hardness mismatch recorded in §1d as a separate, harder
problem this pipeline does not attempt. A pose where the feet sit very
close to the very bottom edge of the frame (as in `IMG_8364`) still shows
less of the floor than a calmer, more centred pose does, simply because
there is less backdrop exposed around the subject to show it on.
---

## 1h. Checked for a free boost first; found none; built lighting harmonisation instead, 2026-09-19

### What was checked, and why it came up empty

Asked directly to check for free connectors before building further, and to
find open-source models if none existed. Checked three things, in order:

1. **Higgsfield's balance** (the only connector in this environment that
   does image work at all): still `{"credits": 0, "subscription_plan_type":
   "free"}`, same reading as every earlier check this session. Nothing to
   spend.
2. **Whether this machine could even run a heavier open-source model.** It
   turns out there *is* a real GPU here -- a GTX 1650, 4GB -- which was not
   obvious from the project's own history, since every earlier decision
   (§1c's HEIC work, the matting backend) was made assuming CPU only. But
   the torch interpreter this project already shares with the sibling
   jewellery project for BiRefNet matting (`Boutique Business/.venv-birefnet`)
   is a CPU-only build (`torch 2.13.0+cpu`) -- confirmed by asking it
   directly, not assumed. So the GPU is real but currently unusable without
   installing a ~2.5 GB CUDA-enabled torch build into an interpreter shared
   with another project's already-verified pipeline. That is a real option,
   not taken here: it is bigger than this task, it touches the sibling
   project's own working setup, and nothing about today's request needed it.
3. **Named open-source options that exist for this specific problem**
   ("image harmonization" is the actual computer-vision term for making a
   composited foreground read as if it were lit by the same light as its
   new background) -- `Harmonizer` (ECCV 2022) and `IC-Light` (relighting,
   SD1.5-based) are the two real, well-known, free ones. Both were set
   aside for now: both need the CUDA upgrade above to run at a usable speed,
   both are learned models that would touch the actual photographed
   product's pixels rather than only the backdrop around it, and neither
   was actually necessary -- the gap they would close turned out to be
   closeable deterministically, for the same reason §1g's cove floor was.

### What was built instead, with no new dependency

The real gap, once the backdrop had a floor (§1g) and the subject had a
shadow (§1d): **the subject's own photographed lighting is never
reconciled with the backdrop's.** A garment shot in cool daylight, pasted
onto a warm `champagne_silk` studio backdrop, still looks pasted even with
a perfect cutout and a correct floor, because the two don't share a light
source -- which is exactly the cue that reads as "edited" rather than
"captured", independent of geometry.

`harmonize_gain()` (`stages.py`) computes a small per-channel colour nudge
from the backdrop's *own* pixels right around where the subject is about to
stand -- not the whole frame, which would mix in wall and floor tones that
have nothing to do with the subject's own lighting. The sample's luminance
is normalised out before comparing, specifically so it does not mistake
§1g's cove floor -- deliberately brighter than its wall by design -- for a
colour cast to lend. `compose()` multiplies that gain into the subject in
linear light before pasting, alongside the existing shadow and placement
work, not instead of them.

**Bounded twice, and checked against a gate that already existed rather
than a new one invented for this.** `harmonize_strength` (0.16) sets how
much of the sampled cast is lent at all; `harmonize_gain_min/max`
(0.92-1.08) hard-clamps the result regardless of how saturated the backdrop
is. The actual backstop is the pipeline's own `colour_fidelity` gate --
already measuring dE2000 between the original photograph and the final
export, already budgeted at 3.0 because (`color.py`'s own words) "a gown
that ships a different red than the listing showed is a return." This
change adds no new safety mechanism; it just has to stay comfortably inside
the one that was already load-bearing.

**Measured, not assumed, to stay inside it.** Re-rendered the same three
real photographs from §1g, plus the fixture the UI's own end-to-end test
runs on every suite run:

| Photo | Backdrop | dE2000 before | dE2000 after | Budget |
|---|---|---:|---:|---:|
| `06-sarees-red` (dark saree, real Myntra photo) | `midnight_velvet` | 0.46 | 1.78 | 3.0 |
| `IMG_8364` (dynamic lehenga spin) | `champagne_silk` | 0.15 | 1.35 | 3.0 |
| `IMG_8300` (calm Garba pose) | `studio_pearl` | 0.12 | 0.24 | 3.0 |
| `0004-flat` (UI test fixture) | `champagne_silk` | -- | 2.12 | 3.0 |

The rise from near-zero to a real, non-trivial number is the proof the
harmonisation is actually doing something rather than being a no-op; the
largest of the four (2.12, a flat-lay garment whose own tone differed most
from the sampled backdrop patch) still leaves 29% of the budget unused. All
four gates still read `✓` (pass).

**5 new tests**: the gain is neutral on a grey backdrop; it leans warm
toward a warm backdrop and not the reverse; it stays inside its bounds even
against an adversarial, maximally saturated sample; it does not mistake the
cove floor's brightness for a colour cast; and `compose()` actually applies
it to the pasted subject rather than computing and discarding it (a
synthetic grey-on-orange case, checked numerically). The existing
real-pipeline end-to-end test in `test_ui.py` now asserts `colour_fidelity`
reads `[ok]`, not merely that the word appears in the report -- a version
that silently pushed the gate past budget would have passed the old
assertion and fails this one.

### What this does and does not claim

It is a deliberately small, deterministic nudge -- a colour-grading pass, not
a relighting model -- and it is meant to be felt rather than seen: on the
photographs above it moves the subject's own measured colour by roughly
half a dE2000 to under two, well below the threshold a viewer would
consciously register as "the garment changed colour," while still closing
part of the gap between "photographed elsewhere" and "photographed here."
It does not simulate directional light, specular highlights, or shadow-side
falloff on the subject the way a real relighting model would -- that is
what `Harmonizer` or `IC-Light` would add, and both remain available
options if the CUDA upgrade is ever worth taking on. This is the free,
zero-new-dependency step that was actually available today.
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
