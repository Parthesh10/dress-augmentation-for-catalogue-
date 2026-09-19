"""Person-preservation on real Indian ethnic wear, worn by a model.

The requirement this pins: when a photograph shows a person wearing the
garment, background removal must not selectively drop the person -- their
face, hair, hands must survive the matte along with the fabric.

Skips gracefully when the fixtures aren't on disk (they are real retail
photography, gitignored, local-testing-only -- see
data/ethnic-fixtures/PROVENANCE.json). This file exists so the finding from
the 2026-09-19 testing pass is checked on every run where the fixtures are
present, rather than trusted from memory.

Method: a plain whiteness threshold on the raw photograph as ground truth for
"this pixel is the subject" (valid here because this dataset's studio
backgrounds are genuinely near-pure white). If BiRefNet's alpha mask covers
much less of that region than the threshold does, something -- most
worryingly the head or hands -- was excluded. Known limitation, stated rather
than hidden: a white-on-white garment breaks this ground truth, because the
fabric itself reads as "background" by the same test. Two of the twelve
fixtures used in the original pass hit exactly that (both verified by eye,
in TASK.md, to be correctly matted) -- this file's threshold accounts for it
by checking the *head region* specifically, which is skin/hair and not
garment colour, so it is not sensitive to the garment being white.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import numpy as np
from PIL import Image

FIXDIR = pathlib.Path(__file__).resolve().parents[1] / "data" / "ethnic-fixtures"

# A representative subset, not all 12 -- this file runs a real matting pass
# per fixture (40-70s each) and is meant to be run deliberately, not on every
# save. `test_ui.py::test_process_runs_the_real_pipeline_end_to_end` is the
# one real-pipeline test that runs unconditionally in the fast suite.
SAMPLE = ["00-sarees-grey.jpg", "54-kurtas-white.jpg", "33-dupatta-orange.jpg"]


def _head_region_missed_fraction(im: Image.Image, alpha: np.ndarray) -> float:
    """Of the pixels in the top 18% of the frame that are clearly not
    background (skin or hair, not garment), what fraction did the matte miss.
    """
    rgb = np.asarray(im, np.float32) / 255.0
    whiteness = rgb.min(axis=2)
    h = rgb.shape[0]
    band = slice(0, int(h * 0.18))
    ground_truth = whiteness[band] < 0.92
    predicted = (alpha[band] > 0.5)
    missed = ground_truth & ~predicted
    denom = max(int(ground_truth.sum()), 1)
    return float(missed.sum()) / denom


def test_fixtures_present_or_skip():
    if not FIXDIR.exists():
        print("  (skipped -- data/ethnic-fixtures not on disk; see docs/01-datasets.md)")
        return
    missing = [f for f in SAMPLE if not (FIXDIR / f).exists()]
    assert not missing, f"expected fixtures missing: {missing}"


def test_the_head_region_survives_matting_on_real_worn_photographs():
    """The core claim, measured fresh rather than quoted from a prior run."""
    if not FIXDIR.exists():
        print("  (skipped -- data/ethnic-fixtures not on disk)")
        return

    from dressaug.backends import get_backend
    backend = get_backend("local_cpu")

    worst = 0.0
    for fn in SAMPLE:
        path = FIXDIR / fn
        if not path.exists():
            continue
        im = Image.open(path).convert("RGB")
        alpha = backend.matte(im)
        if alpha.shape[:2] != (im.size[1], im.size[0]):
            alpha = np.asarray(
                Image.fromarray((alpha * 255).astype(np.uint8), "L").resize(
                    im.size, Image.LANCZOS), np.float32) / 255.0
        frac = _head_region_missed_fraction(im, alpha)
        worst = max(worst, frac)
        assert frac < 0.10, (
            f"{fn}: {frac:.1%} of the head/hair region was missing from the "
            "matte -- the person may have been partially dropped"
        )
    print(f"  worst head-region miss across sample: {worst:.1%}")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("pass", fn.__name__)
    print(f"all {len(fns)} person-preservation tests pass")
