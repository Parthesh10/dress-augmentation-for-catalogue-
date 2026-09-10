"""Matting backend — phase 1, "background removal".

Deliberately leaner than the sibling jewellery project's `backends.py`: that
one carries a Modal deployment as well, and Modal's workspace has been
disabled since 2026-08-25. There is no reason to inherit a second code path
that does not currently run. `local_cpu` is what works, and it ran the
sibling's entire 68-photograph audit and its real-image regression set
correctly, which is the evidence that it is sufficient.

**Two lessons are carried over whole, because both were paid for.**

*The model is pinned to a revision.* `trust_remote_code=True` asks the Hub for
code as well as weights and then executes it, so tracking an implicit `main`
means the thing that runs is whatever was pushed most recently rather than the
thing that was reviewed. The sibling had this right on one backend and wrong
on the other for weeks, which meant the two could silently load different
models — see its `tests/test_backends_pinning.py`.

*fp16 is not offered.* BiRefNet's Swin backbone overflows in half precision
and returns an all-NaN alpha. That is not a quality regression, it is a total
failure that looks like a dozen other bugs, so the option simply does not
exist here.

**What is new is what phase 1 actually has to survive.** A bangle is opaque —
a pixel is product or background. A chiffon dupatta or a tulle skirt is
genuinely both, and the alpha that describes it is fractional over large
areas. So this module returns the soft alpha unchanged and refuses to
threshold it; `stages` decides what to do about transparency, using the
fabric the operator declared.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from .config import ROOT

#: The torch interpreter. Shared with the sibling project rather than
#: duplicated: it is a 2 GB install of torch plus transformers, it is already
#: on this machine, and two copies would drift.
INTERPRETER = (
    ROOT.parent.parent / "Boutique Business" / ".venv-birefnet" / "Scripts" / "python.exe"
)

MODEL_ID = "ZhengPeng7/BiRefNet-matting"
MODEL_REVISION = "57f9f68b43ba337c75762b14cf3075d659007268"

#: Placeholders are substituted at write time so the revision appears once, as
#: a named constant, rather than as a hash buried in a raw string.
_WORKER = r'''
import sys, json, numpy as np
from PIL import Image
import torch
from transformers import AutoModelForImageSegmentation
from torchvision import transforms

src, dst, size = sys.argv[1], sys.argv[2], int(sys.argv[3])
m = AutoModelForImageSegmentation.from_pretrained(
    "__MODEL_ID__", revision="__MODEL_REVISION__", trust_remote_code=True).eval()
im = Image.open(src).convert("RGB")
tf = transforms.Compose([
    transforms.Resize((size, size)), transforms.ToTensor(),
    transforms.Normalize([0.485,0.456,0.406],[0.229,0.224,0.225])])
with torch.no_grad():
    pred = m(tf(im).unsqueeze(0))[-1].sigmoid().float()
arr = pred[0,0].numpy()
if not np.isfinite(arr).all():
    raise SystemExit("non-finite alpha")
Image.fromarray((arr*255).astype("uint8"), "L").resize(im.size, Image.LANCZOS).save(dst)
print(json.dumps({"ok": True}))
'''


def worker_source() -> str:
    """`_WORKER` with the pinned model substituted in."""
    return _WORKER.replace("__MODEL_ID__", MODEL_ID).replace(
        "__MODEL_REVISION__", MODEL_REVISION
    )


class LocalCpuMatting:
    """BiRefNet on CPU, in a separate interpreter.

    Slow — 60-180 s for a full frame — and correct. The separate process is
    not fastidiousness: this project's own venv deliberately has no torch, so
    that the operator machine stays a numpy-and-PIL install.
    """

    name = "local_cpu"

    def __init__(self, infer_size: int = 1024) -> None:
        self.infer_size = infer_size

    def available(self) -> bool:
        return INTERPRETER.exists()

    def matte(self, img: Image.Image) -> np.ndarray:
        """Soft alpha in [0, 1] at the image's own resolution.

        Returned **unthresholded**, on purpose. Hardening it here would throw
        away exactly the information a sheer garment consists of.
        """
        if not self.available():
            raise RuntimeError(
                f"local_cpu matting needs a torch interpreter at {INTERPRETER}. "
                "See README.md — it is shared with the sibling project."
            )
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "in.png", Path(td) / "alpha.png"
            worker = Path(td) / "worker.py"
            img.save(src)
            worker.write_text(worker_source(), encoding="utf-8")
            proc = subprocess.run(
                [str(INTERPRETER), str(worker), str(src), str(dst), str(self.infer_size)],
                capture_output=True, text=True, timeout=1800,
            )
            if not dst.exists():
                raise RuntimeError(f"matting failed:\n{proc.stderr[-1500:]}")
            return np.asarray(Image.open(dst).convert("L"), dtype=np.float32) / 255.0


def get_backend(name: str = "local_cpu") -> LocalCpuMatting:
    if name != "local_cpu":
        raise ValueError(f"unknown backend {name!r}; only 'local_cpu' exists here")
    return LocalCpuMatting()
