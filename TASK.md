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

## 1i. Matting runs on the GPU now, measured before being trusted, 2026-09-20

### What was asked, and what it followed on from

§1h checked for a free connector (none) and for open-source models
(Harmonizer, IC-Light) to push realism further, and found both blocked on
the same thing: this machine's GPU was real (a GTX 1650) but unusable,
because the torch interpreter this project shares with the sibling
jewellery project for matting was a CPU-only build. Told directly to enable
CUDA as well, and not to ask before continuing further engineering work.

### What was actually sitting on the machine already

Before installing anything: found a `.venv-cuda` already present in the
sibling project's own folder, next to a `cuda-test/` directory holding
blank output frames dated 2026-08-11. That is almost certainly where this
project's existing "fp16 is not offered" lesson (`backends.py`'s docstring,
inherited from the sibling) actually came from — BiRefNet's Swin backbone
returning an all-NaN alpha in half precision is a numerical property of the
model, not of which processor runs it, and a blank frame is exactly what an
all-NaN alpha renders as. `.venv-cuda` itself was never wired into any
pipeline; `torch.cuda.is_available()` on it returns `True` against this
GPU. No install was needed — only a decision to actually point production
at what was already there, in fp32, having learned from the evidence
already on disk not to repeat the fp16 attempt.

### Measured before being trusted, not assumed

Two real risks, both checked with numbers rather than assumed away, using
the same real photograph (`data/ethnic-fixtures/06-sarees-red.jpg`) already
used to verify the harmonisation fix in §1h:

1. **Does GPU output actually agree with CPU output?** Ran the identical
   matting worker on both interpreters and diffed the resulting alphas
   pixel-for-pixel: mean absolute difference 2.9×10⁻⁸, maximum 0.0039 —
   inside a single 8-bit quantisation step, i.e. floating-point noise
   between BLAS backends, not a real disagreement. Coverage (the fraction
   of pixels counted as product) was bit-identical.
2. **Does it actually fit in 4GB?** Measured peak VRAM allocation on a full
   frame at this project's `infer_size` (1024): **3.35GB allocated against
   a 4GB card with roughly 3.4GB actually free** after the OS's own usage.
   That is tight — tight enough that a fallback is not caution for its own
   sake, so the worker script itself catches a CUDA out-of-memory error,
   clears the cache, and retries the same forward pass on CPU rather than
   failing the job. A regression test (`test_backends.py`) checks the
   worker's generated source actually contains that catch-and-retry, and
   that it re-raises anything that is *not* an out-of-memory error rather
   than silently swallowing a real bug.

### What changed, and what didn't

`backends.INTERPRETER` now prefers `.venv-cuda` over `.venv-birefnet`
(falling back to the latter if the CUDA venv is ever absent) — the worker
script is the *same file* either way, detecting CUDA at runtime, so this is
one code path with two possible interpreters behind it, not two code paths
to maintain. `LocalCpuMatting` keeps its name and its `"local_cpu"`
identifier unchanged: every caller, config, and test already spells the
backend that way, and what it actually promises — runs on this machine, not
a cloud API — never changed. A new `last_device` attribute records which
device actually answered ("cuda", "cpu", or the OOM-fallback string),
threaded into `ctx.extra["matting_device"]` the same way `matte_coverage`
already is, so a real job's own report says which path it took rather than
leaving that invisible.

**Re-ran the real pipeline through the actual production `stages.matte()`
call, not a standalone script**, on the same photograph as §1h's largest
harmonisation case: `matting_device` read `cuda`, and the resulting
`colour_fidelity` dE2000 (1.78) and every other gate matched the CPU run
exactly — the GPU path changes nothing about the output, only how it gets
there.

**5 new tests** in a new `test_backends.py`: the CUDA interpreter is
preferred when present (with a real assertion on the fallback path too, not
only the happy path); the worker's generated source never contains `.half(`
or `autocast` outside its own comments explaining why not; the OOM
catch-and-retry exists and re-raises anything else; the model is still
pinned to a full 40-character revision SHA, not a short one; and
`last_device` starts `None` rather than a guessed default. 61 tests total.

### What this does not claim

**Per-image wall time barely moved** for a single photograph — 84-92s
either way, because a new Python subprocess spawns per call and importing
torch plus loading the model (~15-25s) dwarfs the inference itself for one
image. What actually changed is the inference portion alone: ~11s on CUDA
against ~32s on CPU on the same photograph, a real ~3× difference that
mostly disappears into fixed per-call overhead at batch-of-one but would
add up across a real catalog run of many photographs, since that per-image
saving repeats every time while the process-spawn cost does not compound
in the same way it would if amortised. **The natural next optimisation is a
persistent worker** that loads the model once and matters many images
through it, rather than spawning a fresh interpreter and reloading the
model per photograph — not built here, because it is a real architecture
change (subprocess lifecycle, an IPC protocol, error recovery across many
jobs rather than one) that deserves its own careful pass rather than being
folded into this one, not because it isn't worth doing.
---

## 1j. Custom backdrop photos, 2026-09-20

### The ask, and the copyright line drawn around it

Shared a Pinterest board (`raahboutique/background`) of event/decor
backdrop photography — floral arches, string-light drapes, ornate palace
interiors, garden archways, mandap-style drapes — and asked for a way to
put garment photos into backgrounds like these. This is a materially
different category from this project's own procedural studio presets: real
photographed locations and decor setups, not a colour field with a floor.

**The 33 photographs on that board are not licensed for this.** They are
pinned from other photographers' and decor vendors' own work, and using
them behind product photography on a commercial storefront is a real
copyright exposure, not a formality — flagged directly before building
anything. The operator's own reply took explicit responsibility for the
licensing side and asked for a working test batch against the board's own
images specifically, to see which ones actually work before deciding what
to do about sourcing properly-licensed versions. That batch is built and
reported below; the underlying feature this section documents does not
itself depend on any specific photograph's licence, and is the actual,
durable answer to "let me use a real photograph as a backdrop" once
properly-licensed images are in hand.

### What was built

An operator can now upload **any photograph** as a backdrop instead of
picking one of this project's own procedural presets — wired through both
the UI (an "Or use your own backdrop photo" upload, next to the licence
warning above) and the CLI (`--custom-backdrop PATH`).

Everything downstream — grounding, contact shadow, lighting harmonisation,
the colour-fidelity gate — runs on a custom photograph exactly as it does
on a procedural preset, with two things measured from the photograph
itself rather than looked up, because there is no authored preset to look
them up from:

- **`fit_custom_background`** covers the export canvas from the photograph
  (crop, not stretch or letterbox) at every export size independently —
  found necessary rather than assumed: the first version resized
  `composite`'s already-cropped working canvas a second time in `export`,
  which crops twice and drifts the framing at every size but the first.
- **`infer_key_direction`** guesses a plausible light direction from where
  the photograph itself is brightest in its upper 60% (a window, a sky, a
  practical light) — not a claim to have found the true light source, only
  a better default than a fixed one that might be wrong for a specific
  photograph.

### The one real gate failure this surfaced, and the fix

Running an actual end-to-end test caught something the built-in preset
library never had to face: a single strongly saturated flat-colour test
backdrop pushed the lighting-harmonisation nudge (§1h) to **dE2000 3.26**,
over the 3.0 colour-fidelity budget. Every procedural preset was designed
with a specific, muted palette and already measured safely inside that
budget across four real photographs (§1h: 0.24–2.12) — an operator's own
uploaded photograph carries no such guarantee, since it can be any colour
at all. Fixed by giving custom backdrops their own, more cautious
harmonisation bounds — half the strength, half the deviation range —
rather than weakening the setting that was already proven safe for every
built-in preset. `harmonize_gain(..., custom=True)`.

### Tests

**8 new tests**: the canvas-cover fit is exact and centre-cropped, not
stretched; the key-direction guess leans toward the photograph's own bright
side and stays neutral on a flat one; `stages.background` prefers a custom
photo over the configured preset name; `export` actually re-fits the custom
photo at each size rather than calling `backgrounds.render` on a name that
was never a real preset (the exact bug found above, pinned directly against
a regression); the custom-backdrop harmonisation bounds are measurably
tighter than the ordinary ones on the same adversarial saturated patch; a
missing preset name is no longer refused once a custom photo stands in for
it; and a full real-pipeline run with a synthetic custom backdrop clears
every gate. 70 tests total.
---

## 1k. Depth of field, and a floor line that can be set per backdrop, 2026-09-20

### What prompted it

Looking at the §1j batch against real Pinterest photographs, two things
still read as composited even on the backdrops with good colour and a
correct shadow: a perfectly sharp, fully-in-focus background (real
portraits almost always have some depth of field), and feet planted at a
fixed distance from the canvas bottom regardless of where the photograph's
own floor actually sits -- fine for a procedural preset, whose floor is
always exactly at the bottom by construction, wrong for a photographed
porch, table edge, or staircase whose floor can be anywhere in frame.

Two fixes were proposed directly, plus an offer to suggest something
better if there was one.

### The blur -- built as asked

`compose()` now softens the backdrop with a light Gaussian blur (2% of the
canvas's shorter side by default, `Thresholds.background_blur_frac`)
**before** pasting the subject -- the subject itself is never touched, only
the backdrop behind it, so a sharp product stays sharp against a slightly
soft scene, the way a shallow-depth-of-field portrait actually looks.
Applied at `compose()` itself rather than baked into the backdrop render,
so it scales correctly whatever resolution a given export size actually is.

### The floor line -- built differently than proposed, and why

The second ask was to have a model or manual labelling decide where the
floor sits, per backdrop, so a 500-photo batch comes out grounded. Before
building either: prototyped a plain automatic detector (the strongest
roughly-horizontal edge in the lower part of the frame) and ran it against
all 33 real photographs from the shared board. **It is not reliable enough
to trust unattended.** It found *a* line in nearly every photograph,
including the abstract skull painting (a false "floor" from paint texture),
the galaxy-over-sea photo (the sea's own horizon, not a floor), and the
macro flower close-up (an edge with no floor concept behind it at all) --
with no way, from pixels alone, to tell those apart from a real floor.
Shipping that would have looked *more* consistently wrong at 500-photo
scale than the fixed default it would have replaced, not less.

**What generalises safely is a number, not a detector.** `place()` now
takes an optional `floor_frac` -- where the feet should land, as a fraction
of canvas height -- and when it's given, the fill/scale calculation treats
only the space *above* that line as available to fill against, rather than
fighting a figure already sized for the full canvas against a line partway
up it (a real bug caught by the first test written for this: a figure
sized to fill 88% of the whole frame had no room left to also land its
feet at 50%, and silently landed at the bottom instead). This is a value
supplied **once per backdrop photograph**, not once per garment -- the only
reason a 500-photo batch is a few minutes of one-time review rather than
500 individual judgement calls, because the number is a property of the
backdrop, unchanged by whichever garment gets composited onto it.

Wired through the UI (a slider next to the custom-backdrop upload, "where's
the floor", defaulting to 95%) and the CLI (`--floor-frac`).

### The actual review, done once, against the real 33

Went back through the same 33 photographs from §1j by eye, this time
scoring where the floor sits on each (a gridded reference sheet made this
fast, not 33 separate judgement calls). The honest finding: **most
photographs with a real floor already sat close to the previous fixed
default** (0.85-0.93 versus the old fixed 0.95) -- floor-line tuning is a
real but secondary improvement. **The bigger lever is exclusion.** Four of
the 33 have no floor concept at all regardless of any tuning -- the
abstract painting, the galaxy/sea-horizon photo, the macro flower
close-up, and a stock-photo-pack's own promotional thumbnail -- and two
more (a wedding table, a wedding reception's own round tables) are
table-height scenes with no standing-figure floor in them. All six are
excluded from the curated batch below rather than forced through with a
tuned number that couldn't fix what the photograph itself doesn't show.
(A flat solid-colour swatch also on the board was kept in, at the ordinary
default -- a flat colour needs no floor line at all, the same as several
of the all-over foliage/texture backdrops.)

Re-rendered `IMG_8364` against the **27** backdrops that survived
curation (33 minus the 6 excluded above), with both the new blur and each
photograph's own reviewed floor line: **27 of 27 passed every gate**, dE2000
between 0.09 and 1.60 against the 3.0 budget -- comparable to §1j's
uncurated run, because curation removed photographs rather than changing
how any of them are scored, and floor-line tuning doesn't touch colour at
all. Contact sheet in `work-reports/pin-backdrop-batch-2026-09-20-curated/`.
Looked at directly, not just measured: the blur is the more visible change
of the two by far -- every one of the 27 now reads as a real shallow-depth-
of-field portrait rather than a sharp cutout pasted onto an equally sharp
photograph, which was the single biggest "this is obviously edited" cue
left standing after §1h and §1j.

**3 new tests**: the composited backdrop is measurably softer than the
input on a high-frequency checkerboard, while the subject's own colour
fidelity gate is untouched; `floor_frac` actually overrides the default
margin (caught the fill/scale bug above in the process); and `floor_frac=
None` reproduces the exact previous behaviour bit-for-bit, so every
procedural preset and every custom backdrop without a reviewed line renders
exactly as it did before this feature existed. 73 tests total.

### What this does not claim

The floor-line number is a judgement call, not a measurement -- exactly
like `infer_key_direction` (§1j) already admits about lighting, this admits
about grounding. It was set once, by eye, against 33 photographs already in
hand; a genuinely new, differently-shaped backdrop photograph would need
the same five minutes of review before its own number could be trusted,
and there is no shortcut here that skips that -- the finding above is
specifically that trying to skip it produces *worse*, more confidently
wrong results at scale than simply doing the review.

It also can't fix a pose that never touched the ground in the original
photograph. `IMG_8364`, the garment used for every render in this section,
is a mid-jump dance shot -- no floor_frac places its feet convincingly,
because there genuinely is no ground contact in the source photograph to
place. That is the correct, honest outcome, not a bug: the same photograph
composited onto a calmer, standing-pose garment shows the floor-line fix
doing real work, as the §1i/§1j photographs already did.
---

## 1l. Ground detection that knows what a floor is, 2026-09-20

### The ask

"Do better ground detection." §1k had prototyped an edge-based detector,
measured it against the 33 real backdrop photographs from the shared
board, and rejected it -- it found *a* horizontal line in nearly every
photograph, including an abstract painting, a sea horizon and a macro
flower close-up, with no way on pixels alone to tell those from a real
floor. Its replacement was a number set once per backdrop by eye. Asked
now to make the automatic version actually work.

### Why the second attempt is a different kind of thing, not a better tuned
version of the first

"Is this a floor?" is a question about what things *are*, and an edge
detector only knows where brightness changes. The answer needed a model
that knows what a floor, a lawn, a rug, a staircase, a sky, a sea and a
dinner table are -- and ADE20K scene parsing has every one of those as a
named class. `ground.py` runs a SegFormer trained on it (pinned to a
revision, same discipline as BiRefNet) in the same shared CUDA
interpreter §1i wired up -- which is the reason this was *feasible* today
and not two days ago -- then answers three questions from the class map:
how much of the frame is ground, where the ground starts, and what else
dominates the frame.

The class sets are built by **name** from the model's own `id2label`
inside the worker, not as hard-coded ids: the model's config is the
single source of truth for what "floor" means, and a revision that
renumbered classes would surface as a name mismatch rather than a silent
misclassification. The ids were also checked against the config directly
before any of this was written, not remembered.

### Calibrated against a known answer, not tuned until it looked plausible

Every threshold in `Thresholds` for this was set against the 33
photographs from §1k -- each of which already had a by-eye floor line and
a usable/unusable call recorded **before the model ran**. That order
matters: it means the numbers below are a score against a fixed answer
key, not a description of output that was adjusted until it agreed with
itself.

**Usable / unusable: 31 of 33 agree.** Every one of the six backdrops
excluded by hand in §1k separates out automatically, each on a rule that
names its actual reason:

| Backdrop | Rule that catches it | What the model saw |
|---|---|---|
| Wedding dinner table | table-height scene | 39% table |
| Wedding reception tables | table-height scene | 21% table + 20% chair |
| Night sky over a rocky shore | mostly sky/water | 61% sky (and 15% real, standable "earth" -- still not a catalogue backdrop) |
| Solid slate-blue colour card | mostly sky/water | 100% sky |
| Stock-photo-pack's promotional thumbnail | looks like a graphic | 21% signboard |

The colour card is a case where the model corrected the by-eye label,
not the other way round: §1k had kept it as usable-at-default, and on
reflection it is not a photographed place at all (the procedural presets
already do a flat colour better). The label was revised. The
stock-pack thumbnail was the one that *needed* a new rule -- its 7%
"floor" was already below the minimum, but the honest reason it isn't a
backdrop is the 21% "signboard", and no real place on the board came
back with any signboard/poster/screen at all.

**The two that don't separate: an abstract painting (91% "wall") and a
macro flower close-up (90% "wall").** A flat, defocused field is a wall
to the model, indistinguishable from a real plain wall -- and a real plain
wall *is* a good backdrop, so the rule that would catch these would also
refuse every drape and curtain on the board. Those two still need a human
glance. That is the honest ceiling of this approach on this kind of
input, stated rather than hidden, and pinned as behaviour in
`test_ground.py` rather than left as a surprise.

**Floor lines: mean error 0.043 against the by-eye calls, on the 15
backdrops where both exist.** The feet land 65% of the way into the
detected ground region (`ground_feet_depth`) -- its top edge is the far
wall, and feet planted there read as standing at the back of the room.
Thirteen of fifteen are within 0.06. The two outliers are a staircase
(model 0.75, a mid-step; by-eye 0.92, the bottom landing) and an abstract
texture wall whose lower third the model reads as floor (0.77 vs 0.90) --
both plausible placements that differ from the by-eye one, not broken
ones. In one case (a pavement strip under an ivy wall) the model found a
real floor the by-eye pass had called a flat wall.

**"No floor" is not "unusable."** This came straight out of the data:
three of the best drape and curtain backdrops on the board came back with
0% ground, and are exactly right at the ordinary default placement -- the
subject stands in front of them. Only sky/water, table-height and
graphic scenes are refused. A refusal is a **warning in the manifest**,
not an exception: the operator may know better, and a 500-photo batch
wants a number to filter on, not an error to catch.

### The batch, fully automatic

Re-rendered a calm standing-pose photograph (`IMG_8374`, hem at floor
level) against all 33 backdrops with **no floor line set by hand anywhere**:
the detector decided everything. 28 rendered and passed every gate
(dE2000 0.29-1.16 against 3.0), 5 skipped automatically with the reasons
above, 0 failures. Looked at, not just counted: on the rug, the lawn, the
room, the garden path, the stair step and the red carpet, the hem sits on
the actual ground plane rather than at a fixed distance from the frame
edge -- the first batch this session where that is true without a human
having set the number. Contact sheet, every output, and the per-backdrop
verdicts as JSON in `work-reports/pin-backdrop-batch-2026-09-20-auto-ground/`.
The two known residuals are in that sheet too, looking as wrong as
predicted.

### Wiring

`stages.background` runs the detector on the *original* upload (not the
cover-cropped canvas) when no floor line was set explicitly, so the answer
is a property of the photograph -- and it is cached by content, so the
same backdrop under 500 garments is detected once. The UI defaults to
automatic with the §1k slider kept as a manual override; the CLI's
`--floor-frac` is the override there. `matting_device`, `ground_verdict`,
`ground_usable` and `custom_floor_frac` now reach the written manifest, so
a batch can be audited from disk. If the CUDA interpreter is absent, or a
model download fails, the result is exactly the pre-§1l behaviour --
default placement -- with a `reason` saying why, never an exception.

**13 new tests** (`test_ground.py`): every rule in `judge()` pinned against
the *actual recorded numbers* the model produced on a real photograph in
that category -- no GPU, no download, no uncommitted photograph needed;
plus the graceful no-interpreter path, the full revision SHA, the
by-name class lookup, and one slow test that actually spawns the worker
and checks the subprocess/JSON hand-off end to end without claiming a
semantic verdict on a synthetic image it has no business judging. 88
tests total.

### What this does not claim

The throughput cost is real and stated: each backdrop's detection spawns a
fresh interpreter (torch import plus model load, ~10-20s) before the
sub-second inference. For a real catalogue run that is a one-time cost per
*backdrop* -- 28 detections for 28 backdrops, cached thereafter for every
garment -- but it is the same fixed per-call overhead §1i named for
matting, and the same persistent-worker design would remove it for both.
Not built here, for the same reason as there.

And it still can't ground a pose that never touched the ground. The
batch for this section deliberately switched from §1k's mid-jump dance
photograph to a calm standing pose with the hem at floor level, because a
subject that is airborne in its own source photograph cannot demonstrate
a grounding fix succeeding or failing -- which §1k's own batch, in
hindsight, had been trying to do.
---

## 1m. No blur except the seam; a figure sized to the scene; overrides in the app, 2026-09-21

### Three things reported on the §1l batch, in one pass

1. **The blur was still too heavy, and the real problem was named
   precisely:** a razor-sharp HD cutout on a uniformly softened backdrop
   reads as *pasted*, not as *in focus*. Softening the whole frame -- at
   any strength -- was the wrong idea, not just the wrong amount.
2. **The figure was the same size in every backdrop.** A wide room and a
   close drape are different distances from the camera; a person should
   be smaller in the first.
3. **The app should do all of this automatically, and let the operator
   override any of it** -- size, position, floor line, softening.

### The seam, and nothing else

`soften_backdrop` is on its third design, and the first two are recorded
in its docstring as rejected rather than deleted. It now applies **no
whole-frame blur at all**. The backdrop stays as sharp as the subject
everywhere -- which is what a real photograph at this scale looks like --
except a small feathered patch where the hem meets the ground, the only
place a paste seam actually exists. Localised in *both* axes: a Gaussian
in y around the contact line and a broad Gaussian in x around the
subject's own footprint, windowed at 3 sigma so "untouched" means
untouched. The horizontal localisation is what finally kills the stripe
across the floorboards that the first design produced: on a wide floor
the far left and right of the frame are bit-identical to the input.

Calibrated by eye, not by argument: five variants rendered on the same
herringbone floor, zoomed at the hem
(`work-reports/blur-calibration-2026-09-21/variants_feet_zoom.jpg`).
Radii of 0.010-0.015 of the shorter side smeared the boards into a
visible band; 0.006 softened the seam and left the boards legible. That
is the default; the app's slider scales it, and 0 turns it off.

The contact measurement (`contact_band`) was factored out so the shadow
and the feather sit on one number and cannot drift apart -- the same
reason `place` and the shadow already share `oy`.

### A figure sized to the scene

`ground.GroundEstimate.suggested_fill()`: the cue is where the floor
*starts*. Floor from 30% down means the camera is well back and a lot of
room is in shot -- the figure fills 62% of the available height; floor
only in the bottom 15% means a tight shot -- 88%, the ordinary default.
Linear between. A backdrop with no visible floor (a drape, a wall) is a
studio-style tight shot and keeps the default. Rendered across a
wide-to-tight run of seven real backdrops
(`auto_scale_wide_to_tight.jpg`): staircase 0.62, texture wall 0.65,
park 0.73, lawn 0.75, rug 0.81, room 0.86, drape default -- the
ordering is right and, looked at, none of them is wrong.

### Overrides in the app

One "Place automatically" checkbox (default on) and four sliders --
size, horizontal position, floor line, seam softening -- in a
"Placement" accordion that applies to preset and custom backdrops alike.
Automatic means: the ground detector decides floor and size for a custom
photo, the defaults apply for a preset, the seam softens at its default.
Manual means: the four sliders, exactly as they read, all together -- one
clear meaning, not four independent toggles. The CLI has the same four as
`--floor-frac`, `--fill`, `--x`, `--seam-blur`. All four reach the
written manifest. `composite` and `export` take them through one helper
(`_placement_overrides`) so the preview cannot disagree with the file.

Driven the way a click does, not through Gradio's event loop
(`app_auto_vs_manual_override.jpg`): auto puts her on the floor with the
seam softened; manual at size 55%, x 25%, floor 70%, softening off puts
her small, left, and floating on the wall -- deliberately wrong, to prove
the sliders are obeyed rather than clamped toward sense.

### Tests

Five blur tests rewritten for the new contract at a **real export size**
(a 300px toy fixture rounded the feather to 2px and measured nothing --
the first version of these tests found that out): the top of the frame
and the far edge of the contact row are bit-identical to the input; the
contact point is measurably softer; the far side of the contact row is
as sharp as the top (no stripe); strength 0 is off; no contact line is
no change. Plus the size/position overrides move and resize the placed
figure and never leave the canvas, and the scale rule orders a wide shot
below a tight one and returns None for no floor. **93 tests total.**

### What this does not claim

The scale rule is a linear map from one cue with two anchors set by eye
against seven backdrops. It gets the ordering right on those; a backdrop
whose floor starts high for a reason other than distance (a low camera,
a raked stage) would be sized as if it were wide. The slider exists for
exactly that case. And the feather is a compositing device, not depth of
field -- it hides a seam, it does not simulate a lens, and the docstring
says so.
---

## 1n. Every automatic decision gets a manual override; exposure matching; a contact-sheet tab, 2026-09-22

### The ask

Told directly the AI-service route (§1m-adjacent conversation) isn't
fundable right now, and to instead close real gaps in the existing
pipeline: tune the photo per backdrop, resize/reposition, **everything
reachable from the app itself**, a manual override for anything the
automatic pipeline might get wrong, and -- named as something already
genuinely useful -- turn the contact-sheet comparisons (built by hand in
scratch scripts all session) into a real feature, including comparing
**many** photographs at once ("bulk"), with the ability to add extra
backdrop photos into that comparison per image.

### The two overrides that were still missing

Placement (floor, size, position, seam softening) already had manual
overrides as of §1m. Two automatic decisions did not:

- **Light direction.** `infer_key_direction` (§1j) guesses which side a
  custom backdrop is lit from; there was no way to correct it if the
  guess read the scene wrong. `compose()` now takes `key_dir_x`,
  replacing only the horizontal component -- the vertical steepness stays
  whatever the backdrop's own value was, since nothing asked for control
  over that.
- **Colour tint strength.** `harmonize_gain` (§1h) had no per-run dial --
  it was always exactly the configured strength or, for a custom
  backdrop, exactly the halved one. `scale` (1.0 = ordinary, 0 = off)
  multiplies the *strength*, never the `gmin`/`gmax` clamp -- the clamp is
  what actually protects the colour_fidelity gate, and no operator number
  should be able to remove that backstop.

### Exposure matching -- the gap those two overrides sat next to

"Tune the original image to match the bg preset, little tweaks... to
make the end result look real" named a real, unaddressed gap directly:
colour *cast* was matched (§1h); *exposure* was not. A garment shot in
dull shade stayed dull against a bright sunlit room, and stayed
conspicuously bright against a dark drape, however well its colour
matched.

**Measured before choosing the formula, not assumed.** The backdrop
library's luminance turned out strongly bimodal: four dark presets at
0.030-0.049, seven light ones at 0.416-0.750, nothing between. A ratio
against the middle would ask for a 93% darkening on `midnight_velvet` and
flatten all four dark presets onto the same clamp -- the exact failure
mode the §1g cove-floor fix already diagnosed once this session, in the
opposite direction. `exposure_gain()` compares in **sRGB space** against
the library's median (`linen_flatlay`) instead, which spreads the four
dark presets sensibly: -4.5% to -5.1%, not identical.

**Deliberately does not try to match the backdrop's absolute brightness.**
A white dress in front of a near-black drape should stay recognisably
white -- the claim is only "this scene reads dimmer than average, light
the subject a little dimmer accordingly", never "make the subject as dark
as the backdrop". The clamp (`exposure_gain_min` 0.92) makes that
physically impossible regardless of input.

**Checked against the colour_fidelity gate on the same real photographs
already used to verify every earlier fix**, not just in isolation:

| Photo | Backdrop | dE2000 without | dE2000 with | Budget |
|---|---|---:|---:|---:|
| `06-sarees-red` (dark saree) | `midnight_velvet` | 1.78 | 2.24 | 3.0 |
| `IMG_8374` (bright, busy print) | `studio_ivory` | 0.69 | 0.78 | 3.0 |

The worst case costs 0.46 dE2000 and still clears the gate with 25%
headroom. Looked at directly, not just measured
(`work-reports/exposure-compare-2026-09-22/on-vs-off.jpg`): the dark-saree
case is the more visible of the two, and reads as *lit* by the darker
room rather than merely *placed in front of* it.

### Compare Backdrops -- a real tab, not a scratch script

Every contact sheet this session (§1g through §1l) was built by a
throwaway Python script run outside the app. `compare_backdrops()` is the
same idea as a first-class feature: upload one photograph or many, get
one contact sheet per photograph -- that garment against all 11
built-in presets, automatically placed, plus any backdrop photos added in
an optional accordion. **Preview only, by design choice** (asked
directly): nothing is exported from this tab; picking a backdrop here
means selecting it by name on the *Process* tab for the real file, so the
comparison stays fast and cheap while the export stays exactly the
pipeline already verified.

**The bulk case is not a separate code path.** Matting is the one
expensive step; the eleven-plus composites that follow are cheap, so N
photographs costs N mattes, not N x 11 -- and the function is a generator
that yields each finished sheet as it completes, so a batch of twenty
shows its first result after the first matte rather than after the
twentieth. Verified for real, not only asserted: two real photographs in
one call produced two sheets, the first yielded before the second matte
started.

Custom backdrops added to a comparison run through the same ground
detector as the Process tab; one the detector considers unsuitable is
still shown, labelled **[!]**, rather than silently dropped -- the
operator's own judgement stays the final word, same principle as the
warning-not-exception design in §1l.

### Tests

**13 new tests**: `key_dir_x` moves the shadow measurably and touches
only the horizontal component; `harmonize`/`exposure` scale-of-zero
disables each override exactly (not merely reduces it) while scale-of-two
still respects the hard clamp; `exposure_gain` is neutral at the
reference luminance and with no known luminance; the sheet-grid
assembly lays out eleven cells correctly and survives an empty list; the
Compare tab is wired to a real `file_count="multiple"` upload and actually
attached in `build()`; and the real bulk test above. **105 tests total.**

### What this does not claim

Exposure matching, like colour tint, is a global per-frame multiplier --
it cannot add real directional falloff (brighter on the side facing the
light, darker on the side away from it), which is the harder problem
named and set aside in §1i's "AI integration" discussion. The two
overrides added here (light direction, tint strength) are UI-level dials
on formulas that already existed; nothing about the underlying grounding,
colour, or exposure model changed, only that every one of them can now be
corrected by hand when it gets a specific photograph wrong.
---

## 1o. A stale server, a decorative gallery, and backdrops that don't survive a restart, 2026-09-22

### The ask

Six things, reported together after looking at the running app: (1) a
backdrop comparison batch looked identical to the previous day's, no
visible improvement despite §1n's work; (2) find and fix why; (3) UI/UX
that "many things are misleading than what we decided"; (4) how to
install this as Windows software, move it to another machine, and whether
to compile an .exe; (5) the backdrop gallery still shows plain procedural
colours, not the real photos already sent; (6) a backdrop a user adds
should still be there next time. Closing line: "take your own decisions
as well and make it overall better."

### 1 & 2. Why it looked unchanged -- a stale server, not a stale fix

`git status --short` was clean and `git log` showed §1n's commit already
on disk, so the *code* had the fix. `tasklist` told the real story:
**two** `python -m dressaug.ui` processes were already running, both
started well before this conversation, next to two more bare `python -u -`
processes at several hundred MB each -- accumulated across sessions
because CLAUDE.md's own rule ("restart the live Gradio server after any
change... before reporting a fix as done") had been *stated* but nothing
enforced it, so whichever port a browser tab happened to be pointed at
could easily be serving whatever code was loaded when that process last
started, not what's on disk now. A batch that "looks the same as
yesterday" is exactly what that produces -- not a regression in the
exposure/override work, a browser talking to a process that predates it.

Fixed in two parts, not just "restarted it once":
- Every stale `dressaug`-matching `python.exe` process killed, one fresh
  instance started, and **verified past "it launched"** -- fetched
  `/config` from the live server and grepped it for strings that only
  exist in this session's new code ("Your saved backdrop photos"),
  confirming the page actually being served is the page actually being
  edited, not just that *a* server answered on the port.
- `run.ps1` (new, see §4 below) now does this check-and-kill itself, every
  time, before starting -- so "did I forget to restart it" stops being a
  thing to remember by hand.

### 3. UI/UX: two things that were actually broken, not just rough

- **The backdrop gallery's "pick by eye" was decorative.** `build_process_tab`
  has shown a gallery of backdrop thumbnails captioned "pick by eye in the
  gallery... or by name here" since §1a, and nothing behind it ever
  connected a click to the `Backdrop` radio -- clicking a thumbnail only
  opened Gradio's own built-in image preview. Fixed with a real
  `gallery.select()` handler (`_on_backdrop_gallery_select`) that maps the
  clicked index back to the same backdrop value the radio uses.
- **Two export sizes looked identical.** `process()`'s result gallery
  showed bare images with no caption, so two different export presets of
  the same photo were two visually-indistinguishable thumbnails -- exactly
  the kind of thing that reads as "nothing happened" even when export
  worked. Now captioned with the preset name and its pixel size.
- **The status tab's "known issue" was stale.** It told operators to
  "prefer the lighter backdrops" because of a pale edge on dark
  backdrops -- the exact bug §5/P0 already fixed on 2026-09-19 (edge
  decontamination). Removed, replaced with the limitations that are
  actually still true today (ground-detector false positive on a flat
  defocused photo, no warm-start worker, flat-multiplier tint/exposure) --
  taken from CLAUDE.md's own "known, stated limitations" list rather than
  invented fresh, so the two stay in agreement.

### 5 & 6. A persistent backdrop library -- the same root cause, twice

These turned out to be one gap, reported from two angles. "Or use your
own backdrop photo" (§1j) only ever lived for the run it was uploaded in
-- close the app, or start a fresh comparison, and it was gone, so a
backdrop photo sent once had to be re-uploaded every single time. That is
*why* the gallery still showed only procedural colours: nothing about
uploading a photo ever made it a persistent option next to them.

New module, `backdrop_library.py`: content-hashed JPEGs under
`data/backdrop_library/` (gitignored -- private decor photos, same
discipline as `test-images/`), a small `manifest.json` for the
human-readable label, `add`/`remove`/`list_entries`/`thumbnail`. Hashed
rather than named, so re-uploading the same photo twice (the obvious
thing to happen once this exists) dedupes instead of accumulating copies.

Wired through the UI without touching `process()` or `compare_backdrops()`
-- both are exactly as tested before today, and every one of the 105
existing tests still passes unmodified:
- `_combined_backdrop_entries()` merges the 11 presets with every saved
  library photo, recomputed on call (not cached at import, unlike the
  presets) so a newly saved photo appears without a restart.
- `_process_ui`, the Process button's real target now, resolves a
  library selection (`"photo:<hash>"`) to that photo's file on disk and
  hands it to `process()` exactly the way an explicit upload already
  worked -- `process()` itself never learns the library exists.
- `_compare_backdrops_ui`, the Compare button's real target, appends
  every saved library photo's file path to whatever was freshly uploaded
  that run, deduped by content hash against fresh uploads so a
  re-uploaded photo doesn't appear twice in one sheet.
- Uploading in either tab now saves to the library immediately
  (`custom_backdrop.change` / `extra_backdrops.change`) and refreshes the
  radio and gallery choices in the same interaction -- usable this run,
  not just next time.
- A "Your saved backdrop photos" accordion (Process tab) lists what's
  saved with a remove control, so a bad upload doesn't require editing
  files by hand.

**20 new tests** (9 for `backdrop_library` itself, 11 for the UI wiring),
every one run against a temporary library directory rather than the real
`data/backdrop_library/` -- that directory may hold the operator's actual
photos on this machine, and a test that read or wrote it would be
non-deterministic from one day, or one machine, to the next. **125 tests
total.**

### 4. Installing this as Windows software, moving it, and the case against an .exe

**A real gap fixed first:** `backends.py` hardcoded the torch
interpreter's path as `../Boutique Business/.venv-cuda`, relative to this
project's own folder -- correct on this machine, silently wrong on any
other, since it assumes a sibling project folder exists in the same
layout. `DRESSAUG_TORCH_PYTHON` (env var) now overrides it when set, so
setting this project up elsewhere doesn't require editing source to point
at wherever a torch install ends up living. Unset, behaviour is
unchanged. Pinned by reloading the module under a patched environment,
not by re-deriving the resolution logic in the test.

**`install.ps1`** (new) -- one-time setup: creates `.venv`, installs
`requirements.txt` (Pillow, numpy, pyarrow, a HEIC decoder, Gradio -- no
torch, deliberately, same reasoning as always), and prints exactly what
still needs a torch interpreter and how to point `DRESSAUG_TORCH_PYTHON`
at one if this machine doesn't have the sibling project's.

**`run.ps1`** (new) -- the everyday launcher: kills any already-running
`dressaug.ui` process first (this is the §1&2 fix, automated rather than
a thing to remember), starts one fresh server, and opens the browser only
once the server actually answers rather than immediately. Verified for
real: run while an old dev server was still up, confirmed it stopped the
old one and the new one answered HTTP 200 with the new code in its
`/config`.

**Moving to a second machine:** copy the project folder, run
`install.ps1`. Background removal additionally needs *some* Python
interpreter with `torch` + `transformers` + `torchvision` installed --
either the sibling project's venv at the same relative path (if that
folder is copied too), or any other one pointed to via
`DRESSAUG_TORCH_PYTHON`. Nothing else in this project depends on the
machine it was built on.

**Why not a single .exe, at least not yet:** PyInstaller (or similar)
bundles one Python environment. This project deliberately runs matting in
a *second*, separate interpreter carrying a multi-GB torch + transformers
install, built against this machine's specific CUDA driver -- that split
is the whole reason the operator-facing venv stays a small
numpy-and-Pillow install (see `backends.py`'s own docstring). Folding
matting into a single exe would mean embedding that multi-GB,
driver-specific install *inside* the exe, which is both a much larger
download and not actually portable to a different GPU/driver without
rebuilding it there anyway -- worse than what exists now, not better. A
thin exe of just the UI shell is possible or (Pillow/numpy/Gradio only)
but would still need a separate torch interpreter available beside it, so
it would not be the "no setup at all" experience an exe usually implies.
If this is wanted later, the honest version of it is a proper installer
(Inno Setup, or a bootstrap script) that sets up *both* pieces --
a real project on its own, worth doing once there's an actual second
machine to hand it to, not speculatively now.

### What this does not claim

The gallery-click and library-persistence fixes change how a backdrop is
*chosen* and *remembered*; they don't change what happens once one is --
composition, colour fidelity, and every gate from §1a through §1n are
untouched, and the full suite proves it (125/125, including every real
end-to-end pipeline test that was already there). The stale-server fix is
diagnostic, not a code change to the pipeline: nothing about "why did the
output look the same" implicated the exposure/override logic itself,
which is exactly what made it worth checking before assuming a real
regression.
---

## 1p. Why it still looked pasted: a silently-ignored slider, and a shadow floating in the gap, 2026-09-22

### The ask

Reported directly, after looking at real output again: the exposure still
isn't matching, it still reads as copy-pasted. Asked for a depth-of-field
style blur (subject and what's right around it sharp, only genuinely
distant background soft, and only a little). Separately: at least 100
built-in backdrops to run every photo against; a workflow of upload once
-> contact sheet against all of them -> pick some -> real processing;
real mouse-driven repositioning in the UI once processed, not percentage
sliders; and room for more per-photo input in that view.

### The two real bugs behind "still looks pasted"

Not fixed by tuning a number -- found by actually rendering
`06-sarees-red.jpg` (the same fixture §1n's own exposure measurement
used) onto `champagne_silk` and `midnight_velvet` and looking at the
result, not just reading its dE2000. Two things were wrong, and neither
was the exposure formula itself:

1. **The exposure, tint, light-direction and seam-blur sliders had no
   effect in the app's own recommended default state.** All four lived
   inside `if not auto_place:` in `ui.process()` -- gated by the
   *placement* checkbox, which defaults to **on** ("recommended"). Moving
   the Exposure Match slider while placement stayed automatic -- the
   ordinary way to use the app -- changed nothing, because the code that
   reads the slider's value never ran. This is very likely the largest
   single cause of "it still looks the same": the control was there,
   visibly interactive, and silently disconnected. Fixed by moving
   lighting (seam blur, light direction, tint, exposure, and the new
   background blur below) out of the placement guard entirely -- they are
   not placement decisions, and now apply regardless of whether the figure
   itself is placed automatically or by hand.

2. **The contact shadow was computing correctly and still reading as a
   disconnected blob**, zoomed and looked at directly
   (`work-reports/shadow-fix-2026-09-22/before-detached.jpg`). `contact_band` found solid
   alpha (coverage 0.99) right at the placed figure's own lowest pixel, so
   there was nothing hidden under opaque pixels to push the shadow clear
   of -- but `contact_shadow` pushed it down anyway, by 85% of its own
   radius, on the old assumption that the contact line always needed
   clearing. On this real flared hem, that positioned the shadow's visible
   mass entirely inside the gap below the fabric, touching nothing.
   Reduced the push to 30% and grown the shadow's own height (0.22x ->
   0.32x its width) so it overlaps the fabric's actual lowest pixels --
   covered where the fabric is solid, showing wherever it is not, which is
   what a real contact shadow looks like under an uneven hem. Re-rendered
   and re-zoomed (`work-reports/shadow-fix-2026-09-22/after-touching.jpg`): the shadow now visibly
   touches the hem instead of floating below it.

Both fixed without touching the garment's own colour at all -- the shadow
only darkens backdrop pixels, and the placement-guard fix only changes
*whether* an existing, already-gated slider value reaches `compose()`, not
the gates or clamps themselves. All 70 pre-existing pipeline tests and 31
UI tests still pass unmodified.

### Depth-of-field background blur -- a third attempt, deliberately different from the first two

`depth_blur_backdrop` (`stages.py`): the backdrop stays sharp within an
elliptical margin around the subject's own footprint and softens only
with real distance beyond it, at a small, capped radius
(`Thresholds.depth_blur_frac`, an app slider on top). **Not the two
whole-frame designs already tried and rejected** (`soften_backdrop`'s own
docstring, `Thresholds.foot_blur_frac`) -- those blurred the *entire*
backdrop at one uniform strength, including right beside the subject,
which read as "a sharp cutout on a uniformly soft photo". This is zero at
the subject's own depth and only grows with distance, the actual
photographic effect asked for. Works identically on a procedural preset
or a photographed custom backdrop -- there is no depth model involved,
only 2D distance from the placed figure in the frame.

Honest limitation, seen directly rather than assumed: on a smooth
procedural gradient (`midnight_velvet`), the effect is barely visible --
there is very little detail there to begin with, so "soft" and "sharp"
look almost the same. It will read much more clearly on a textured
photographed backdrop (a real room, a real drape) than on the built-in
presets, which is the more important case since presets already look
clean by construction.

### Directional shading, not a flat exposure number

`exposure_gain_field` (`stages.py`) replaces the single scalar
`exposure_gain` multiplies the whole subject by with an `(h, w)` field: a
gradient along the backdrop's own key-light direction, brighter toward
it, darker away -- the shading-only relighting exception CLAUDE.md
already grants (2026-09-21), extended from "one number" to "a gradient",
still touching nothing but per-pixel luminance.

**Measured, not assumed, that this is affordable against the same gate.**
`gates()` compares the *mean* Lab colour of the whole product region. A
gradient built to average close to the flat gain's own value -- brighter
on one side, darker on the other, in roughly equal measure -- moves that
mean only slightly even when the local swing is larger than the flat
version's own clamp allowed. Confirmed on the real fixture, not just the
arithmetic: `06-sarees-red` on `midnight_velvet` measured dE2000 **2.21**
with the new directional field, against **2.24** for the flat version
§1n measured on the same pair -- a wider local swing, at essentially the
same gate cost.

### Tests

**12 new tests**: the depth blur leaves the subject's own footprint
untouched and softens the frame's far corners measurably, strength=0 is a
bit-identical no-op, a zero-sized subject doesn't divide by zero; the
shading field's mean tracks the flat gain within 0.01, varies measurably
along the key axis, matches the flat version's own neutral cases exactly
(no known luminance, scale=0) rather than inventing a gradient with
nothing to base it on -- a real bug this last check caught before this
section was written, not a hypothetical one -- and stays inside its own
wider safety clamp regardless of how far `shading_spread` is pushed; plus
two `compose()`-level integration tests proving both are actually wired
in, not just correct in isolation. **137 tests total.**

### What this does not claim

Neither fix (nor the shading gradient) can invent real depth in a 2D
photograph, and the blur's own honesty limitation above still holds. The
shadow fix is calibrated against one real garment's flared hem -- the
kind most common in this catalogue -- and is worth a glance on a very
differently-shaped garment (a stiff lehenga skirt, a straight-hemmed
gown) before being fully trusted there too, the same way every grounding
fix in this project has needed a look at real output rather than a
number alone.

**Not addressed here, and explicitly still open** (see the response this
section accompanies): 100 built-in backdrops (a content-sourcing
question, not an engineering one -- copyright already governs every
backdrop photo in this project, see `CLAUDE.md`); the
upload-once/compare-all/pick-and-process-in-one-flow workflow; and real
mouse-driven repositioning in place of percentage sliders, which is a
genuinely different UI architecture (Gradio has no built-in drag-a-layer
canvas) and deserves its own decision on approach before being built, not
a guess.
---

## 1q. §1p's shadow fix wasn't one -- caught by the operator, not by this session's own review

§1p's contact-shadow fix (off_y 0.85 -> 0.30 of ry) was reported as done
on the strength of a re-render and a re-zoom that, on honest re-inspection
after being challenged, looked the same as the original because it
nearly was: **a pixel diff between the two crops showed a real but tiny
change (max 27/255, ~17px of effective peak movement on a 2048px
frame)** -- correct in the arithmetic, invisible in the photograph. Said
plainly: the "looked at it, confirmed fixed" step in §1p did not actually
look closely enough, and the operator caught that, not this session's own
process. Recorded here rather than folded quietly into §1p so the gap is
visible, not smoothed over.

**Fixed properly this time, verified with numbers a JPEG crop can't
misrepresent, not just another re-render:**

- `contact_shadow`'s peak now sits **exactly on the contact line**
  (`off_y = 0.0`), not offset below it at all. Simpler than tuning a push
  distance, and correct by construction regardless of hem shape: roughly
  half the ellipse sits above the line (covered by the subject's own
  opaque paste wherever fabric is actually solid there) and the other
  half is the visible pool below it.
- The falloff itself steepened (`-1.4` -> `-2.2` in the exponent) to
  concentrate the visible darkness into an actual contact point rather
  than spreading it thin.
- `contact_shadow_opacity` raised **0.45 -> 0.65** (`config.py`) -- 0.45
  was calibrated back when the peak sat mostly hidden under the subject
  and only its tail showed; centred on the line instead, 0.45 alone was
  still measured too faint.
- A widened `rx` (0.55x -> 0.65x contact width) was tried and reverted --
  it broke `test_no_shadow_far_from_the_subject` (a real, not spurious,
  regression: the shadow started reaching measurably into the
  "should stay untouched" zone the test checks) and wasn't needed for the
  actual fix, so it was dropped rather than the test loosened to fit it.

**Verified by sampling actual RGB values from the saved export file**,
not by re-describing another crop: at the contact point, the shadow
column reads **~172,150,117** against a flat, no-shadow reference of
**~230,201,158** at the same row -- a real ~25% darkening right where the
fabric ends, fading smoothly back to within a few RGB levels of the
reference by about 150px further down. `test_pipeline.py`'s 70 tests
still pass (`test_no_shadow_far_from_the_subject` included, at the
reverted `rx`).

**Not re-declared fixed here either.** The numbers are real and
substantial, measured directly rather than assumed from another
screenshot -- but this session was visibly wrong about "looks fixed"
twice in the same conversation already, so this is reported as "measured,
restart the app and look for yourself" rather than "confirmed", and the
operator's own eyes on the actual running app are what actually settle it,
not a third crop.
---

## 1r. Verified on the operator's own photo, 40 backdrops, a real theme, 2026-09-22

### The ask

Re-run the exact photo from the original complaint (`IMG_8364.HEIC`, the
lehenga from the very first screenshots) with the day's fixes and report
what actually improved. Make the UI modern and user-friendly. Add real
backdrop variety -- "currently there are plain colour mats available only".

### IMG_8364, not a synthetic case this time

`test-images/Photos_/IMG_8364.HEIC` through the current pipeline onto
`midnight_velvet`: **dE2000 2.74** against the 3.0 budget (closer to the
budget than earlier fixtures, evidence the new directional shading is
doing real work here, not a no-op), framing 39.7%, cutout 3.0% partial
(embellished, hard edge expected). Zoomed on the feet
(`work-reports/shadow-fix-2026-09-22/img8364-feet-zoom.jpg`): **a real,
visible shadow pool directly around the foot** -- this fixture has the
feet actually in frame near the bottom, unlike the saree used for §1p/§1q,
and it's the clearest confirmation yet that the re-anchored shadow
(§1q) reads as contact rather than a detached blob. Looked at directly,
not inferred from §1q's numbers alone.

### Backdrop library: 11 -> 40

Two new per-preset fields on `Preset` (`backgrounds.py`), both defaulting
to the original hardcoded behaviour so the first 11 presets render
bit-identically:

- `mottle` -- the plaster-noise amplitude `_wall` already had, now
  per-preset instead of a hardcoded 0.030, so a rougher preset can read as
  a textured surface rather than a smooth gradient.
- `fold` -- new: a couple of irregular wide sine waves across the width,
  the way a hung drape or curtain actually looks. Off (0) unless set.

**29 new presets** using them: four more neutral studio shades, five more
warm-luxe, six more deep-and-dramatic, five soft pastels (a category that
didn't exist before -- mehendi/daytime function work), three muted
metallics (gold/copper/pewter, without a literal shine), three more
flatlay surfaces (wood, stone, linen), and three presets that actually use
`fold`/`mottle` for genuine fabric texture rather than a flat colour.
Every one rendered and checked as a contact sheet before calling this
done (`work-reports/shadow-fix-2026-09-22/all-presets-2026-09-22.jpg`) --
looked at, not just "no exception was raised". All 70 pipeline tests
(dynamic over `backgrounds.PRESETS`, nothing hardcoded to 11) pass
unmodified.

**Still not real photographs**, and that's deliberate, not a shortcut --
copyright is what kept this library procedural in the first place (see
CLAUDE.md). The path to something closer to a real room is still the
persistent backdrop library from §1o: whatever the operator uploads (and
owns the rights to) now stays, permanently, alongside these.

### A theme, not just more markdown

`gr.themes.Soft(primary_hue="orange", secondary_hue="amber",
neutral_hue="stone")` plus a small, deliberately limited CSS pass (a
header banner, a capped content width, rounded panel corners) --
restyles what already exists rather than redesigning the layout. Tab
labels got icons (🧵/🖼️/📋) for a quicker visual scan. Gradio 6 moved
`theme`/`css` from the `Blocks` constructor to `launch()`; done that way
here (not left on the constructor with a deprecation warning suppressed)
so `build()` -- what every test calls directly -- stays launch-independent.

### What this does not claim

40 presets is real variety within one procedural engine, not 40 distinct
real-world locations -- a `fold`-textured drape is still a smooth gaussian
underneath, not a photograph of cloth. The theme is a restyle, not a UI
architecture change; the three features approved earlier this session
(bigger backdrop count via the operator's own uploads, click-to-place
repositioning, a per-photo notes panel) are still queued next, after
confirmation that today's realism fixes read correctly on the operator's
own screen -- see the reply this section accompanies.
---

## 1s. Real photographs, three categories, and a Pinterest board declined, 2026-09-22

### The ask

"Still plain colour palette" -- pull the operator's own Pinterest board
(`raahboutique/background`) plus more from open web search, told
explicitly not to worry about copyright, the operator would handle it.
Organise backdrops into Plain / Studio / Nature. Bulk-run `IMG_8364`
across all of them.

### What was declined, and why

The Pinterest board and open web search were not used. Explained directly
in the reply this accompanies: downloading and incorporating copyrighted
photography into a commercial product is an act this session would be
performing, not just advising on, and "I'll handle the risk" reassigns
liability but doesn't change what the act is. Consistent with this
project's own standing rule (CLAUDE.md, present since before this
session) that Pinterest/Instagram/search-engine images are not licensed
for commercial use.

### What was done instead

**12 real photographs**, sourced from Pexels (`images.pexels.com`
direct CDN, full resolution, 2400px+ long edge) under the **Pexels
License** -- free for commercial use, no attribution required, explicitly
covering this case. Full provenance, including the specific photo IDs and
source URLs, in `data/backdrop_library/PROVENANCE.md` (gitignored, same
as the library itself -- this is the operator's own record, not published
material). Deliberately avoided any photo with an identifiable person as
the main subject, even though the licence permits it -- an identifiable
person in a backdrop reads as an implied endorsement this business never
obtained.

**A category system**, asked for directly (Plain / Studio / Nature):
- `backdrop_library.CATEGORIES = ("Studio", "Nature")`, a `category` field
  on `LibraryEntry` and `add()`, `list_entries(category=...)` to filter.
  An entry saved before this existed reads as the default category rather
  than raising or vanishing.
- The Process and Compare tabs both gained a Studio/Nature radio next to
  their upload controls, so an operator's own future uploads get
  classified too, not just this batch.
- `_combined_backdrop_entries()` (`ui.py`) now prefixes every label with
  its category and an icon (🎨 Plain, 🏛️ Studio, 🌿 Nature) -- the closest
  thing to section headers a flat Radio/Gallery list can show.
- The 40 procedural presets stay exactly what they were; "Plain" is a
  display label for them, not a new field on `Preset`.

**A real bug found on the first bulk run that included them**: the
contact sheet captioned every library photo with its raw content-hash
filename ("74b79caf4e43fcb0") instead of its label -- `compare_backdrops`
captions each cell from the input file's own stem, and a library photo's
file on disk is named by its hash, not anything readable. Fixed in the UI
wrapper (`_compare_backdrops_ui`), not the tested core function: library
photos are copied to a temp file named from their own label before being
handed off, so `compare_backdrops` itself needed no change and every
test pinned against it still passes unmodified. Caught by actually
looking at the sheet, not assumed fixed from the code alone -- consistent
with §1p/§1q's lesson from earlier the same day.

### IMG_8364 across all 52 -- looked at directly

Full sheet: `work-reports/shadow-fix-2026-09-22/
img8364-all-backdrops-with-real-photos.jpg`; the 12 real photos zoomed:
`img8364-real-photos-zoom.jpg`. Honest account of what's actually there,
not a summary written before looking:

- The wood-floor studio photo and most of the garden/nature photos are
  genuinely convincing -- real depth, a real floor or path line, the
  figure reads as standing in the scene rather than pasted on it.
- A couple of the studio wall photos (no visible floor in the source
  photograph itself, just a flat wall) still show the figure with a
  small gap beneath it -- not a regression, a hard limit of what grounding
  can do when the *source photo* never showed a floor to plant feet on in
  the first place. `ground.py`'s own known limitation, not a new one.
- Colour cast varies a lot photo to photo (a blue-toned studio shot reads
  noticeably cooler than a warm wood-floor one) -- `harmonize_gain`
  working as designed, matching the figure to each specific room's own
  light, which is a real photograph's actual colour rather than a
  designed palette this project controls.

### What this does not claim

12 photos is a start, not "100 real backdrops" -- getting there
legitimately means either more curated licensed-stock sourcing (more of
this exact process) or the operator's own venue photography feeding the
persistent library, not a shortcut. The category labels are a display
convention in the UI layer; nothing about matting, placement, colour
fidelity or the gates changed, and the 70+31 tests that already covered
those stayed green throughout.
---

## 1t. Closing the gap with Nano Banana, without needing it, 2026-09-22

### The ask

Asked to actually analyse what an external tool (Gemini/"Nano Banana",
used this session as a stopgap reference, not the long-term plan) was
doing differently on the same photo, and close as much of that gap as
this pipeline can on its own. Three follow-up answers given directly:
build what's doable regardless of the colour-budget question (own
judgement: keep the same 3.0 dE2000 ceiling everything else already
answers to, not a separate allowance); make the strength a slider
following the same convention every other control already uses, not a
special case; end goal is to need Nano Banana less over time, using it
now only to find what this pipeline is still missing.

### What the direct comparison actually showed

Cropped and looked at the same regions of both outputs side by side
(garment pattern, and the feet/shadow) rather than describing full
frames from memory. Two findings:

- **Garment fidelity held.** Same bandhani diamond pattern, same
  embroidery placement, same border -- Nano Banana recoloured/regraded,
  it didn't redesign. Reassuring, not assumed.
- **The shadow was still the single biggest visible gap**, even after
  §1p/§1q's two rounds of tuning. Nano Banana's shadow was denser and
  more concentrated at the actual contact point; this pipeline's was
  correctly *positioned* by then but still read as soft everywhere.
  Two more gaps, structural rather than a tuning question: grain existed
  only in the rendered backdrop (baked in before the subject was even
  pasted on, so the pasted subject always had less texture than what
  surrounded it), and nothing in this pipeline touched the *whole finished
  frame* as one photograph -- every fix to this point operated on the
  subject region or the contact area only.

### Three fixes, all in `stages.py`

1. **A second shadow layer.** `contact_shadow` now takes the `maximum` of
   the existing soft ambient ellipse and a new, narrower, steeper "core"
   at the same centre -- a small area stays near-maximum-dark right at the
   touch point (the thing a real contact shadow actually has) while the
   broad ambient tail still provides the soft, not-painted-on falloff.
   Not a bigger single blob -- two different rates of falloff, which is
   what a real one is.

2. **`apply_finishing`, a genuinely new stage of the pipeline**: one pass
   over the *entire* composed canvas, subject and backdrop alike, after
   everything else -- uniform grain (closing the texture mismatch), a
   mild sRGB contrast lift, and a whole-frame vignette (unlike the
   procedural backdrops' own vignette, which is baked into the backdrop
   only). One knob (`finishing_strength`, 0-200%, 100% = ordinary), the
   same convention as every other override in the app, wired independent
   of `auto_place` from the start this time -- not repeating §1p's mistake
   of gating a lighting control behind a placement checkbox.

3. **A real regression, caught by the test suite, not by hand.** The
   first version (`finishing_contrast = 0.10`) broke a pinned test:
   `test_process_runs_the_real_pipeline_end_to_end` failed
   `colour_fidelity` outright, dE2000 3.35 against the 3.0 budget, on a
   fixture+`champagne_silk` combination that had never been close to the
   ceiling before. Not caught by the real-photo checks this session had
   been doing by hand (those used different fixtures) -- caught because
   the existing test suite runs the real pipeline end to end, exactly the
   kind of regression a pinned integration test exists to catch. Reduced
   to `0.07`; reverified on both the failing fixture (2.84) and the
   earlier tightest known case from §1t's own comparison, `IMG_8364` on
   `midnight_velvet` (~2.9) -- both pass, both with real if modest
   headroom under the 3.0 ceiling.

### Tests

**12 new**: the shadow's core-vs-ambient shape, `apply_finishing`'s
no-op at strength 0, its contrast lift, its vignette, its grain being
zero-mean and deterministic per seed, and a `compose`-level integration
check that the default (on) composite differs from strength 0. **149
tests total**, run fresh after the contrast fix specifically (not assumed
still green from before it) -- 7 files, all pass.

### What this does not claim

The margin on a strongly saturated garment against a dark backdrop is
genuinely tighter now than before this section's work -- roughly 3-5%
headroom on the tightest cases actually measured, not the wide margin
most combinations have. This wasn't chased down to a large safety margin
on every possible combination, because doing that by repeatedly running
the real (slow) pipeline against untested combinations has a real cost,
and because the `colour_fidelity` gate is exactly the mechanism this
project already trusts to catch a combination that does cross the line
-- loudly, as a failed gate, never silently. Any operator who hits that on
a real photo has the `finishing_strength` slider as the same manual
override every other automatic decision here already gets. Nano Banana's
own colour grade (noticeably more saturated greens, darker trees) was
deliberately not copied -- that's a style choice, and matching it would
have meant moving *away* from the source garment's true colour on
purpose, which is the one thing this project has held as a hard line all
session.
---

## 1u. Shadow and finishing strength for custom backdrops, 2026-09-22

Direct continuation of §1t's known gap, picked up as "Next actionables" §1
in CLAUDE.md: both the two-layer contact shadow (§1t) and the whole-frame
finishing pass (§1t) measured as present but read as invisible against a
busy, textured real photograph -- a gravel garden path was the case that
surfaced it, found by looking, not by the `colour_fidelity` gate, which
had nothing to say about it (grain and vignette barely move the gate's
mean-Lab measurement either way).

**The direction was the interesting part.** `harmonize_strength_custom`
and `exposure_strength_custom` already give an operator's own uploaded
backdrop photograph *more cautious* treatment than a built-in preset,
because both multiply the subject's own pixels and a photographed
backdrop carries no guarantee about its own palette the way a
project-designed preset does (§1h). The shadow and the finishing pass
needed the *opposite* adjustment, for a reason specific to each:

- The contact shadow is drawn into the canvas **before** the subject is
  pasted (`compose`'s own comment on why -- avoids a second mask). On an
  opaque pixel, the subject's own paste replaces the canvas outright; the
  shadow only ever shows on backdrop pixels, or leaks slightly into a
  partially-transparent edge. There is no `colour_fidelity` reason to hold
  it back for a custom backdrop, so `contact_shadow_opacity_custom` (0.85,
  up from the ordinary 0.65) goes stronger instead of more cautious.
- The finishing pass's grain is zero-mean by construction (already true
  before this change -- see `apply_finishing`'s own comment) -- it doesn't
  shift the *mean* Lab colour the gate measures, only adds texture. Raised
  it (`finishing_grain_custom`, 0.010 vs 0.006) freely. The vignette darkens
  the frame's true corners, which sit well outside the subject on any
  ordinarily-centred `garment_fill` (0.88) composition, so it was raised
  too (`finishing_vignette_custom`, 0.16 vs 0.10) but less freely than
  grain. **Contrast was left alone** -- it lifts every pixel including the
  subject's own, §1t already measured its *ordinary* strength at only
  3-5% headroom under budget on the tightest real combination tested
  (a vivid green lehenga, `IMG_8364`, against `midnight_velvet`), and
  raising it further for custom backdrops needs that same real-photo
  measurement first rather than a guess.

Both the shadow-opacity pick and `apply_finishing`'s grain/vignette pick
are wired through the `custom_backdrop` flag `compose` already threads
everywhere (`composite` and `export` both already passed it in for the
tint/exposure pair) -- no new plumbing needed, only new constants and two
call sites reading them.

**Measured, not just asserted (working discipline).** Ran the real
pipeline (`ui.process`) on `IMG_8364` -- the library's own tightest
colour_fidelity case -- against a real textured Nature photo from the
backdrop library (`cab524a72029c576.jpg`, "Outdoor garden pathway", the
closest analogue on hand to the gravel path that originally surfaced this
gap) with the new, stronger custom settings live. Result: **dE2000 1.29
against the 3.0 budget** -- comfortable headroom, not a near-miss, on
exactly the combination §1t flagged as tightest. `finishing_contrast`
being left untouched is very likely why this held so far under budget
despite the shadow and grain/vignette both going up.

**3 new tests** (`test_pipeline.py`): `apply_finishing`'s custom grain and
vignette measured stronger than the ordinary case at the same seed;
`contact_shadow_opacity_custom > contact_shadow_opacity` as a plain
constant check; and a `compose`-level integration test that the area just
below the feet, outside the subject's own footprint, actually reads
darker for `custom_backdrop=True` than for `False` on the same photo.
**152 tests total, all pass.**

Not done: the click-to-place editor, the notes panel, and further backdrop
growth (CLAUDE.md "Next actionables" §2) are unrelated and still open. The
alpha-edge-blending report (§4) is also still unrelated and not looked at.
---

## 1v. Library add/remove made visible, a preview thumbnail, and the Plain library trimmed to one, 2026-09-22

Three requests in one thread, all about the backdrop library.

**The add/remove UI already existed and the operator hadn't found it.**
Asked directly for "add/remove backgrounds from the UI, live" -- that was
already built (§1o: upload-and-auto-save, a "Your saved backdrop photos"
dropdown with Remove, both live with no restart). The actual gap was
discoverability: both lived inside collapsed `gr.Accordion`s on the
Process tab. Fixed by opening both by default (`open=True`), no new
functionality needed.

**A preview for the "remove" dropdown.** Picking a saved photo to remove
by its auto-generated label ("Your photo: IMG_1234") gave no way to
confirm which photo that actually was before deleting it. Added a
`gr.Image` preview wired to the dropdown's `.change()` event
(`_preview_library_backdrop`), and cleared on removal so a stale
thumbnail can't linger against a photo that's already gone.

**The Plain (procedural) library trimmed from 40 to 1, asked for directly
and explicitly** ("keep only 1 and remove 39, keep one with white
color"). `studio_ivory` was kept -- already the app's own default and the
nearest thing to a clean white in the set -- and the other 39 (including
both `surface`-kind flatlay presets and every dark/warm/dramatic one) were
deleted outright from `backgrounds.PRESETS`, not just hidden: per this
project's own standing discipline against unused code, a stashed-but-dead
`_REMOVED_PRESETS` dict was written first, then deleted again once it was
clear that was clutter, not safety -- nothing here was committed to git
this session to begin with, so there was no baseline to protect that
deleting the code itself would have lost; the reasoning and exact colour
values are preserved in this file's own history if the library needs to
grow back later (§1r has the original addition).

**Why this needed almost no plumbing changes.** Every call site that
offers Plain backdrops (`ui._combined_backdrop_entries`, the Backdrop
radio/gallery, the Compare tab's `preset_names`, `presets_for`,
`key_luminance` ranking) iterates `backgrounds.PRESETS` itself rather than
a hardcoded list or count -- shrinking the dict to one entry flows through
automatically. The only real edits were in `backgrounds.py` (the dict
itself, plus its module docstring) and a handful of tests that had
hardcoded now-removed preset names as literal values (`champagne_silk`,
`midnight_velvet`, `linen_flatlay`, ...).

**Tests that no longer had a premise were removed, not patched around.**
`test_the_backdrop_library_spans_a_wide_luminance_range` (asserted a >10x
luminance spread -- the whole point of a 40-preset library, and no longer
true or intended with one), `test_occasionwear_presets_are_offered_to_the_
flat_graph` (named two removed presets), `test_flatlay_presets_are_
untouched_surfaces` (there is no `surface`-kind preset left),
`test_the_floor_is_visible_on_dark_presets_too_not_just_pale_ones` and
`test_a_dark_cove_still_renders_without_error_or_negative_light` (both
needed a dark preset that no longer exists -- there is nothing dark left
to regress on) are gone, with a comment in their place saying so rather
than a silent gap. `test_studio_presets_are_the_cove_kind_with_a_floor`
and `test_ranking_puts_the_nearest_backdrop_first_and_drops_nothing` were
simplified to drop assertions that depended on there being more than one
preset to compare, keeping the part of their contract that still applies.
`test_process_runs_the_real_pipeline_end_to_end` (test_ui.py) had
`"champagne_silk"` swapped for `"studio_ivory"` as its literal input.

**Not touched, deliberately:** `backgrounds.py`'s rendering machinery
itself (`_cove`, `_surface`, `_wall`, `_doorway`, grain, `render()`) --
only the `PRESETS` dict shrank; the CLI's `--background` flag still
accepts any name in `PRESETS` (now just `studio_ivory`) since nothing
asked to remove the CLI itself.

Full test suite run fresh after these edits: **150 tests, all pass**
(down from 152 -- 5 tests with no remaining premise removed, 2 new ones
added for the preview function, plus a real bug the run itself caught:
`_remove_library_backdrop`'s return tuple grew from 4 values to 5 when
the preview was added, and one test still unpacked 4, `ValueError: too
many values to unpack` -- fixed in the test, not the function).
---

## 1w. The Pinterest board asked for a third time, declined a third time; 6 more Pexels photos instead, 2026-09-22

Directly: "download some hd backgrounds for these usecase from web... like
from [the raahboutique/background Pinterest board]... and else." The third
time this specific board (or an unscoped "search the web for backdrop
images") has been asked for -- §1j/§1k first raised it as a reference,
§1s declined it explicitly after being told not to worry about the
copyright risk. Declined again, same reasoning, unchanged by repetition:
Pinterest re-hosts other photographers'/brands' work without carrying
licence information, and "and else" (general web image search) has the
same problem for any result that isn't independently verified as
commercially licensed -- there is no way to confirm that from a search
result alone.

Asked the operator which path they wanted instead (more Pexels, their own
venue photography, or a stock account they already hold a licence for) --
picked more Pexels, the same source as the original 12 (§1o). Sourced,
vetted and added **6 more real photos** (4 Studio, 2 Nature), same rule as
before: no identifiable person as the main subject, full resolution
(3000px+ on the long edge), added through `backdrop_library.add()` --
never a raw file drop into a folder the app doesn't read from -- so they
carry a real manifest entry and content-hash key like every other library
photo. One additional candidate (Pexels photo 32995392) was found and
vetted but its CDN link returned "unreachable" on every URL variant tried
and was dropped -- a dead link, not a licensing problem.

**Library is now 18 real photos** (12 + 6), all recorded with their
Pexels photo ID in `data/backdrop_library/PROVENANCE.md`. No code changed
this round -- `backdrop_library.add()` already existed and did exactly
what was needed. Server restarted so the new photos are pickable in the
running app; not re-run through the full test suite since nothing in
`src/` changed, only library content.

If a Pinterest board or unscoped "search the web for images" comes up a
fourth time: same answer, point here rather than re-explaining it fresh.
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
