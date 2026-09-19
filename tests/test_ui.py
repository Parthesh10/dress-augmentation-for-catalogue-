"""The UI's own logic, exercised the way a click does -- not through Gradio's
event loop, but by calling the same functions a click calls.

Not a synthetic fixture in sight in the end-to-end test: this runs a real
matting pass on a real image, because the UI's most important promise is that
the button actually produces files, and that is exactly the promise a mocked
matting call cannot check.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from PIL import Image

from dressaug import ui
from dressaug.config import EXPORT_PRESETS, Fabric, Garment


class _NoProgress:
    def __call__(self, *a, **k):
        pass


FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "data" / "fixtures" / "0004-flat.png"


def test_every_garment_has_a_label_and_round_trips():
    for g in Garment:
        label = ui._GARMENT_LABELS[g]
        assert ui._garment_from_label(label) is g


def test_every_fabric_has_a_label_and_round_trips():
    for f in Fabric:
        label = ui._FABRIC_LABELS[f]
        assert ui._fabric_from_label(label) is f


def test_auto_fabric_resolves_to_none_so_the_garment_default_applies():
    assert ui._fabric_from_label(ui._AUTO_FABRIC) is None


def test_the_preset_label_map_is_populated_without_building_the_ui():
    """Pins the bug found 2026-09-19: the map used to fill only as a side
    effect of constructing the Gradio widgets, so calling `process()` before
    `build()` -- exactly what this test file does -- raised KeyError on every
    preset label."""
    assert len(ui._PRESET_LABEL_TO_NAME) == len(EXPORT_PRESETS)
    for label in ui._preset_choices():
        assert ui._PRESET_LABEL_TO_NAME[label] in EXPORT_PRESETS


def test_every_backdrop_preset_gets_a_thumbnail():
    from dressaug import backgrounds
    assert len(ui._BACKDROP_THUMBS) == len(backgrounds.PRESETS)
    assert set(ui._BACKDROP_NAMES) == set(backgrounds.PRESETS)


def test_the_app_builds_without_error():
    demo = ui.build()
    assert demo is not None


def test_missing_image_is_refused_without_running_the_pipeline():
    result = list(ui.process(
        None, "Gown", ui._AUTO_FABRIC, "studio_ivory",
        ui._preset_choices()[:1], progress=_NoProgress(),
    ))[-1]
    assert result[0] is None
    assert "photograph" in result[1].lower()


def test_missing_backdrop_is_refused():
    img = Image.new("RGB", (80, 80), (180, 140, 140))
    result = list(ui.process(
        img, "Gown", ui._AUTO_FABRIC, "",
        ui._preset_choices()[:1], progress=_NoProgress(),
    ))[-1]
    assert result[0] is None
    assert "backdrop" in result[1].lower()


def test_missing_presets_is_refused():
    img = Image.new("RGB", (80, 80), (180, 140, 140))
    result = list(ui.process(
        img, "Gown", ui._AUTO_FABRIC, "studio_ivory", [],
        progress=_NoProgress(),
    ))[-1]
    assert result[0] is None
    assert "export size" in result[1].lower()


def test_process_runs_the_real_pipeline_end_to_end():
    """The one test in this file that actually mattes an image. Slow (~50s)
    and deliberately not skipped: the UI's whole job is turning a click into
    files on disk, and that is the one thing worth spending real time to
    check for real."""
    if not FIXTURE.exists():
        print("  (skipped -- no fixture on disk; run dataset.cut_fixtures first)")
        return
    img = Image.open(FIXTURE).convert("RGB")
    gallery, report, warnings = list(ui.process(
        img, "Gown", ui._AUTO_FABRIC, "champagne_silk",
        ui._preset_choices()[:2], progress=_NoProgress(),
    ))[-1]
    assert gallery is not None and len(gallery) == 2
    assert "colour_fidelity" in report
    assert "cutout_softness" in report


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("pass", fn.__name__)
    print(f"all {len(fns)} UI tests pass")
