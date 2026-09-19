# 01 — Datasets: what was searched, what was rejected, and why

Written 2026-09-11, after a search for training and development images of
**women's occasionwear** — gowns, party dresses, lehengas, sarees.

**Headline: no public dataset matches the requirement.** Ten candidates were
checked. Two were downloaded and inspected rather than judged from their
dataset cards. This file exists so nobody repeats the search, and so the
reason for what is on disk is written down rather than assumed.

---

## 1.1 The requirement

For phases 1-4 the pipeline needs garment images that resemble what the shop
will actually photograph: a dress, whole, at a resolution where lace and
beading survive. For phase 6 it needs the same garment both flat and on a
body, paired.

Three properties matter, in this order:

1. **Subject** — women's occasionwear, not casual separates, not menswear.
2. **Resolution** — enough that a lace hem is more than a suggestion.
3. **Licence** — clear enough to say whether an image may inform a commercial
   catalogue, which is the same discipline the sibling project applies in its
   `docs/08-licensing-and-compliance.md`.

---

## 1.2 What was checked

| Dataset | Verdict |
|---|---|
| `detection-datasets/fashionpedia` | **Downloaded and inspected.** CC-BY-4.0, the only clean licence found. Street-style and runway photographs of *people*, mostly casual, mixed men and women, several visibly watermarked with photographer credits. This mirror carries **bounding boxes only, no masks**. Wrong subject, and no segmentation worth having |
| `ares1123/vto_dress_train_data` | **Downloaded and inspected.** VITON-style **paired** data — a model wearing the garment plus the same garment as a flat cutout on white. The structure is exactly right for phases 1-4 and 6. The content is tops and casual separates at 512×512; the captions say so ("a woman in a white tank top and blue jeans"). No licence declared |
| `JianhaoZeng/Dresscode` | Right content — DressCode has a dedicated *dresses* split at 1024×768, paired, with masks. **74 GB in two concatenated parts**, and the upstream dataset is research-only with an academic agreement. Not practical here and not licence-clean |
| `ashraq/fashion-product-images-small` | 44k product shots, but "small" means thumbnails. Useless for matting. No licence declared |
| `ceyda/fashion-products-small` | Same shape, same problem |
| `zalando-datasets/fashion_mnist` | 28×28 greyscale. Included only to say it was considered and is not remotely applicable |
| `SaffalPoosh/deepFashion-with-masks`, `lirus18/deepfashion*` | DeepFashion derivatives. Masks are genuinely useful, but DeepFashion's upstream terms are research-only and these mirrors do not change that |
| `TryOnVirtual/VITON-HD-TEST`, `forgeml/viton_hd`, `SaffalPoosh/HR-VITON` | Try-on datasets, upper-body focused, research licences |
| `harshiitsingh/flipkart-scraped-dresses-10` | Scraped retail images. The copyright is the retailer's and the brand's; scraping does not transfer it. 0.1 MB, and no licence declared |
| `Bilalbk/womenDressImg2Img` | Closest by name. 4 downloads, unvetted, no card |

Searches run: `dress`, `gown`, `party dress`, `evening`, `bridal`,
`occasionwear`, `women dress`, `viton`, `deepfashion`, `clothing-segmentation`.
`gown`, `bridal` and `occasionwear` returned essentially nothing.

---

## 1.3 What is on disk, and what it is honest for

`data/raw/` holds two files, both gitignored:

- `fashionpedia-val.parquet` — 85 MB, kept as the licence-clean reference even
  though its subject is wrong.
- `vto-dress-0000.parquet` — 488 MB, one shard, 1,456 paired rows.

`data/fixtures/` holds 60 pairs cut from the second, with a `PROVENANCE.json`
next to them stating in the file itself that they are **not occasionwear**.

**Honest for:** developing the algorithms. Matting a garment off a background,
compositing it onto a new one and recolouring it are the same operations
whatever the garment is, and a bug in any of them shows up on a t-shirt.

**Not honest for:** tuning a single threshold. Every number this project
deviates from the sibling on is driven by transparency and scale — a chiffon
gown at 3000 px behaves nothing like a cotton top at 512 px. Tuning
`alpha_solid` or `min_partial_alpha_on_sheer` against these fixtures would
produce numbers that look measured and are not.

**Never:** published. Nothing from either dataset may reach a listing.

---

## 1.4 The recommendation

**Photograph 20-30 real garments from stock.** That is what unblocks phases
3 and 4, and it is the same conclusion the sibling project reached about its
wrist plate: one real photograph beat every clever way of avoiding taking one.

A useful set would cover the failure modes rather than the easy cases:

- a plain opaque dress — the baseline that must stay good
- a chiffon or georgette gown — the transparency case the thresholds exist for
- a net or tulle skirt — the hardest matte in the catalogue
- a heavily sequinned lehenga — specular, high-frequency
- a shot-silk or ombre piece — phase 4's whole reason to exist
- one photographed against a dark surface, and one against a light one

Shoot them the way the sibling's README asks: flat or on a hanger, plain
background, soft daylight, and sent as files rather than through a messaging
app that re-encodes them.

---

## 1.5 On training a model

Nothing here trains anything, and nothing needs to yet.

The honest case for training, when it comes, is **phase 1**: a general
salient-object model like BiRefNet is very good at "the obvious subject" and
has no particular idea about net, tulle or lace, which is where this catalogue
is hardest. A garment-specific matting model fine-tuned on real occasionwear
would beat it there.

That is a real project, and it should start when there are real garment
photographs to train and validate against — not before, and not on casual tops
at 512 px, which would teach a model the wrong thing very efficiently.

---

## 1.6 Update, 2026-09-19 — real Indian ethnic wear found, on a narrower search

The 2026-09-11 search above was for *women's occasionwear generally*
("dress", "gown", "party dress", "evening", "bridal"). A different, narrower
search — for *Indian ethnic wear specifically* — found something usable that
the first search's terms never surfaced, because "saree" and "kurta" are not
"dress" or "gown" in English-language dataset naming.

**`benitomartin/fashion-product-images-small-900x1200`** — a full-resolution
re-upload of Param Aggarwal's Fashion Product Images Dataset (the well-known
Kaggle dataset scraped from Myntra listings; the HF name is misleading, it is
"small" only relative to an even larger original). 44,072 rows, 900×1200,
genuine product photography, women's items labelled by `articleType`
(Sarees, Kurtas, Kurta Sets, Kurtis, Dupatta) with `gender` filterable.

**One shard (of 14) was downloaded and 60 women's ethnic-wear photographs
extracted** — 22 sarees, 14 kurtis, 11 kurta sets, 8 kurtas, 5 dupattas, all
genuinely worn by a model against a studio background. This is what
`TASK.md §1b`'s person-preservation and full-pipeline testing ran against.

**Licence is the same caveat as everything else here.** The uploader marks
the compiled dataset CC0; the photographs are Myntra / brand retail product
photography, and CC0 on a compilation is not the same claim as CC0 on the
copyright in each photo. `data/ethnic-fixtures/PROVENANCE.json` states this
in the fixtures' own directory. **Local testing and development only —
never published, never redistributed**, same as every dataset in this file.

**What this does not close.** This shard had zero lehengas and zero gowns —
the categories this project's `Garment` enum names as `LEHENGA` and `GOWN`
remain genuinely untested against real photographs. `articleType` in the
full dataset does include a `Lehenga Choli` category (one row was seen in an
earlier, smaller sample); a later shard would likely surface more, if that
gap needs closing before the shop's own photographs arrive.
