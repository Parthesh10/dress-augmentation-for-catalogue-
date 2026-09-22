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
        None, None, "Gown", ui._AUTO_FABRIC, "studio_ivory", None, False, 88, 50, 95, 100, -25, 100, 100,
        ui._preset_choices()[:1], progress=_NoProgress(),
    ))[-1]
    assert result[0] is None
    assert "photograph" in result[1].lower()


def test_missing_backdrop_is_refused():
    img = Image.new("RGB", (80, 80), (180, 140, 140))
    result = list(ui.process(
        img, None, "Gown", ui._AUTO_FABRIC, "", None, False, 88, 50, 95, 100, -25, 100, 100,
        ui._preset_choices()[:1], progress=_NoProgress(),
    ))[-1]
    assert result[0] is None
    assert "backdrop" in result[1].lower()


def test_missing_presets_is_refused():
    img = Image.new("RGB", (80, 80), (180, 140, 140))
    result = list(ui.process(
        img, None, "Gown", ui._AUTO_FABRIC, "studio_ivory", None, False, 88, 50, 95, 100, -25, 100, 100, [],
        progress=_NoProgress(),
    ))[-1]
    assert result[0] is None
    assert "export size" in result[1].lower()


def test_a_custom_backdrop_photo_bypasses_the_missing_backdrop_refusal():
    """The other half of `test_missing_backdrop_is_refused`: an empty preset
    *name* must not be refused for lacking a backdrop when a custom photo
    stands in for it. Paired with an empty export-size list so this stays a
    fast guard-logic check rather than running the real (slow) pipeline --
    the *next* guard is expected to fire instead, and which one fires is
    exactly what this test is checking."""
    img = Image.new("RGB", (80, 80), (180, 140, 140))
    result = list(ui.process(
        img, None, "Gown", ui._AUTO_FABRIC, "", str(FIXTURE), False, 88, 50, 95, 100, -25, 100, 100, [],
        progress=_NoProgress(),
    ))[-1]
    assert result[0] is None
    assert "export size" in result[1].lower(), (
        f"expected the *next* guard (export size) to fire, not a backdrop "
        f"refusal, once a custom photo was given: {result[1]!r}"
    )


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
        img, str(FIXTURE), "Gown", ui._AUTO_FABRIC, "studio_ivory", None, False, 88, 50, 95, 100, -25, 100, 100,
        ui._preset_choices()[:2], progress=_NoProgress(),
    ))[-1]
    assert gallery is not None and len(gallery) == 2
    assert "colour_fidelity" in report
    assert "cutout_softness" in report
    # The lighting-harmonisation pass (2026-09-19) nudges the subject's own
    # colour toward the backdrop's -- this is the gate that proves it never
    # nudges far enough to fail the promise "the garment ships the colour it
    # was listed in". Checked against the pass mark specifically (see
    # ui.process's "✓" / "✗ FAILED"), since a failing gate still contains
    # the substring "colour_fidelity".
    assert "✓  colour_fidelity" in report, report
    # And the export actually landed under the real filename, not "source".
    from dressaug.config import OUT_DIR
    expected = OUT_DIR / f"{ui._export_stem(str(FIXTURE))}--portrait_2x3.jpg"
    assert expected.exists(), f"expected export at {expected}"


def test_a_custom_backdrop_photo_runs_through_the_real_pipeline():
    """2026-09-20: an operator asked to use their own backdrop photographs
    (event/decor style backgrounds far richer than this project's own
    procedural presets) rather than being limited to the built-in library.
    Proves the *whole* path, not just the guard logic above: an uploaded
    photograph reaches `stages.background`, gets used as the actual
    backdrop, and the export still clears every gate -- with no preset name
    involved anywhere.

    Slow, like the test above, and for the same reason: this is the one
    place a synthetic fixture can't stand in for a real matting pass."""
    if not FIXTURE.exists():
        print("  (skipped -- no fixture on disk; run dataset.cut_fixtures first)")
        return
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        # A synthetic photo stands in for an operator's own backdrop here --
        # the pipeline doesn't care what the pixels depict, only that they
        # arrived as an uploaded photograph rather than a preset name, which
        # is exactly the mechanism under test.
        bg_path = pathlib.Path(td) / "my-own-venue.jpg"
        Image.new("RGB", (1600, 2000), (210, 150, 90)).save(bg_path, quality=90)

        img = Image.open(FIXTURE).convert("RGB")
        # Manual floor mode (auto_floor=False) at 40, not the 95 default --
        # proves the UI's floor-line slider actually reaches the pipeline
        # (ctx.extra["custom_floor_frac"]), not only that the default value
        # happens to work. The automatic detector has its own tests in
        # test_ground.py; a flat synthetic colour field is not a meaningful
        # input for it.
        gallery, report, warnings = list(ui.process(
            img, str(FIXTURE), "Gown", ui._AUTO_FABRIC, "", str(bg_path), False, 88, 50, 40, 100, -25, 100, 100,
            ui._preset_choices()[:1], progress=_NoProgress(),
        ))[-1]
        assert gallery is not None and len(gallery) == 1
        assert "✓  colour_fidelity" in report, report


def test_compare_refuses_with_no_photographs():
    result = list(ui.compare_backdrops(None, "Gown", ui._AUTO_FABRIC, None,
                                       progress=_NoProgress()))[-1]
    assert result[0] == []
    assert "photograph" in result[1].lower()


def test_sheet_grid_lays_out_every_cell_and_survives_an_empty_list():
    """The contact sheet's own assembly, without matting: eleven labelled
    cells land in a 4-wide grid of the right size, and a failed
    photograph's empty sheet still renders (with just the title) rather
    than raising inside the generator."""
    cells = [(f"bg_{i}", Image.new("RGB", (300, 450), (i * 20, 90, 120))) for i in range(11)]
    sheet = ui._sheet_grid(cells, "test")
    cw, ch = ui._SHEET_CELL
    assert sheet.size == (ui._SHEET_COLS * cw, 3 * ch + 28)  # 11 cells -> 3 rows of 4
    empty = ui._sheet_grid([], "nothing")
    assert empty.size[0] == ui._SHEET_COLS * cw and empty.size[1] > 0


def test_the_compare_tab_takes_many_files_and_exists_in_the_app():
    """Pins the bulk mechanism at the widget level: the upload must be
    `file_count="multiple"`, and the tab must actually be wired into
    `build()` -- a `compare_backdrops` that works when called directly but
    was never attached to a button is not a feature."""
    import inspect
    src = inspect.getsource(ui.build_compare_tab)
    assert 'file_count="multiple"' in src
    assert "compare_backdrops" in src
    assert "build_compare_tab()" in inspect.getsource(ui.build)


def test_compare_runs_two_real_photographs_into_two_sheets():
    """The bulk claim, for real: two photographs in, two contact sheets
    out, each with every built-in backdrop on it -- and the first sheet
    arrives before the second matte starts (the generator yields per
    photograph). Slow: two real mattes. Deliberately not skipped when the
    fixture exists, because "bulk" is exactly the thing a single-photo test
    cannot prove."""
    if not FIXTURE.exists():
        print("  (skipped -- no fixture on disk)")
        return
    import tempfile
    from dressaug import backgrounds
    with tempfile.TemporaryDirectory() as td:
        # The same fixture twice, under two names -- what matters is two
        # independent runs, not two different garments.
        a = pathlib.Path(td) / "first-dress.png"
        b = pathlib.Path(td) / "second-dress.png"
        Image.open(FIXTURE).convert("RGB").save(a)
        Image.open(FIXTURE).convert("RGB").save(b)
        yields = list(ui.compare_backdrops([str(a), str(b)], "Gown", ui._AUTO_FABRIC, None,
                                           progress=_NoProgress()))
    # Progressive: a yield with one sheet must precede the final one with two.
    counts = [len(y[0]) for y in yields]
    assert 1 in counts and counts[-1] == 2, counts
    sheets, status = yields[-1]
    assert "2/2" in status
    captions = [c for _, c in sheets]
    assert captions == ["first-dress", "second-dress"]
    # Each sheet is a real grid sized for all the presets.
    cw, ch = ui._SHEET_CELL
    n = len(backgrounds.PRESETS)
    rows = (n + ui._SHEET_COLS - 1) // ui._SHEET_COLS
    for im, _ in sheets:
        assert im.size == (ui._SHEET_COLS * cw, rows * ch + 28)


import contextlib
import tempfile as _tempfile

from dressaug import backdrop_library


@contextlib.contextmanager
def _isolated_library():
    """Same isolation as `test_backdrop_library.py` -- these tests must
    never read or write the real `data/backdrop_library/`, which may hold
    the operator's actual saved photos on this machine."""
    orig_dir, orig_manifest = backdrop_library.LIBRARY_DIR, backdrop_library._MANIFEST
    with _tempfile.TemporaryDirectory() as td:
        backdrop_library.LIBRARY_DIR = pathlib.Path(td) / "backdrop_library"
        backdrop_library._MANIFEST = backdrop_library.LIBRARY_DIR / "manifest.json"
        try:
            yield
        finally:
            backdrop_library.LIBRARY_DIR = orig_dir
            backdrop_library._MANIFEST = orig_manifest


def test_combined_backdrop_entries_is_presets_only_when_the_library_is_empty():
    with _isolated_library():
        entries = ui._combined_backdrop_entries()
        assert [v for _, _, v in entries] == ui._BACKDROP_NAMES


def test_combined_backdrop_entries_appends_library_photos_after_presets():
    with _isolated_library():
        backdrop_library.add(Image.new("RGB", (300, 400), (200, 120, 60)), "my venue")
        entries = ui._combined_backdrop_entries()
        assert len(entries) == len(ui._BACKDROP_NAMES) + 1
        thumb, label, value = entries[-1]
        assert "my venue" in label
        assert value.startswith(backdrop_library.PREFIX)


def test_backdrop_gallery_select_returns_the_matching_value():
    """Pins the fix for a real gap: the gallery's caption promised "pick by
    eye" since it was introduced, but nothing connected a click to the
    `Backdrop` radio until now -- this is the function that click wires to."""
    class _Evt:
        index = 0
    result = ui._on_backdrop_gallery_select(_Evt())
    # index 0 is the first (darkest) built-in preset in `_BACKDROP_NAMES`'s
    # own order, which `_combined_backdrop_entries` preserves.
    assert result["value"] == ui._BACKDROP_NAMES[0]


def test_backdrop_gallery_select_is_a_noop_for_an_out_of_range_index():
    class _Evt:
        index = 9999
    result = ui._on_backdrop_gallery_select(_Evt())
    assert "value" not in result


def test_process_ui_resolves_a_library_backdrop_to_its_saved_file():
    """`_process_ui` is what the Process button actually calls; this proves
    a `"photo:<hash>"` radio value reaches `process()` as a real custom
    backdrop path, not as a literal (invalid) background name."""
    with _isolated_library():
        key = backdrop_library.add(
            Image.new("RGB", (200, 300), (80, 80, 200)), "test venue")
        img = Image.new("RGB", (80, 80), (180, 140, 140))
        result = list(ui._process_ui(
            img, None, "Gown", ui._AUTO_FABRIC, backdrop_library.PREFIX + key, None,
            False, 88, 50, 95, 100, -25, 100, 100, [],
            progress=_NoProgress(),
        ))[-1]
        # Empty preset list -- this only needs to prove the guard *after*
        # the backdrop check fires (export size), not a backdrop refusal,
        # which is exactly what would happen if the library value leaked
        # into `process()` unresolved.
        assert result[0] is None
        assert "export size" in result[1].lower(), result[1]


def test_save_uploaded_backdrop_and_refresh_is_a_noop_for_no_file():
    result = ui._save_uploaded_backdrop_and_refresh(None)
    assert len(result) == 2


def test_save_uploaded_backdrop_and_refresh_adds_to_the_library():
    with _isolated_library():
        with _tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "my-decor.jpg"
            Image.new("RGB", (300, 400), (210, 150, 90)).save(path, quality=90)
            radio_update, gallery_update = ui._save_uploaded_backdrop_and_refresh(str(path))
        assert radio_update["value"].startswith(backdrop_library.PREFIX)
        assert len(backdrop_library.list_entries()) == 1
        assert len(gallery_update["value"]) == len(ui._BACKDROP_NAMES) + 1


def test_preview_library_backdrop_returns_the_saved_photo():
    with _isolated_library():
        key = backdrop_library.add(Image.new("RGB", (300, 400), (10, 200, 10)), "greenish")
        preview = ui._preview_library_backdrop(key)
        assert preview is not None
        assert preview.size[0] > 0 and preview.size[1] > 0


def test_preview_library_backdrop_is_none_for_no_selection_or_unknown_key():
    with _isolated_library():
        assert ui._preview_library_backdrop(None) is None
        assert ui._preview_library_backdrop("not-a-real-key") is None


def test_remove_library_backdrop_removes_it_and_refreshes_choices():
    with _isolated_library():
        key = backdrop_library.add(Image.new("RGB", (100, 100), (1, 2, 3)), "to remove")
        radio_update, gallery_update, list_update, preview_update, status = (
            ui._remove_library_backdrop(key))
        assert backdrop_library.list_entries() == []
        assert len(radio_update["choices"]) == len(ui._BACKDROP_NAMES)
        assert list_update["choices"] == []
        assert preview_update["value"] is None
        assert "removed" in status.lower()


def test_remove_library_backdrop_with_no_selection_refuses_without_raising():
    with _isolated_library():
        result = ui._remove_library_backdrop(None)
        assert "pick" in result[-1].lower()


def test_compare_backdrops_ui_includes_saved_library_photos_automatically():
    """The wrapper the Compare button actually calls: a backdrop saved to
    the library in an earlier run must show up in this run's comparison
    without being re-uploaded -- same persistence promise as the Process
    tab's radio, applied to the bulk tab."""
    with _isolated_library():
        backdrop_library.add(Image.new("RGB", (300, 400), (30, 90, 140)), "saved venue")
        result = list(ui._compare_backdrops_ui(None, "Gown", ui._AUTO_FABRIC, None,
                                               progress=_NoProgress()))[-1]
        # No photograph uploaded -- the guard fires before any backdrop is
        # even looked at, which is exactly why this only needs to prove the
        # wrapper doesn't crash while merging in the library before that
        # guard runs, not that a sheet gets built.
        assert result[0] == []


def test_sanitize_filename_strips_unsafe_characters_and_caps_length():
    assert ui._sanitize_filename("Studio - White wall") == "Studio - White wall"
    cleaned = ui._sanitize_filename("a/b:c*d?e")
    assert "/" not in cleaned and ":" not in cleaned and "*" not in cleaned
    assert ui._sanitize_filename("") == "backdrop"
    assert len(ui._sanitize_filename("x" * 200)) == 60


def test_compare_backdrops_ui_captions_library_photos_by_label_not_hash():
    """Pins the fix for a real bug found on the first bulk run that
    included library photos: `compare_backdrops` captions each sheet cell
    from its input file's own stem, and a library photo's real filename on
    disk is its content hash -- so without renaming, every library
    backdrop's caption came back as an unreadable hash string instead of
    its label. Checked by intercepting the call to the real
    `compare_backdrops`, not by running a real (slow) matte."""
    with _isolated_library():
        key = backdrop_library.add(
            Image.new("RGB", (300, 400), (80, 150, 90)), "White wall", category="Studio")
        captured = {}

        def _fake_compare_backdrops(upload_paths, garment_label, fabric_label,
                                     extra_paths, progress=None):
            captured["extra_paths"] = list(extra_paths)
            return iter(())

        orig = ui.compare_backdrops
        ui.compare_backdrops = _fake_compare_backdrops
        try:
            list(ui._compare_backdrops_ui(None, "Gown", ui._AUTO_FABRIC, None,
                                          progress=_NoProgress()))
        finally:
            ui.compare_backdrops = orig

        stems = [pathlib.Path(p).stem for p in captured["extra_paths"]]
        assert any("White wall" in s for s in stems), stems
        assert key not in stems


def test_status_tab_no_longer_carries_the_stale_dark_backdrop_warning():
    """Pins the fix for stale copy: 'Prefer the lighter backdrops until
    this is fixed' referred to the edge-halo bug that §5/P0 already fixed
    (2026-09-19), but the status page kept telling operators to avoid dark
    backdrops for a bug that no longer existed."""
    import inspect
    src = inspect.getsource(ui.build_status_tab)
    assert "Prefer the lighter backdrops" not in src
    assert "background-removal cleanup not finished" not in src


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("pass", fn.__name__)
    print(f"all {len(fns)} UI tests pass")
