"""A persistent library of the operator's own backdrop photographs.

Every "use your own backdrop photo" upload (Process tab or Compare tab) used
to live only for the run it was uploaded in -- close the app, or start a
second run, and it was gone, so the operator was re-uploading the same decor
photos every session. This module is the fix: uploads land here once and
stay picked-by-name (and shown-by-eye) in every run after, across restarts,
until removed.

Deliberately file-based, no database: this is a few dozen photos at most for
a single-operator local app, and `LIBRARY_DIR` is exactly the kind of thing
`data/` already holds and `.gitignore` already keeps off the remote (own
decor photos are the operator's private stock, same discipline as
`test-images/` and `data/incoming/`).

Content-hashed filenames so the same photo uploaded twice (the obvious thing
to happen once this exists) dedupes for free rather than accumulating
duplicates under different names.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .config import ROOT

LIBRARY_DIR = ROOT / "data" / "backdrop_library"
_MANIFEST = LIBRARY_DIR / "manifest.json"

#: Prefix on a backdrop's UI value that marks it as a library photo rather
#: than a procedural preset name -- `"studio_ivory"` vs `"photo:a1b2c3d4e5f6"`.
#: Chosen so it can never collide with a preset name (those are
#: lowercase_underscore identifiers with no colon) without needing a lookup.
PREFIX = "photo:"


#: The three ways a backdrop is offered, asked for directly (2026-09-22):
#: **Plain** -- the procedural presets (`backgrounds.py`), unaffected by
#: this module. **Studio** and **Nature** -- real photographs, saved here.
#: An operator's own upload defaults to "Studio" (the more common case --
#: their own venue/decor) but can be filed as either.
CATEGORIES = ("Studio", "Nature")
DEFAULT_CATEGORY = "Studio"


@dataclass(frozen=True)
class LibraryEntry:
    key: str
    label: str
    path: Path
    added: str
    category: str = DEFAULT_CATEGORY


def _read_manifest() -> dict:
    if not _MANIFEST.exists():
        return {}
    try:
        return json.loads(_MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_manifest(data: dict) -> None:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    _MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def hash_image(image: Image.Image) -> str:
    """A stable id for `image`'s pixels, independent of the filename it
    arrived under -- so re-uploading the same photo, even renamed, dedupes
    rather than adding a second copy. Public: the UI layer uses it too, to
    check whether a fresh upload already matches a saved library entry."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "JPEG", quality=92)
    return hashlib.sha1(buf.getvalue()).hexdigest()[:16]


def add(image: Image.Image, label: str, category: str = DEFAULT_CATEGORY) -> str:
    """Save `image` into the library, keyed by content hash. Returns the key.

    Safe to call on every upload unconditionally -- an identical photo
    already in the library is a no-op past the hash check, not a duplicate.
    `category` is only recorded on first save; re-adding an existing photo
    doesn't reclassify it.
    """
    key = hash_image(image)
    path = LIBRARY_DIR / f"{key}.jpg"
    if not path.exists():
        LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        # Full quality on save -- these are meant to stay HD source material
        # for full-resolution export, not just a thumbnail source.
        image.convert("RGB").save(path, "JPEG", quality=95)
    manifest = _read_manifest()
    if key not in manifest:
        manifest[key] = {
            "label": label or key,
            "category": category if category in CATEGORIES else DEFAULT_CATEGORY,
            "added": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _write_manifest(manifest)
    return key


def remove(key: str) -> None:
    manifest = _read_manifest()
    manifest.pop(key, None)
    _write_manifest(manifest)
    path = LIBRARY_DIR / f"{key}.jpg"
    if path.exists():
        path.unlink()


def list_entries(category: str | None = None) -> list[LibraryEntry]:
    """Every library photo still on disk, oldest first (the order they were
    added -- stable and predictable rather than alphabetical-by-hash).
    `category` filters to just "Studio" or "Nature" when given; `None`
    (the default) returns both. An entry saved before categories existed
    reads as `DEFAULT_CATEGORY` rather than raising or being dropped."""
    manifest = _read_manifest()
    out = []
    for key, meta in manifest.items():
        path = LIBRARY_DIR / f"{key}.jpg"
        if not path.exists():
            continue
        entry_category = meta.get("category", DEFAULT_CATEGORY)
        if category is not None and entry_category != category:
            continue
        out.append(LibraryEntry(
            key, meta.get("label", key), path, meta.get("added", ""), entry_category,
        ))
    out.sort(key=lambda e: e.added)
    return out


def load(key: str) -> Image.Image:
    return Image.open(LIBRARY_DIR / f"{key}.jpg").convert("RGB")


def thumbnail(entry: LibraryEntry, size: tuple[int, int]) -> Image.Image:
    im = load(entry.key)
    im.thumbnail(size)
    return im
