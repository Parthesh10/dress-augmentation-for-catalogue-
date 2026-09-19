"""Dress augmentation pipeline — see README.md and TASK.md."""

from __future__ import annotations

# HEIC/HEIF support, registered here rather than in stages.py or ui.py so it
# applies to *every* PIL.Image.open() call anything in this package makes --
# including the ones Gradio's own upload handling does internally before the
# UI's own code ever sees the file. Registering it downstream of that would
# be too late: a HEIC upload through the app fails inside Gradio, not inside
# dressaug.
#
# iPhones default to HEIC since iOS 11 (2017), and this catalogue's actual
# source photographs are exactly that -- see test-images/Photos_, 136 real
# HEIC files. Pillow has never shipped a HEIF decoder (patent licensing,
# not an oversight), so without this every photo straight off a phone fails
# at the first stage with "cannot identify image file".
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover -- see requirements.txt
    import warnings

    warnings.warn(
        "pillow-heif is not installed -- .heic/.heif photographs will fail "
        "to open. Run: .venv\\Scripts\\pip install pillow-heif",
        stacklevel=2,
    )
