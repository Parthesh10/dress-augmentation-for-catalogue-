"""Where can a person stand in this photograph? Ground detection for a
custom backdrop -- a floor line, and a usable/unusable call.

Only ever run on an operator-supplied backdrop photograph. Never on the
garment: this reads the *scene* the subject is about to be placed into and
touches nothing about the subject itself.

**Why a segmentation model and not an edge detector.** The first attempt
at this (TASK.md §1k) was a plain heuristic -- the strongest roughly
horizontal edge in the lower part of the frame -- and it was rejected after
being run against 33 real photographs: it found *a* line in nearly all of
them, including an abstract painting, a sea horizon and a macro flower
close-up, with no way on pixels alone to tell those from a real floor. The
question "is this a floor?" is a question about what things *are*, and
that needs a model that knows what a floor, a lawn, a rug, a sky and a
table are. ADE20K scene parsing has all of those as named classes; a
SegFormer trained on it answers the question directly.

**Verified against a known answer before being trusted, not tuned until
it looked plausible.** All 33 photographs had a by-eye floor line and a
usable/unusable call recorded *before* the model ran (§1k). Against that:
every one of the 6 hand-excluded backdrops separates out automatically on
the rules in `judge()`; floor lines land within ~0.05 of the by-eye calls
on the large majority of the rest; and in one case (a pavement strip under
an ivy wall) it found a real floor the by-eye pass had missed. One known
residual: an abstract painting that fills the frame flatly is "wall" to
the model, indistinguishable from a real plain wall -- that one still
needs a human glance. Everything else on that board it gets right.

**"No floor" is not "unusable."** A drape, a curtain, an ivy wall have no
floor in them and are perfectly good backdrops -- the subject stands in
front of them at the ordinary default placement. Only a scene that is
mostly sky or water, or at table height, is refused. This distinction
came straight out of the 33: three of the best drape backdrops on the
board came back with 0% ground.

Same subprocess pattern as `backends.py`, for the same reason: this
project's own venv deliberately has no torch. Runs in the shared CUDA
interpreter when present, with the same automatic CPU fallback. Results
are cached in-process by image content, because a backdrop is detected
once and reused across every garment composited onto it -- that reuse is
the whole reason a 500-photo batch needs 30 detections, not 500.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .backends import INTERPRETER
from .config import THRESHOLDS

MODEL_ID = "nvidia/segformer-b2-finetuned-ade-512-512"
MODEL_REVISION = "de01bae28967510f9ddd496c60a969357195400c"

#: Placeholders substituted at write time, as in `backends._WORKER`. The
#: class sets are built by *name* from the model's own `id2label` inside the
#: worker rather than as hardcoded ids here, so the model's config is the
#: single source of truth for what "floor" means and a revision change that
#: renumbered classes would surface as a name mismatch, not a silent
#: misclassification.
_WORKER = r'''
import sys, json, numpy as np
from PIL import Image
import torch
from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor

src, row_cov, search_from = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
dev = "cuda" if torch.cuda.is_available() else "cpu"
proc = SegformerImageProcessor.from_pretrained("__MODEL_ID__", revision="__MODEL_REVISION__")
model = SegformerForSemanticSegmentation.from_pretrained(
    "__MODEL_ID__", revision="__MODEL_REVISION__").eval()

GROUND = {"floor", "road", "grass", "sidewalk", "earth", "rug", "field", "sand",
          "path", "stairs", "runway", "stairway", "dirt track", "land", "stage", "step"}
SKY_WATER = {"sky", "water", "sea", "river", "lake", "waterfall"}
FURNITURE = {"table", "chair", "armchair", "seat", "sofa", "pool table",
             "coffee table", "kitchen island", "desk", "bench"}
GRAPHIC = {"signboard", "poster", "bulletin board", "screen", "crt screen",
           "television receiver", "computer", "monitor", "billboard"}

def ids_for(names):
    out = set()
    for i, label in model.config.id2label.items():
        # ADE20K labels are "floor, flooring" style -- match on the first term
        if label.split(",")[0].strip().lower() in names:
            out.add(int(i))
    return out

ground_ids, sw_ids, furn_ids, gfx_ids = (
    ids_for(GROUND), ids_for(SKY_WATER), ids_for(FURNITURE), ids_for(GRAPHIC))

im = Image.open(src).convert("RGB")
def run(device):
    m = model.to(device)
    inputs = proc(images=im, return_tensors="pt").to(device)
    with torch.no_grad():
        logits = m(**inputs).logits
    up = torch.nn.functional.interpolate(
        logits, size=im.size[::-1], mode="bilinear", align_corners=False)
    return up.argmax(1)[0].cpu().numpy()

used = dev
try:
    seg = run(dev)
except RuntimeError as exc:
    if dev == "cuda" and "out of memory" in str(exc).lower():
        torch.cuda.empty_cache()
        used = "cpu (fallback after CUDA OOM)"
        seg = run("cpu")
    else:
        raise

h, w = seg.shape
ground = np.isin(seg, list(ground_ids))
row = ground.mean(axis=1)
lo = int(h * search_from)
rows = np.nonzero(row[lo:] > row_cov)[0]
ids, counts = np.unique(seg, return_counts=True)
top = sorted(zip(counts.tolist(), ids.tolist()), reverse=True)[:4]
print(json.dumps({
    "ok": True,
    "device": used,
    "ground_frac": float(ground.mean()),
    "ground_top": (lo + int(rows[0])) / h if len(rows) else None,
    "sky_water_frac": float(np.isin(seg, list(sw_ids)).mean()),
    "furniture_frac": float(np.isin(seg, list(furn_ids)).mean()),
    "graphic_frac": float(np.isin(seg, list(gfx_ids)).mean()),
    "top_classes": [[model.config.id2label[i].split(",")[0].strip(), round(c / seg.size, 3)]
                    for c, i in top],
}))
'''


def worker_source() -> str:
    return _WORKER.replace("__MODEL_ID__", MODEL_ID).replace(
        "__MODEL_REVISION__", MODEL_REVISION)


@dataclass(frozen=True)
class GroundEstimate:
    """What the detector concluded about one backdrop photograph."""

    usable: bool
    reason: str
    #: Where the feet should land, as a fraction of height from the top --
    #: or None for "no floor visible; default placement" (which is *not* the
    #: same as unusable, see the module docstring).
    floor_frac: float | None
    ground_frac: float = 0.0
    sky_water_frac: float = 0.0
    furniture_frac: float = 0.0
    graphic_frac: float = 0.0
    top_classes: list = field(default_factory=list)
    device: str | None = None


def judge(raw: dict) -> GroundEstimate:
    """The decision rules, kept separate from the model call so they can
    be tested against recorded outputs without a GPU in the room."""
    T = THRESHOLDS
    g, sw, fu = raw["ground_frac"], raw["sky_water_frac"], raw["furniture_frac"]
    gx = raw.get("graphic_frac", 0.0)
    top = raw.get("top_classes", [])
    common = dict(ground_frac=g, sky_water_frac=sw, furniture_frac=fu,
                  graphic_frac=gx, top_classes=top, device=raw.get("device"))
    if sw > T.ground_sky_water_max:
        return GroundEstimate(False, f"mostly sky or water ({sw:.0%})", None, **common)
    if fu > T.ground_furniture_max:
        return GroundEstimate(False, f"table-height scene ({fu:.0%} furniture)", None, **common)
    if gx > T.ground_graphic_max:
        return GroundEstimate(
            False, f"looks like a graphic or text, not a photographed place "
                   f"({gx:.0%} signboard/poster/screen)", None, **common)
    top_ = raw.get("ground_top")
    if g >= T.ground_min_frac and top_ is not None:
        ff = top_ + T.ground_feet_depth * (1.0 - top_)
        return GroundEstimate(
            True, f"floor found from {top_:.0%} down ({g:.0%} of frame)",
            float(min(max(ff, 0.0), 1.0)), **common)
    return GroundEstimate(
        True, "no floor visible -- standing in front of it at the default placement",
        None, **common)


def available() -> bool:
    return INTERPRETER.exists()


_CACHE: dict[str, GroundEstimate] = {}


def _key(bg: Image.Image) -> str:
    small = bg.convert("RGB").resize((64, 64))
    return hashlib.sha1(small.tobytes()).hexdigest()


def detect_ground(bg: Image.Image) -> GroundEstimate:
    """Run the detector on one backdrop photograph, cached by content.

    Never raises for a missing interpreter or a failed run: ground detection
    is an improvement on the default placement, not a requirement for it,
    so a machine without the CUDA venv (or a model download that fails)
    gets the same result as before this module existed -- default
    placement, and a `reason` that says why.
    """
    key = _key(bg)
    if key in _CACHE:
        return _CACHE[key]
    if not available():
        est = GroundEstimate(True, "ground detection unavailable (no torch interpreter)", None)
        _CACHE[key] = est
        return est
    T = THRESHOLDS
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "bg.png"
        worker = Path(td) / "worker.py"
        bg.convert("RGB").save(src)
        worker.write_text(worker_source(), encoding="utf-8")
        proc = subprocess.run(
            [str(INTERPRETER), str(worker), str(src),
             str(T.ground_row_coverage), str(T.ground_search_from)],
            capture_output=True, text=True, timeout=600,
        )
    raw = None
    for line in proc.stdout.splitlines()[::-1]:
        line = line.strip()
        if line.startswith("{"):
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                pass
            break
    if not raw or not raw.get("ok"):
        est = GroundEstimate(
            True, f"ground detection failed -- default placement ({proc.stderr[-300:].strip()})",
            None)
    else:
        est = judge(raw)
    _CACHE[key] = est
    return est
