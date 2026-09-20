"""Matting backend — phase 1, "background removal".

Deliberately leaner than the sibling jewellery project's `backends.py`: that
one carries a Modal deployment as well, and Modal's workspace has been
disabled since 2026-08-25. There is no reason to inherit a second code path
that does not currently run. `local_cpu` is what works, and it ran the
sibling's entire 68-photograph audit and its real-image regression set
correctly, which is the evidence that it is sufficient.

**Three lessons are carried over whole, because all three were paid for.**

*The model is pinned to a revision.* `trust_remote_code=True` asks the Hub for
code as well as weights and then executes it, so tracking an implicit `main`
means the thing that runs is whatever was pushed most recently rather than the
thing that was reviewed. The sibling had this right on one backend and wrong
on the other for weeks, which meant the two could silently load different
models — see its `tests/test_backends_pinning.py`.

*fp16 is not offered.* BiRefNet's Swin backbone overflows in half precision
and returns an all-NaN alpha. That is not a quality regression, it is a total
failure that looks like a dozen other bugs, so the option simply does not
exist here — not on CPU, and not on CUDA below. (A `cuda-test/` directory
found in the sibling project, holding blank output frames from 2026-08-11
and a `.venv-cuda` that was never wired into any pipeline, is very likely
where this was originally learned — GPU inference in half precision hits the
same Swin-backbone overflow CPU fp16 would, since it is a numerical property
of the model, not of which processor runs it.)

*GPU inference is measured, not assumed, before being trusted.* Added
2026-09-20: `.venv-cuda` was sitting on this machine, already built with
CUDA-enabled torch, unused. Before pointing production at it: ran the same
photograph through both the CPU and CUDA paths and diffed the resulting
alphas (mean abs difference 2.9e-8, max 0.0039 — within one 8-bit
quantisation step, i.e. floating-point noise between BLAS backends, not a
real disagreement) and measured peak VRAM use on a full frame at this
project's `infer_size` (~3.35 GB allocated against a 4 GB card with ~3.4 GB
actually free after the OS's own usage) before deciding it fits — with real
margin thin enough that a fallback below is not caution for its own sake.

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

_SIBLING = ROOT.parent.parent / "Boutique Business"

#: The torch interpreter. Shared with the sibling project rather than
#: duplicated: it is a multi-GB install of torch plus transformers, it is
#: already on this machine, and a second copy would drift.
#:
#: `.venv-cuda` is preferred over `.venv-birefnet` — same packages, same
#: pinned model, the only difference is a CUDA-enabled torch build — with
#: `.venv-birefnet` kept as the fallback if `.venv-cuda` is ever absent,
#: rather than as a second code path to maintain: the worker script below is
#: the same file either way and detects CUDA at runtime, so which
#: interpreter answers only changes whether that detection finds a GPU.
_CUDA_INTERPRETER = _SIBLING / ".venv-cuda" / "Scripts" / "python.exe"
_CPU_INTERPRETER = _SIBLING / ".venv-birefnet" / "Scripts" / "python.exe"
INTERPRETER = _CUDA_INTERPRETER if _CUDA_INTERPRETER.exists() else _CPU_INTERPRETER

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
x = tf(im).unsqueeze(0)

def run(device):
    with torch.no_grad():
        pred = m.to(device)(x.to(device))[-1].sigmoid().float()
    return pred[0, 0].cpu().numpy()

# fp32 throughout, on either device -- never autocast, never .half(). See
# this module's docstring: BiRefNet's Swin backbone returns an all-NaN alpha
# in half precision regardless of which processor runs it.
device = "cuda" if torch.cuda.is_available() else "cpu"
used = device
try:
    arr = run(device)
except RuntimeError as exc:
    if device == "cuda" and "out of memory" in str(exc).lower():
        # A measured risk, not a hypothetical: this model's own peak
        # allocation on a full frame runs within a few hundred MB of a 4 GB
        # card's actual free memory, so any other GPU load on the machine
        # that day can tip it over. Correctness is never traded for speed --
        # fall back to the CPU path this ran reliably on before CUDA existed.
        torch.cuda.empty_cache()
        used = "cpu (fallback after CUDA OOM)"
        arr = run("cpu")
    else:
        raise

if not np.isfinite(arr).all():
    raise SystemExit("non-finite alpha")
Image.fromarray((arr*255).astype("uint8"), "L").resize(im.size, Image.LANCZOS).save(dst)
print(json.dumps({"ok": True, "device": used}))
'''


def worker_source() -> str:
    """`_WORKER` with the pinned model substituted in."""
    return _WORKER.replace("__MODEL_ID__", MODEL_ID).replace(
        "__MODEL_REVISION__", MODEL_REVISION
    )


class LocalCpuMatting:
    """BiRefNet in a separate interpreter, on GPU when one is available.

    The name predates GPU support and is kept anyway: every caller,
    config, and test already spells the backend `"local_cpu"`, and what it
    actually promises — runs on this machine, not a cloud API — never
    changed. What changed is only how fast it keeps that promise: seconds on
    a CUDA-enabled interpreter, 30-180s on a CPU-only one, with an automatic
    fallback to CPU baked into the worker script itself if the GPU path ever
    runs out of memory mid-job.

    The separate process is not fastidiousness: this project's own venv
    deliberately has no torch, so that the operator machine stays a
    numpy-and-PIL install regardless of which interpreter answers.
    """

    name = "local_cpu"

    def __init__(self, infer_size: int = 1024) -> None:
        self.infer_size = infer_size
        #: Set by the most recent `matte()` call -- "cuda", "cpu", or the
        #: OOM-fallback string. `None` before the first call.
        self.last_device: str | None = None

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
            self.last_device = None
            for line in proc.stdout.splitlines()[::-1]:
                line = line.strip()
                if line.startswith("{"):
                    try:
                        self.last_device = json.loads(line).get("device")
                    except json.JSONDecodeError:
                        pass
                    break
            return np.asarray(Image.open(dst).convert("L"), dtype=np.float32) / 255.0


def get_backend(name: str = "local_cpu") -> LocalCpuMatting:
    if name != "local_cpu":
        raise ValueError(f"unknown backend {name!r}; only 'local_cpu' exists here")
    return LocalCpuMatting()
