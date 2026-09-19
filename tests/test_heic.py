"""HEIC/HEIF input support.

Found necessary 2026-09-19: the operator's own real garment photographs
(dropped into test-images/, gitignored -- private stock, never committed)
are 136 HEIC files straight off an iPhone, and Pillow has never shipped a
HEIF decoder. Every one of them failed at `ingest` with "cannot identify
image file" before this.

The fixture here is a **synthetic** HEIC, generated on the fly by
`pillow_heif` itself, not a copy of the operator's real photos -- those stay
out of version control entirely, same discipline as every other private or
licence-uncertain image this project has touched.
"""
import sys, pathlib, io
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import numpy as np
from PIL import Image

import dressaug  # noqa: F401 -- importing the package registers the HEIF opener
from dressaug import stages
from dressaug.config import THRESHOLDS


def _synthetic_heic(path, size=(1600, 2000), colour=(150, 60, 90)):
    """A real .heic file, encoded from nothing -- exercises the actual
    decoder rather than trusting that registration alone is enough."""
    import pillow_heif

    im = Image.new("RGB", size, colour)
    heif = pillow_heif.from_pillow(im)
    heif.save(path, quality=90)
    return im


def test_the_heif_opener_is_registered_by_importing_the_package():
    """The mechanism the fix relies on: Gradio's own upload handling calls
    PIL.Image.open() with no format allowlist (confirmed by reading
    gradio.image_utils.preprocess_image on 2026-09-19), so registering the
    opener anywhere downstream of `import dressaug` would be too late for a
    HEIC uploaded through the app. It has to be package-level."""
    import PIL.Image as PILImage
    assert "HEIF" in PILImage.OPEN or "HEIC" in PILImage.OPEN, (
        "no HEIF/HEIC opener registered with Pillow -- pillow_heif."
        "register_heif_opener() should have run at `import dressaug` time"
    )


def test_a_real_heic_file_round_trips_through_plain_pil_open():
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "photo.heic")
        original = _synthetic_heic(path)
        im = Image.open(path)
        im.load()
        assert im.size == original.size
        # HEIC decodes to RGB even for a flat colour; check it round-tripped
        # reasonably rather than pixel-exact, since HEIC is lossy by default.
        arr = np.asarray(im.convert("RGB"), dtype=np.int16)
        want = np.array(original.getpixel((0, 0)))
        assert np.abs(arr[0, 0] - want).max() < 20, (arr[0, 0], want)


def test_the_ingest_stage_accepts_a_heic_source():
    """The actual entry point every job goes through -- not just PIL in
    isolation, but `stages.ingest`, which is what a HEIC upload or a HEIC
    file passed to the CLI actually reaches first."""
    import tempfile, os
    from dressaug.pipeline import Context, ArtifactStore, JobManifest
    from dressaug.config import JobConfig, Graph, Garment

    with tempfile.TemporaryDirectory() as td:
        path = pathlib.Path(td) / "garment.heic"
        _synthetic_heic(str(path), size=(1600, 2000))

        cfg = JobConfig(graph=Graph.FLAT, garment=Garment.PARTY_DRESS)
        job_id = "heic-test"
        ctx = Context(
            job_id=job_id, source_path=path, cfg=cfg,
            store=ArtifactStore(job_id),
            manifest=JobManifest(job_id=job_id, source=str(path), profile=cfg.profile),
        )
        ctx = stages.ingest(ctx)
        assert ctx.source is not None
        assert ctx.source.mode == "RGB"
        assert min(ctx.source.size) >= THRESHOLDS.min_short_edge_reject


def test_a_heic_below_the_reject_floor_is_still_refused_for_size_not_format():
    """HEIC support must not accidentally bypass the existing quality gate --
    a tiny HEIC should fail for being tiny, the same way a tiny JPEG does."""
    import tempfile
    from dressaug.pipeline import Context, ArtifactStore, JobManifest
    from dressaug.config import JobConfig, Graph, Garment

    with tempfile.TemporaryDirectory() as td:
        path = pathlib.Path(td) / "tiny.heic"
        _synthetic_heic(str(path), size=(200, 200))

        cfg = JobConfig(graph=Graph.FLAT, garment=Garment.PARTY_DRESS)
        job_id = "heic-tiny"
        ctx = Context(
            job_id=job_id, source_path=path, cfg=cfg,
            store=ArtifactStore(job_id),
            manifest=JobManifest(job_id=job_id, source=str(path), profile=cfg.profile),
        )
        try:
            stages.ingest(ctx)
        except ValueError as exc:
            assert "floor" in str(exc) or "px" in str(exc)
            return
        raise AssertionError("a 200x200 HEIC should be rejected for size")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("pass", fn.__name__)
    print(f"all {len(fns)} HEIC tests pass")
