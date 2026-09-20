"""Stage registry, artifact store, job manifest and the runner.

**Architecture inherited from the sibling jewellery project**
(`Image Augmentation`, `src/imgaug/pipeline.py`). This module is deliberately
close to it, because none of it knows what a product is: a graph is a list of
stage names, a stage is a function from Context to Context, and everything a
run did is written to a manifest so it can be argued with afterwards. That
shape earned its keep over three product families there and there is no
reason to redesign it for a fourth.

What this project adds to it is `Context.phase` — the roadmap in
`config.Phase` is a sequence, and a stage that belongs to a phase which is
not built yet should say so rather than silently doing nothing.
"""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
from PIL import Image

from .config import WORK_DIR, JobConfig


# ---------------------------------------------------------------- artifacts


@dataclass
class Artifact:
    stage: str
    name: str
    path: str
    kind: str  # "image" | "mask" | "json"


class ArtifactStore:
    """Every intermediate is written to disk and recorded.

    FR-9 requires per-stage artifacts to be inspectable, and the debugging
    reality is that a composite failure is almost never in the composite —
    it is a bad alpha three stages earlier. Keeping every intermediate is
    cheap and it is the difference between "the output looks wrong" and
    "the matte lost the latkans".
    """

    def __init__(self, job_id: str, root: Path = WORK_DIR):
        self.job_id = job_id
        self.dir = root / job_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.artifacts: list[Artifact] = []
        self._seq = 0

    def _next(self, stage: str, name: str, ext: str) -> Path:
        self._seq += 1
        return self.dir / f"{self._seq:02d}-{stage}-{name}.{ext}"

    def image(self, stage: str, name: str, img: Image.Image) -> Artifact:
        p = self._next(stage, name, "png")
        img.save(p)
        a = Artifact(stage, name, str(p), "image")
        self.artifacts.append(a)
        return a

    def mask(self, stage: str, name: str, alpha: np.ndarray) -> Artifact:
        p = self._next(stage, name, "png")
        Image.fromarray((np.clip(alpha, 0, 1) * 255).astype(np.uint8), "L").save(p)
        a = Artifact(stage, name, str(p), "mask")
        self.artifacts.append(a)
        return a

    def json(self, stage: str, name: str, data: Any) -> Artifact:
        p = self._next(stage, name, "json")
        p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        a = Artifact(stage, name, str(p), "json")
        self.artifacts.append(a)
        return a


# ---------------------------------------------------------------- manifest


@dataclass
class StageRecord:
    name: str
    status: str  # "ok" | "failed" | "skipped"
    seconds: float
    note: str = ""


@dataclass
class GateResult:
    name: str
    passed: bool
    value: float | None
    threshold: float | None
    detail: str = ""


@dataclass
class JobManifest:
    """AD-4. The record of what was done, enough to reproduce or argue with it."""

    job_id: str
    source: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    config: dict = field(default_factory=dict)
    profile: str = ""
    backend: str = ""
    stages: list[StageRecord] = field(default_factory=list)
    gates: list[GateResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    #: Measurements a stage took that the operator has to be able to see.
    #: `Context.extra` is the scratch space stages talk to each other through
    #: and most of it is arrays and intermediates; this is the small, named
    #: subset worth keeping -- see `DIAGNOSTIC_KEYS`.
    diagnostics: dict = field(default_factory=dict)
    status: str = "pending"
    total_seconds: float = 0.0

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, default=str), encoding="utf-8")

    @property
    def passed(self) -> bool:
        return self.status == "ok" and all(g.passed for g in self.gates)


# ---------------------------------------------------------------- context


@dataclass
class Context:
    """Carried through the graph. Stages read what they need and add to it."""

    job_id: str
    source_path: Path
    cfg: JobConfig
    store: ArtifactStore
    manifest: JobManifest

    #: Ingested product photo, sRGB, EXIF-oriented. Set by `ingest`.
    source: Image.Image | None = None
    #: Soft alpha in [0,1], same size as `source`. Set by `matte`.
    alpha: np.ndarray | None = None
    #: Product RGB with background spill removed. Set by `matte`.
    product: Image.Image | None = None
    #: Generated backdrop at composite size. Set by `background`.
    background: Image.Image | None = None
    #: The composited result before export cropping. Set by `composite`.
    composited: Image.Image | None = None
    #: Alpha of the product within `composited`, for the gates.
    composited_alpha: np.ndarray | None = None
    #: Written files, per preset.
    exports: dict[str, str] = field(default_factory=dict)

    extra: dict[str, Any] = field(default_factory=dict)

    def warn(self, msg: str) -> None:
        self.manifest.warnings.append(msg)


Stage = Callable[[Context], Context]


# ---------------------------------------------------------------- registry


class StageRegistry:
    """AD-3. Name -> stage. Graphs are lists of names, so a graph is data."""

    def __init__(self) -> None:
        self._stages: dict[str, Stage] = {}

    def register(self, name: str) -> Callable[[Stage], Stage]:
        def deco(fn: Stage) -> Stage:
            if name in self._stages:
                raise ValueError(f"stage {name!r} already registered")
            self._stages[name] = fn
            return fn

        return deco

    def get(self, name: str) -> Stage:
        try:
            return self._stages[name]
        except KeyError:
            raise KeyError(
                f"unknown stage {name!r}; registered: {sorted(self._stages)}"
            ) from None

    def names(self) -> list[str]:
        return sorted(self._stages)


REGISTRY = StageRegistry()


# ---------------------------------------------------------------- runner


#: What survives from `Context.extra` into the written manifest.
#:
#: `relight_strength` is the one that prompted this. The 2026-09-05 regression
#: run found relight throttling itself on 7 of 7 real photographs -- a real
#: quality ceiling -- and the number describing it existed only in memory, so
#: nothing downstream could show the operator that the candidate they were
#: looking at had been lit at 25% of intent.
DIAGNOSTIC_KEYS = (
    "backdrop_used",
    "key_luminance",
    "product_key_luminance",
    "relight_ratio",
    "relight_strength",
    "relight_delta_e",
    "composite_size",
    # 2026-09-20: which device matted, and -- for a custom backdrop -- what
    # the ground detector concluded and where it planted the feet. Same
    # reasoning as relight_strength above: a batch of 500 needs these on
    # disk per job to filter and audit, not only in one process's memory.
    "matting_device",
    "ground_verdict",
    "ground_usable",
    "custom_floor_frac",
)


def _diagnostics(ctx: "Context") -> dict:
    return {k: ctx.extra[k] for k in DIAGNOSTIC_KEYS if k in ctx.extra}


class PipelineRunner:
    def __init__(self, registry: StageRegistry = REGISTRY):
        self.registry = registry

    def run(
        self,
        ctx: Context,
        stage_names: Iterable[str],
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> JobManifest:
        names = list(stage_names)
        t_all = time.perf_counter()

        for i, name in enumerate(names, 1):
            if on_progress:
                on_progress(name, i, len(names))
            stage = self.registry.get(name)
            t0 = time.perf_counter()
            try:
                ctx = stage(ctx)
            except Exception as exc:  # noqa: BLE001 — recorded, then re-raised context
                ctx.manifest.stages.append(
                    StageRecord(name, "failed", time.perf_counter() - t0, str(exc))
                )
                ctx.manifest.status = "failed"
                ctx.manifest.warnings.append(traceback.format_exc(limit=3))
                ctx.manifest.artifacts = ctx.store.artifacts
                ctx.manifest.diagnostics = _diagnostics(ctx)
                ctx.manifest.total_seconds = time.perf_counter() - t_all
                return ctx.manifest
            ctx.manifest.stages.append(
                StageRecord(name, "ok", time.perf_counter() - t0)
            )

        ctx.manifest.artifacts = ctx.store.artifacts
        ctx.manifest.outputs = list(ctx.exports.values())
        ctx.manifest.diagnostics = _diagnostics(ctx)
        ctx.manifest.total_seconds = time.perf_counter() - t_all
        ctx.manifest.status = "ok"
        return ctx.manifest


# ---------------------------------------------------------------- housekeeping


def work_usage(root: Path = WORK_DIR) -> tuple[int, int]:
    """`(job directories, bytes)` currently under the work root."""
    if not root.exists():
        return 0, 0
    dirs = [d for d in root.iterdir() if d.is_dir()]
    total = sum(f.stat().st_size for d in dirs for f in d.rglob("*") if f.is_file())
    return len(dirs), total


def clean_work(keep: int = 10, root: Path = WORK_DIR, *, dry_run: bool = False) -> dict:
    """Delete old job directories, keeping the `keep` most recent.

    `work/` is scratch by definition — every file in it is a pure function of a
    source photograph and a job config, so nothing here is information. It
    still grows without bound, and a variation set of four writes four job
    directories at a time, so it grows faster than a run count suggests.

    Keeps the most recent rather than emptying, because the reason to open one
    of these is almost always "the last run looked wrong" — and deleting the
    evidence at the moment you want it is the one behaviour that would make
    this feature a net loss.
    """
    import shutil

    if keep < 0:
        raise ValueError("keep cannot be negative")
    if not root.exists():
        return {"removed": 0, "kept": 0, "freed_bytes": 0, "dry_run": dry_run}

    dirs = sorted(
        (d for d in root.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    doomed = dirs[keep:]
    freed = sum(f.stat().st_size for d in doomed for f in d.rglob("*") if f.is_file())
    if not dry_run:
        for d in doomed:
            shutil.rmtree(d, ignore_errors=True)
    return {
        "removed": len(doomed),
        "kept": len(dirs) - len(doomed),
        "freed_bytes": freed,
        "dry_run": dry_run,
    }
