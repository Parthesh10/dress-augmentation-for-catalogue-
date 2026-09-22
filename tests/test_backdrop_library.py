"""The persistent backdrop-photo library, added 2026-09-22 so an uploaded
backdrop photo survives past the run it was uploaded in.

Every test runs against a temporary library directory, never the real
`data/backdrop_library/` -- that directory may hold the operator's actual
saved photos on this machine, and a test suite that wrote into or counted
entries in it would be non-deterministic from one machine (or one day) to
the next.
"""
import contextlib
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from PIL import Image

from dressaug import backdrop_library as lib


@contextlib.contextmanager
def _isolated_library():
    """Point the module at a throwaway directory for the duration of the
    `with` block, then put it back -- module-level constants, so every
    function that reads `lib.LIBRARY_DIR` picks up the swap automatically."""
    orig_dir, orig_manifest = lib.LIBRARY_DIR, lib._MANIFEST
    with tempfile.TemporaryDirectory() as td:
        lib.LIBRARY_DIR = pathlib.Path(td) / "backdrop_library"
        lib._MANIFEST = lib.LIBRARY_DIR / "manifest.json"
        try:
            yield
        finally:
            lib.LIBRARY_DIR, lib._MANIFEST = orig_dir, orig_manifest


def test_add_then_list_round_trips():
    with _isolated_library():
        im = Image.new("RGB", (400, 600), (90, 140, 200))
        key = lib.add(im, "showroom wall")
        entries = lib.list_entries()
        assert len(entries) == 1
        assert entries[0].key == key
        assert entries[0].label == "showroom wall"
        assert entries[0].path.exists()


def test_add_is_idempotent_for_identical_content():
    """The same photo uploaded twice -- even under a different label, the
    way re-uploading the same file from a different folder might arrive --
    must not create a second library entry."""
    with _isolated_library():
        im = Image.new("RGB", (300, 300), (10, 200, 90))
        key_a = lib.add(im, "first label")
        key_b = lib.add(im.copy(), "second label")
        assert key_a == key_b
        assert len(lib.list_entries()) == 1
        # The first label wins -- `add` does not overwrite an existing entry.
        assert lib.list_entries()[0].label == "first label"


def test_add_of_different_photos_creates_separate_entries():
    with _isolated_library():
        lib.add(Image.new("RGB", (200, 200), (255, 0, 0)), "red")
        lib.add(Image.new("RGB", (200, 200), (0, 255, 0)), "green")
        assert len(lib.list_entries()) == 2


def test_remove_deletes_file_and_manifest_entry():
    with _isolated_library():
        key = lib.add(Image.new("RGB", (100, 100), (50, 50, 50)), "to remove")
        path = lib.LIBRARY_DIR / f"{key}.jpg"
        assert path.exists()
        lib.remove(key)
        assert not path.exists()
        assert lib.list_entries() == []


def test_remove_of_an_unknown_key_does_not_raise():
    with _isolated_library():
        lib.remove("not-a-real-key")  # must be a no-op, not an error


def test_list_skips_an_entry_whose_file_was_deleted_by_hand():
    """Defensive: if a photo is removed from disk without going through
    `remove()` (a person cleaning up the folder directly), `list_entries`
    must not offer a backdrop that can no longer be loaded."""
    with _isolated_library():
        key = lib.add(Image.new("RGB", (100, 100), (10, 10, 10)), "gone")
        (lib.LIBRARY_DIR / f"{key}.jpg").unlink()
        assert lib.list_entries() == []


def test_thumbnail_is_resized_within_the_requested_box():
    with _isolated_library():
        entry_key = lib.add(Image.new("RGB", (2000, 3000), (120, 90, 60)), "big photo")
        entry = lib.list_entries()[0]
        assert entry.key == entry_key
        thumb = lib.thumbnail(entry, (220, 300))
        assert thumb.width <= 220 and thumb.height <= 300


def test_add_defaults_to_the_default_category():
    with _isolated_library():
        key = lib.add(Image.new("RGB", (200, 200), (10, 90, 40)), "a garden path")
        assert lib.list_entries()[0].category == lib.DEFAULT_CATEGORY
        assert lib.list_entries()[0].key == key


def test_add_respects_an_explicit_category():
    with _isolated_library():
        lib.add(Image.new("RGB", (200, 200), (200, 40, 10)), "a garden", category="Nature")
        assert lib.list_entries()[0].category == "Nature"


def test_add_rejects_an_unknown_category_by_falling_back_to_the_default():
    """A typo'd or programmer-error category must not silently corrupt the
    manifest with a value `list_entries(category=...)` can never match."""
    with _isolated_library():
        lib.add(Image.new("RGB", (200, 200), (5, 5, 5)), "oops", category="Outdoors")
        assert lib.list_entries()[0].category == lib.DEFAULT_CATEGORY


def test_list_entries_filters_by_category():
    with _isolated_library():
        lib.add(Image.new("RGB", (200, 200), (200, 200, 200)), "wall", category="Studio")
        lib.add(Image.new("RGB", (200, 200), (10, 120, 30)), "garden", category="Nature")
        studio = lib.list_entries(category="Studio")
        nature = lib.list_entries(category="Nature")
        both = lib.list_entries()
        assert [e.label for e in studio] == ["wall"]
        assert [e.label for e in nature] == ["garden"]
        assert len(both) == 2


def test_hash_image_is_stable_for_the_same_pixels():
    im = Image.new("RGB", (50, 50), (1, 2, 3))
    assert lib.hash_image(im) == lib.hash_image(im.copy())


def test_prefix_never_collides_with_a_preset_style_name():
    """Preset names are lowercase_underscore identifiers with no colon
    (`studio_ivory`, `midnight_velvet`, ...) -- the UI tells a library photo
    apart from a preset purely by this prefix, so the prefix itself must
    contain a character no preset name could ever contain."""
    from dressaug import backgrounds
    assert ":" in lib.PREFIX
    assert all(":" not in name for name in backgrounds.PRESETS)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("pass", fn.__name__)
    print(f"all {len(fns)} backdrop-library tests pass")
