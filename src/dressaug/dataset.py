"""Development fixtures cut from public datasets.

**Read this before trusting anything cut from here.**

The catalogue this pipeline is being built for is *women's occasionwear* —
gowns, party dresses, lehengas, sarees. Ten public datasets were searched on
2026-09-11 and **none of them is that.** What was found, and why each was
rejected, is recorded in `docs/01-datasets.md` so nobody repeats the search.

Two were downloaded and inspected rather than judged from their cards:

* **`detection-datasets/fashionpedia`** (CC-BY-4.0, 85 MB val split) —
  street-style and runway photographs of people, mostly casual, mixed men and
  women, several visibly watermarked, and this mirror carries **bounding
  boxes only, no masks**. Wrong subject and no supervision worth having.
* **`ares1123/vto_dress_train_data`** (488 MB shard, 1,456 rows) — VITON-style
  **paired** data: a model wearing the garment, and the same garment as a flat
  cutout on white. The *structure* is exactly what phases 1-4 and 6 need. The
  *content* is tops and casual separates at 512x512, and the captions say so
  ("a woman in a white tank top and blue jeans").

So this module cuts fixtures from the second one and labels them for what
they are. They are honest for developing the **algorithms** — matting a
garment off a background, compositing it onto a new one and recolouring it
are the same operations whatever the garment is — and dishonest for tuning
any **threshold**, because a t-shirt at 512px is not a chiffon gown at 3000px
and the numbers that matter here are the ones transparency and scale drive.

The real input is the shop's own photography, exactly as it was for the
sibling jewellery project. A public dataset is scaffolding, never the product.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image

from .config import DATA_DIR

#: Where fixtures land. Gitignored — they are regenerable from the parquet
#: and they are not ours to redistribute.
FIXTURES = DATA_DIR / "fixtures"

#: The shard this cuts from, and what it actually contains.
VTO_SHARD = DATA_DIR / "raw" / "vto-dress-0000.parquet"

#: Honest provenance, written next to the fixtures so a later reader does not
#: have to come back to this docstring.
PROVENANCE = {
    "source": "huggingface.co/datasets/ares1123/vto_dress_train_data",
    "shard": "data/0000.parquet",
    "downloaded": "2026-09-11",
    "licence": "NOT DECLARED upstream — treat as development-only",
    "content": "women's casual tops and separates, 512x512, VITON-style pairs",
    "is_occasionwear": False,
    "use": "algorithm development only; do not tune thresholds on this and "
           "do not publish any image from it",
}


def cut_fixtures(limit: int = 60, *, flat_only: bool = True) -> Path:
    """Write `limit` fixtures out of the shard as PNGs, plus provenance.

    `flat_only` takes the `conditioning_image` column — the garment as a flat
    cutout on white, which is the shape a shop's own product photograph will
    be. The worn image is kept too when `flat_only` is False, because phase 6
    needs pairs and there is no point re-reading a 488 MB file later to get
    them.
    """
    import pyarrow.parquet as pq

    if not VTO_SHARD.exists():
        raise FileNotFoundError(
            f"{VTO_SHARD} is missing. See docs/01-datasets.md for the download "
            "command — the shard is deliberately not committed."
        )

    FIXTURES.mkdir(parents=True, exist_ok=True)
    table = pq.read_table(VTO_SHARD)
    flats = table.column("conditioning_image").to_pylist()
    worns = table.column("image").to_pylist()
    texts = table.column("text").to_pylist()

    written = []
    for i in range(min(limit, len(flats))):
        flat = Image.open(io.BytesIO(flats[i]["bytes"])).convert("RGB")
        flat.save(FIXTURES / f"{i:04d}-flat.png")
        entry = {"index": i, "flat": f"{i:04d}-flat.png",
                 "caption": (texts[i] or "").strip()}
        if not flat_only:
            worn = Image.open(io.BytesIO(worns[i]["bytes"])).convert("RGB")
            worn.save(FIXTURES / f"{i:04d}-worn.png")
            entry["worn"] = f"{i:04d}-worn.png"
        written.append(entry)

    (FIXTURES / "PROVENANCE.json").write_text(
        json.dumps({**PROVENANCE, "count": len(written), "items": written}, indent=2),
        encoding="utf-8",
    )
    return FIXTURES


def fixture_paths() -> list[Path]:
    """Every flat fixture on disk, sorted. Empty if none have been cut."""
    if not FIXTURES.exists():
        return []
    return sorted(FIXTURES.glob("*-flat.png"))
