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


def test_load_upload_decodes_a_heic_file():
    """The fix for a real, reported bug: uploading a .heic through the app's
    own drop zone was refused client-side with "Invalid file type only
    image/* allowed" before this file ever reached Python at all -- on
    Windows, a .heic file's browser-reported MIME type is commonly empty,
    since there is no OS-level file association for it, and `gr.Image`'s
    upload widget rejects anything that does not MIME-sniff as "image/*".

    The fix routes the upload through `gr.File` with an explicit
    `file_types` list instead, which is validated server-side by filename
    extension -- unaffected by what the browser's MIME sniff says. This test
    proves the decode side of that path works against a real HEIC file; it
    cannot exercise the browser's own upload widget from here, which is
    exactly why the bug was invisible to every earlier automated test.
    """
    import tempfile

    real = pathlib.Path(__file__).resolve().parents[1] / "test-images" / "Photos_"
    heic_files = list(real.glob("*.HEIC")) if real.exists() else []
    if heic_files:
        im = ui.load_upload(str(heic_files[0]))
        assert im is not None and im.mode == "RGB" and min(im.size) > 0
        return

    # No private photos on this machine -- prove the same path on a
    # synthetic HEIC instead, so the test still means something in CI.
    import pillow_heif
    with tempfile.TemporaryDirectory() as td:
        path = pathlib.Path(td) / "probe.heic"
        src = Image.new("RGB", (200, 300), (90, 40, 150))
        pillow_heif.from_pillow(src).save(str(path), quality=90)
        im = ui.load_upload(str(path))
        assert im is not None and im.mode == "RGB" and im.size == (200, 300)


def test_load_upload_returns_none_for_no_file():
    assert ui.load_upload(None) is None


def test_the_process_tab_uploads_by_file_not_by_images_own_drop_zone():
    """Pins the mechanism, not just the outcome: a regression that swapped
    `gr.File` back for a plain `gr.Image` upload would pass every other test
    in this file (they all call `load_upload`/`process` directly) while
    silently reintroducing the exact bug this fix was for."""
    import inspect
    src = inspect.getsource(ui.build_process_tab)
    assert "gr.File(" in src
    assert ".heic" in src


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
        None, None, "Gown", ui._AUTO_FABRIC, "studio_ivory",
        ui._preset_choices()[:1], progress=_NoProgress(),
    ))[-1]
    assert result[0] is None
    assert "photograph" in result[1].lower()


def test_missing_backdrop_is_refused():
    img = Image.new("RGB", (80, 80), (180, 140, 140))
    result = list(ui.process(
        img, None, "Gown", ui._AUTO_FABRIC, "",
        ui._preset_choices()[:1], progress=_NoProgress(),
    ))[-1]
    assert result[0] is None
    assert "backdrop" in result[1].lower()


def test_missing_presets_is_refused():
    img = Image.new("RGB", (80, 80), (180, 140, 140))
    result = list(ui.process(
        img, None, "Gown", ui._AUTO_FABRIC, "studio_ivory", [],
        progress=_NoProgress(),
    ))[-1]
    assert result[0] is None
    assert "export size" in result[1].lower()


def test_export_stem_uses_the_original_filename_not_a_placeholder():
    """The fix for a real report: every export used to be named
    `source--<preset>.jpg` regardless of what was uploaded, because
    `process()` discarded the original filename and always wrote to a
    hardcoded temp path. A second photograph silently overwrote the first."""
    assert ui._export_stem("/tmp/abc123/IMG_8364.HEIC") == "img_8364"
    assert ui._export_stem("/tmp/abc123/My Lehenga Photo.jpg") == "my-lehenga-photo"
    assert ui._export_stem(None) == "dress"
    assert ui._export_stem("") == "dress"


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
        img, str(FIXTURE), "Gown", ui._AUTO_FABRIC, "champagne_silk",
        ui._preset_choices()[:2], progress=_NoProgress(),
    ))[-1]
    assert gallery is not None and len(gallery) == 2
    assert "colour_fidelity" in report
    assert "cutout_softness" in report
    # And the export actually landed under the real filename, not "source".
    from dressaug.config import OUT_DIR
    expected = OUT_DIR / f"{ui._export_stem(str(FIXTURE))}--portrait_2x3.jpg"
    assert expected.exists(), f"expected export at {expected}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("pass", fn.__name__)
    print(f"all {len(fns)} UI tests pass")
