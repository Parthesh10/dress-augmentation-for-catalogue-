"""Batch runner.

    $env:PYTHONPATH="src"
    .venv\Scripts\python.exe -m dressaug.cli --path data\fixtures\0000-flat.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import backgrounds, stages  # noqa: F401 -- registers the stages
from .config import EXPORT_PRESETS, Fabric, Garment, Graph, JobConfig
from .graphs import stages_for
from .pipeline import ArtifactStore, Context, JobManifest, PipelineRunner


def use_utf8_console() -> None:
    """Windows consoles are cp1252 and cannot encode the characters the gate
    messages use. Without this a run completes and then dies in `print` --
    the sibling project lost a seven-case regression run to exactly that."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def run_one(
    path: Path, cfg: JobConfig, backend: str = "local_cpu", *,
    quiet: bool = False, custom_backdrop: Path | None = None,
    floor_frac: float | None = None, fill: float | None = None,
    x_frac: float | None = None, seam_blur: float | None = None,
):
    job_id = f"{path.stem[:24]}-{cfg.graph.value}"
    store = ArtifactStore(job_id)
    manifest = JobManifest(
        job_id=job_id, source=str(path), profile=cfg.profile,
        config={"graph": cfg.graph.value, "garment": cfg.garment.value,
                "fabric": cfg.resolved_fabric().value,
                "background": "custom photo" if custom_backdrop else cfg.background},
    )
    ctx = Context(job_id=job_id, source_path=path, cfg=cfg, store=store, manifest=manifest)
    ctx.extra["backend"] = backend
    if custom_backdrop is not None:
        from PIL import Image, ImageOps
        ctx.extra["custom_background"] = ImageOps.exif_transpose(
            Image.open(custom_backdrop)).convert("RGB")
    # Placement overrides. None means "decide automatically"; see
    # `stages._placement_overrides` for what each one reaches.
    for key, val in (("custom_floor_frac", floor_frac), ("subject_fill", fill),
                     ("subject_x", x_frac), ("seam_blur_strength", seam_blur)):
        if val is not None:
            ctx.extra[key] = val

    def progress(name, i, n):
        if not quiet:
            print(f"    [{i}/{n}] {name}", flush=True)

    m = PipelineRunner().run(ctx, stages_for(cfg.graph), progress)
    m.write(store.dir / "manifest.json")
    return m


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    ap = argparse.ArgumentParser(prog="dressaug")
    ap.add_argument("--path", type=Path, required=True)
    ap.add_argument("--graph", default=Graph.FLAT.value,
                    choices=[g.value for g in Graph])
    ap.add_argument("--garment", default=Garment.PARTY_DRESS.value,
                    choices=[g.value for g in Garment])
    ap.add_argument("--fabric", default=None, choices=[f.value for f in Fabric])
    ap.add_argument("--background", default="studio_ivory",
                    choices=sorted(backgrounds.PRESETS))
    ap.add_argument("--presets", default=None,
                    help="comma-separated; default is the garment portrait pair")
    ap.add_argument("--custom-backdrop", type=Path, default=None,
                    help="a photograph to use as the backdrop instead of --background; "
                         "must be one you actually have the rights to use commercially")
    ap.add_argument("--floor-frac", type=float, default=None,
                    help="with --custom-backdrop: where the feet should land, as a "
                         "fraction of the photo's height from the top (e.g. 0.95 for "
                         "near the bottom). Set once per backdrop photo, by eye; "
                         "reused for every garment composited onto it")
    ap.add_argument("--fill", type=float, default=None,
                    help="how tall the figure is, as a fraction of the height above the "
                         "floor line (default: from the backdrop, or 0.88)")
    ap.add_argument("--x", type=float, default=None,
                    help="horizontal centre of the figure, 0-1 (default 0.5)")
    ap.add_argument("--seam-blur", type=float, default=None,
                    help="strength of the feathered patch where the hem meets the ground, "
                         "1.0 = default, 0 = off")
    a = ap.parse_args(argv)

    cfg = JobConfig(
        graph=Graph(a.graph), garment=Garment(a.garment),
        fabric=Fabric(a.fabric) if a.fabric else None,
        background=a.background,
        presets=[p.strip() for p in a.presets.split(",")] if a.presets
        else JobConfig().presets,
    )
    for p in cfg.presets:
        if p not in EXPORT_PRESETS:
            print(f"unknown preset {p!r}; have {sorted(EXPORT_PRESETS)}")
            return 2

    print(f"=== {a.path.name}  garment={cfg.garment.value} "
          f"fabric={cfg.resolved_fabric().value} "
          f"backdrop={a.custom_backdrop.name if a.custom_backdrop else cfg.background}")
    m = run_one(a.path, cfg, custom_backdrop=a.custom_backdrop, floor_frac=a.floor_frac,
                fill=a.fill, x_frac=a.x, seam_blur=a.seam_blur)
    print(f"    status={m.status}  {m.total_seconds:.1f}s")
    for g in m.gates:
        print(f"    [{'ok' if g.passed else 'FAIL'}] {g.name}: {g.detail}")
    for w in m.warnings:
        print(f"    warn: {w}")
    for o in m.outputs:
        print(f"    -> {o}")
    return 0 if m.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
