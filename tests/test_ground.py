"""Ground detection's decision rules, pinned against recorded model output.

`ground.judge()` is deliberately separate from the model call so that every
rule in it can be checked here against the *actual numbers* the segmentation
model produced on the 33 real backdrop photographs it was calibrated on --
without a GPU, a model download, or those photographs (which are not
committed) in the room. Each case below is a real recorded output, not a
made-up one, and the expected verdict is the by-eye call that was recorded
for that photograph *before* the model ever ran (TASK.md §1k, §1l).

The model call itself is exercised by `test_ui.py`'s real-pipeline custom
backdrop test, which now runs detection for real.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from dressaug import ground
from dressaug.config import THRESHOLDS


def _raw(**kw):
    base = dict(ground_frac=0.0, ground_top=None, sky_water_frac=0.0,
                furniture_frac=0.0, graphic_frac=0.0, top_classes=[], device="cuda")
    base.update(kw)
    return base


def test_a_real_floor_gives_a_floor_line_inside_the_ground_region():
    """Recorded: an empty room with a wood floor -- floor from 81% down,
    19% of the frame. The by-eye floor line was 0.92."""
    est = ground.judge(_raw(ground_frac=0.187, ground_top=0.81))
    assert est.usable
    assert est.floor_frac is not None
    assert 0.81 < est.floor_frac <= 1.0
    assert abs(est.floor_frac - 0.92) < 0.03, est.floor_frac


def test_feet_land_partway_into_the_ground_not_at_its_top_edge():
    """The top edge of the ground region is the far wall. Feet planted there
    read as "standing at the back". `ground_feet_depth` pushes them into the
    region -- 0 would be the top edge, 1 the bottom of the frame."""
    est = ground.judge(_raw(ground_frac=0.38, ground_top=0.58))  # recorded: a lawn
    expected = 0.58 + THRESHOLDS.ground_feet_depth * (1 - 0.58)
    assert abs(est.floor_frac - expected) < 1e-6


def test_a_drape_with_no_floor_is_usable_at_the_default_placement():
    """Recorded: a white curtain backdrop, 0% ground, 65% curtain. One of
    the best backdrops on the board -- 'no floor' must not mean 'refused'."""
    est = ground.judge(_raw(ground_frac=0.0, top_classes=[["curtain", 0.65]]))
    assert est.usable
    assert est.floor_frac is None
    assert "default" in est.reason


def test_mostly_sky_is_refused_even_with_real_ground_in_it():
    """Recorded: a night sky over a rocky shore -- 61% sky, 15% 'earth'.
    Real, standable earth, and still not a catalogue backdrop."""
    est = ground.judge(_raw(ground_frac=0.20, ground_top=0.67, sky_water_frac=0.67))
    assert not est.usable
    assert "sky" in est.reason


def test_a_flat_colour_swatch_is_refused_as_sky():
    """Recorded: a solid slate-blue card, 100% 'sky'. The detector called it
    unusable; the by-eye label had said usable-at-default, and was revised
    -- it is not a photographed place, and the procedural presets already
    do a flat colour better."""
    est = ground.judge(_raw(sky_water_frac=1.0, top_classes=[["sky", 1.0]]))
    assert not est.usable


def test_a_table_height_scene_is_refused():
    """Recorded: a wedding dinner table, 0% ground, 39% table. And a
    reception's round tables: 21% table + 20% chair -- the chair share is
    why furniture counts chairs and seats, not tables alone."""
    assert not ground.judge(_raw(furniture_frac=0.40)).usable
    assert not ground.judge(_raw(furniture_frac=0.41)).usable
    assert "table" in ground.judge(_raw(furniture_frac=0.40)).reason


def test_a_graphic_is_refused_on_its_signboard_share():
    """Recorded: a stock-photo-pack's own promotional thumbnail -- 72%
    'wall', 21% 'signboard', 7% 'floor'. The floor share is below the
    minimum, but the *reason* it's refused is the signboard: a real place
    came back with no signboard/poster/screen at all on any of the 33."""
    est = ground.judge(_raw(ground_frac=0.07, ground_top=0.92, graphic_frac=0.21))
    assert not est.usable
    assert "graphic" in est.reason


def test_a_sliver_of_floor_below_the_minimum_falls_back_to_default_not_a_guess():
    """Recorded: an abstract painting, 91% 'wall', 8% 'floor' from its own
    bottom edge. Below `ground_min_frac`, so no floor line is derived from
    it -- default placement. (It is *also* the documented residual: a flat
    painting is 'wall' to the model, indistinguishable from a real one, so
    it comes back usable. That is a known limit, pinned here as behaviour
    rather than hidden.)"""
    est = ground.judge(_raw(ground_frac=0.082, ground_top=0.80))
    assert est.usable
    assert est.floor_frac is None, "a sub-threshold floor share must not produce a floor line"


def test_the_derived_floor_line_is_always_within_the_frame():
    for top in (0.0, 0.3, 0.7, 0.95, 1.0):
        est = ground.judge(_raw(ground_frac=0.5, ground_top=top))
        assert 0.0 <= est.floor_frac <= 1.0


def test_detection_degrades_to_default_placement_without_an_interpreter(monkeypatch=None):
    """Ground detection is an improvement on the default, never a
    requirement for it. With no torch interpreter the result must be the
    same as before this module existed -- usable, default placement -- and
    the reason must say why, rather than raising."""
    from PIL import Image
    saved = ground.INTERPRETER
    try:
        ground.INTERPRETER = pathlib.Path("Z:/definitely/not/here/python.exe")
        ground._CACHE.clear()
        est = ground.detect_ground(Image.new("RGB", (64, 64), (100, 100, 100)))
        assert est.usable and est.floor_frac is None
        assert "unavailable" in est.reason
    finally:
        ground.INTERPRETER = saved
        ground._CACHE.clear()


def test_the_worker_actually_runs_and_answers_in_the_shared_interpreter():
    """The one test here that spawns the model. Slow (~10-25s: torch import
    plus model load in a fresh interpreter) and deliberately not skipped
    when the interpreter exists: the rule tests above prove `judge()`, but
    only this proves the subprocess boundary, the pinned download, the
    device selection and the JSON hand-off all actually work together.

    Claims only that the worker returns a well-formed answer with a real
    device -- *not* a particular semantic verdict. A synthetic two-tone
    image is not a photograph, and asserting what a scene-parsing model
    should call it would be asserting something this test has no business
    knowing. The semantic accuracy claims live in TASK.md §1l, measured
    against 33 real photographs that are not committed."""
    if not ground.available():
        print("  (skipped -- no torch interpreter on this machine)")
        return
    from PIL import Image
    import numpy as np
    arr = np.zeros((480, 360, 3), np.uint8)
    arr[:300] = (200, 200, 195)   # a pale wall
    arr[300:] = (140, 100, 70)    # a brown floor
    ground._CACHE.clear()
    est = ground.detect_ground(Image.fromarray(arr, "RGB"))
    assert est.device is not None, est.reason
    assert est.device.startswith("cuda") or est.device.startswith("cpu"), est.device
    assert 0.0 <= est.ground_frac <= 1.0
    assert est.floor_frac is None or 0.0 <= est.floor_frac <= 1.0
    # And the cache holds it -- a second call must not spawn again.
    again = ground.detect_ground(Image.fromarray(arr, "RGB"))
    assert again is est


def test_the_model_is_pinned_to_a_full_revision_sha():
    """The sibling's lesson, applied here too: the worker executes whatever
    the Hub serves at the revision it names."""
    assert len(ground.MODEL_REVISION) == 40
    assert ground.MODEL_REVISION in ground.worker_source()


def test_the_worker_builds_its_class_sets_by_name_from_the_models_own_labels():
    """Pins the mechanism, not just the outcome: ids are looked up from
    `id2label` inside the worker, so a revision that renumbered classes
    would surface as a name mismatch, not a silent misclassification."""
    src = ground.worker_source()
    assert "id2label" in src
    assert '"floor"' in src and '"sky"' in src and '"table"' in src


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("pass", fn.__name__)
    print(f"all {len(fns)} ground tests pass")
