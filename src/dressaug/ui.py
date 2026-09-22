"""Operator UI — one app: add a dress, get catalogue images back.

    $env:PYTHONPATH="src"
    .venv\\Scripts\\python.exe -m dressaug.ui

Dress-specific only. Nothing here reads or calls the sibling jewellery
project — the two are separate software that happen to share a parent folder.

Two tools are live: background removal and background replacement. A third,
recolouring, is not built (Phase 3) and its control is shown disabled rather
than hidden, so "what does this app do today" is answered by looking at it
rather than by reading a doc.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import time
import traceback
from pathlib import Path

import gradio as gr
import numpy as np
from PIL import Image, ImageOps

from . import backdrop_library, backgrounds, stages  # noqa: F401 -- importing stages registers them
from .cli import use_utf8_console
from .config import EXPORT_PRESETS, Fabric, Garment, Graph, JobConfig
from .graphs import stages_for
from .pipeline import ArtifactStore, Context, JobManifest, PipelineRunner

use_utf8_console()

_GARMENT_LABELS = {
    Garment.GOWN: "Gown",
    Garment.PARTY_DRESS: "Party dress",
    Garment.LEHENGA: "Lehenga",
    Garment.SAREE: "Saree",
    Garment.ANARKALI: "Anarkali",
}
_FABRIC_LABELS = {
    Fabric.OPAQUE: "Opaque (cotton, crepe, structured lining)",
    Fabric.SHEEN: "Sheen (satin, silk, taffeta)",
    Fabric.VELVET: "Velvet",
    Fabric.EMBELLISHED: "Embellished (sequins, zari, heavy beading)",
    Fabric.LACE: "Lace / net",
    Fabric.SHEER: "Sheer (chiffon, georgette, organza, tulle)",
}
_AUTO_FABRIC = "Auto (from garment type)"


def _garment_choices() -> list[str]:
    return [_GARMENT_LABELS[g] for g in Garment]


def _fabric_choices() -> list[str]:
    return [_AUTO_FABRIC] + [_FABRIC_LABELS[f] for f in Fabric]


def _garment_from_label(label: str) -> Garment:
    return next(g for g, l in _GARMENT_LABELS.items() if l == label)


def _fabric_from_label(label: str) -> Fabric | None:
    if label == _AUTO_FABRIC:
        return None
    return next(f for f, l in _FABRIC_LABELS.items() if l == label)


def _backdrop_gallery() -> list[tuple[Image.Image, str]]:
    """A thumbnail per preset, for picking a backdrop by eye rather than by
    name. Rendered once at import time -- these are cheap (~50ms each) and
    there are only 11 of them."""
    out = []
    for name in sorted(backgrounds.PRESETS, key=backgrounds.key_luminance):
        thumb = backgrounds.render(name, (220, 300), seed=0)
        out.append((thumb, name))
    return out


_BACKDROP_THUMBS = _backdrop_gallery()
_BACKDROP_NAMES = [n for _, n in _BACKDROP_THUMBS]


def _combined_backdrop_entries() -> list[tuple[Image.Image, str, str]]:
    """(thumbnail, display label, internal value) for every backdrop on
    offer right now, grouped into the three categories asked for directly
    (2026-09-22) -- **Plain** (the built-in procedural presets, dark ->
    light, as before, `value == name`), **Studio** and **Nature** (real
    photographs saved to the operator's own library, oldest-added first
    within each, `value == "photo:<hash>"`, see `backdrop_library.PREFIX`).
    The label is prefixed with its category so the grouping is visible in
    a flat Radio/Gallery list, which has no native section-header widget.

    Recomputed on call rather than cached at import time, unlike
    `_BACKDROP_THUMBS` above -- the library can grow while the app is
    running, and the whole point of it is that a newly saved photo shows up
    without a restart.
    """
    out = [(thumb, f"🎨 Plain — {name}", name) for thumb, name in _BACKDROP_THUMBS]
    icons = {"Studio": "🏛️", "Nature": "🌿"}
    for category in backdrop_library.CATEGORIES:
        for entry in backdrop_library.list_entries(category=category):
            icon = icons.get(category, "🖼️")
            out.append((
                backdrop_library.thumbnail(entry, (220, 300)),
                f"{icon} {category} — {entry.label}",
                backdrop_library.PREFIX + entry.key,
            ))
    return out


def _library_choices() -> list[tuple[str, str]]:
    """(label, key) for the "remove a saved photo" dropdown -- key, not the
    `photo:`-prefixed value, since `backdrop_library.remove` takes the bare
    hash."""
    return [(e.label, e.key) for e in backdrop_library.list_entries()]


def _export_stem(upload_path: str | None) -> str:
    """A filesystem-safe name derived from what was actually uploaded.

    `upload_path` is `gr.File`'s own cached copy, and Gradio's upload route
    already sanitises and preserves the original filename as that cache
    entry's basename (`gradio/route_utils.py::upload_fn`) -- so this needs
    no filename of its own, only to read the one already there rather than
    discard it. Before this, every export was named `source--<preset>.jpg`
    regardless of what was uploaded, and a second photograph silently
    overwrote the first.
    """
    if not upload_path:
        return "dress"
    stem = Path(upload_path).stem.replace(" ", "-").lower()[:48]
    return stem or "dress"


def process(
    image,
    upload_path,
    garment_label: str,
    fabric_label: str,
    backdrop_name: str,
    custom_backdrop_path,
    auto_place: bool,
    fill_pct,
    x_pct,
    floor_frac_pct,
    blur_pct,
    light_dir_pct,
    tint_pct,
    exposure_pct,
    preset_labels: list[str],
    depth_blur_pct=100,
    finishing_pct=100,
    progress=gr.Progress(),
):
    """One garment through phases 1 and 2. A generator so the operator sees
    progress rather than a frozen button for 60-180 seconds."""
    if image is None:
        yield None, "Add a photograph first.", ""
        return
    if not backdrop_name and not custom_backdrop_path:
        yield None, "Pick a backdrop, or upload your own.", ""
        return
    if not preset_labels:
        yield None, "Pick at least one export size.", ""
        return

    custom_backdrop = load_upload(custom_backdrop_path)

    progress(0.02, desc="preparing")
    yield None, "starting…", ""

    with tempfile.TemporaryDirectory() as td:
        src_path = Path(td) / f"{_export_stem(upload_path)}.png"
        image.save(src_path)

        cfg = JobConfig(
            graph=Graph.FLAT,
            garment=_garment_from_label(garment_label),
            fabric=_fabric_from_label(fabric_label),
            background=backdrop_name or "custom",
            presets=[_PRESET_LABEL_TO_NAME[p] for p in preset_labels],
        )

        job_id = f"ui-{int(time.time())}"
        store = ArtifactStore(job_id)
        manifest = JobManifest(
            job_id=job_id, source=str(src_path), profile=cfg.profile,
            config={"graph": cfg.graph.value, "garment": cfg.garment.value,
                    "fabric": cfg.resolved_fabric().value,
                    "background": "custom photo" if custom_backdrop is not None
                    else cfg.background},
        )
        ctx = Context(
            job_id=job_id, source_path=src_path, cfg=cfg,
            store=store, manifest=manifest,
        )
        if custom_backdrop is not None:
            ctx.extra["custom_background"] = custom_backdrop
        if not auto_place:
            # Leaving these unset is what asks `stages.background` to run
            # the ground detector (floor line and size) and `compose` to
            # use its defaults (position). Setting them is the override --
            # together, so "manual placement" has one clear meaning: where
            # the figure stands and how big it is, exactly as the sliders
            # read.
            ctx.extra["custom_floor_frac"] = float(floor_frac_pct) / 100.0
            ctx.extra["subject_fill"] = float(fill_pct) / 100.0
            ctx.extra["subject_x"] = float(x_pct) / 100.0
        # Lighting -- seam softening, light direction, colour tint, exposure
        # match, and background blur -- used to live inside the `not
        # auto_place` guard above, gated by the *placement* checkbox even
        # though none of them place anything. Since "Place automatically" is
        # the recommended, default-on setting, that meant every one of these
        # sliders had **no effect at all** unless the operator also switched
        # placement to manual -- reported directly, 2026-09-22, as "moving
        # the exposure slider does nothing": it wasn't a weak effect, it was
        # never being read. Independent of `auto_place` now, so the ground
        # detector can still own where the figure stands while these still
        # apply. See TASK.md §1o.
        ctx.extra["seam_blur_strength"] = float(blur_pct) / 100.0
        # -100..100 on the slider maps to the same +-0.4 range
        # `infer_key_direction` itself clips to.
        ctx.extra["light_dir_x"] = float(light_dir_pct) / 100.0 * 0.4
        ctx.extra["tint_strength"] = float(tint_pct) / 100.0
        ctx.extra["exposure_strength"] = float(exposure_pct) / 100.0
        ctx.extra["depth_blur_strength"] = float(depth_blur_pct) / 100.0
        ctx.extra["finishing_strength"] = float(finishing_pct) / 100.0

        steps = stages_for(cfg.graph)
        step_progress = {"ingest": 0.05, "matte": 0.15, "background": 0.55,
                          "composite": 0.75, "gates": 0.85, "export": 0.9}

        def on_progress(name, i, n):
            frac = step_progress.get(name, i / max(n, 1))
            label = {"matte": "removing background — the slow step",
                      "background": "generating backdrop",
                      "composite": "placing the garment",
                      "gates": "checking colour and framing",
                      "export": "writing files"}.get(name, name)
            progress(frac, desc=label)

        try:
            m = PipelineRunner().run(ctx, steps, on_progress)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the operator, not hidden
            yield None, f"Failed: {exc}", traceback.format_exc(limit=3)
            return

        m.write(store.dir / "manifest.json")

        if m.status != "ok":
            note = next((s.note for s in m.stages if s.status == "failed"), "unknown error")
            yield None, f"Failed: {note}", ""
            return

        # Captioned by preset -- before this, two export sizes of the same
        # photo showed as two visually-identical thumbnails with no way to
        # tell which was which, which is exactly the kind of thing that
        # reads as "no change happened" even when the pipeline worked.
        # `m.outputs` and `cfg.presets` share the insertion order `export()`
        # wrote them in (dict order), so zipping the two is safe.
        gallery = [
            (Image.open(p).convert("RGB"),
             f"{name}  ({EXPORT_PRESETS[name].width}×{EXPORT_PRESETS[name].height})")
            for name, p in zip(cfg.presets, m.outputs)
        ]

        lines = []
        for g in m.gates:
            mark = "✓" if g.passed else "✗ FAILED"
            lines.append(f"{mark}  {g.name}: {g.detail}")
        report = "\n".join(lines) if lines else "(no gates recorded)"

        warn_lines = "\n".join(f"⚠ {w}" for w in m.warnings) if m.warnings else ""

        progress(1.0, desc="done")
        yield gallery, report, warn_lines


def _process_ui(
    image, upload_path, garment_label, fabric_label, backdrop_name, custom_backdrop_path,
    auto_place, fill_pct, x_pct, floor_frac_pct, blur_pct, light_dir_pct, tint_pct,
    exposure_pct, preset_labels, depth_blur_pct=100, finishing_pct=100,
    progress=gr.Progress(),
):
    """What the Process button actually calls. A thin wrapper, not a
    rewrite of `process()`: if the operator's `Backdrop` choice is a saved
    library photo (`"photo:<hash>"`, see `backdrop_library.PREFIX`) rather
    than a preset name, resolve it to that photo's file on disk and hand it
    to `process()` exactly the way an "own backdrop photo" upload already
    works -- `process()` itself, and every test pinned against it, never
    needs to know the library exists.
    """
    if backdrop_name and backdrop_name.startswith(backdrop_library.PREFIX):
        key = backdrop_name[len(backdrop_library.PREFIX):]
        path = backdrop_library.LIBRARY_DIR / f"{key}.jpg"
        if path.exists():
            custom_backdrop_path = str(path)
        backdrop_name = ""
    yield from process(
        image, upload_path, garment_label, fabric_label, backdrop_name, custom_backdrop_path,
        auto_place, fill_pct, x_pct, floor_frac_pct, blur_pct, light_dir_pct, tint_pct,
        exposure_pct, preset_labels, depth_blur_pct, finishing_pct, progress=progress,
    )


def _save_uploaded_backdrop_and_refresh(file_path, category=backdrop_library.DEFAULT_CATEGORY):
    """Fires when a photo lands in "Or use your own backdrop photo": saves
    it into the persistent library (a no-op if it's already there -- see
    `backdrop_library.add`), under the chosen Studio/Nature category, then
    hands back fresh choices for the `Backdrop` radio and gallery so the
    photo is pickable by name or by eye immediately, this run, with no
    restart and no second upload later.

    `gr.update()` (a no-op) when the file input is cleared, so clearing the
    upload never wipes the radio/gallery back to presets-only.
    """
    if not file_path:
        return gr.update(), gr.update()
    image = load_upload(file_path)
    label = f"Your photo: {Path(file_path).stem}"
    key = backdrop_library.add(image, label, category=category)
    entries = _combined_backdrop_entries()
    radio_update = gr.update(
        choices=[(label, value) for _, label, value in entries],
        value=backdrop_library.PREFIX + key,
    )
    gallery_update = gr.update(value=[(thumb, label) for thumb, label, _ in entries])
    return radio_update, gallery_update


def _on_backdrop_gallery_select(evt: gr.SelectData):
    """The gallery was captioned "Pick by eye ... or by name here" since
    §1a, but nothing ever actually connected a click in the gallery to the
    `Backdrop` radio -- clicking a thumbnail only opened Gradio's own
    built-in single-image preview, with no effect on which backdrop would
    actually be used. That gap is what made the gallery decorative rather
    than a real second way to choose, and it's fixed here, not by removing
    the claim.
    """
    entries = _combined_backdrop_entries()
    if evt.index is None or evt.index >= len(entries):
        return gr.update()
    _, _, value = entries[evt.index]
    return gr.update(value=value)


def _preview_library_backdrop(key):
    """Fires when "Saved photo" changes in the library accordion -- shows
    what the selected photo actually looks like before the operator decides
    whether to remove it, rather than picking blind off a filename-derived
    label."""
    if not key:
        return None
    entries = {e.key: e for e in backdrop_library.list_entries()}
    entry = entries.get(key)
    if entry is None:
        return None
    return backdrop_library.thumbnail(entry, (400, 400))


def _remove_library_backdrop(key):
    """"Remove a saved photo" in the Process tab's library accordion."""
    if not key:
        return gr.update(), gr.update(), gr.update(), gr.update(), "Pick a saved photo to remove first."
    backdrop_library.remove(key)
    entries = _combined_backdrop_entries()
    radio_update = gr.update(choices=[(label, value) for _, label, value in entries])
    gallery_update = gr.update(value=[(thumb, label) for thumb, label, _ in entries])
    list_update = gr.update(choices=_library_choices(), value=None)
    preview_update = gr.update(value=None)
    return radio_update, gallery_update, list_update, preview_update, "Removed."


#: Contact-sheet cell size. Preview quality on purpose -- the sheet is for
#: deciding which backdrop, and the Process tab makes the real file.
_SHEET_CELL = (260, 400)
_SHEET_COLS = 4
#: Working resolution for each composite in the sheet. Well below export
#: size: eleven composites per photograph, and every one of them is a
#: throwaway once a backdrop is picked.
_SHEET_CANVAS_LONG = 900


def _sheet_grid(cells: list[tuple[str, Image.Image]], title: str) -> Image.Image:
    """Assemble labelled thumbnails into one image, `_SHEET_COLS` across."""
    from PIL import ImageDraw
    cw, ch = _SHEET_CELL
    rows = max((len(cells) + _SHEET_COLS - 1) // _SHEET_COLS, 1)
    sheet = Image.new("RGB", (_SHEET_COLS * cw, rows * ch + 28), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    d.text((8, 7), title, fill=(235, 235, 235))
    for i, (label, im) in enumerate(cells):
        t = im.copy()
        t.thumbnail((cw - 10, ch - 30))
        x, y = (i % _SHEET_COLS) * cw, 28 + (i // _SHEET_COLS) * ch
        sheet.paste(t, (x + (cw - t.width) // 2, y + 22))
        d.text((x + 6, y + 4), label, fill=(255, 235, 120))
    return sheet


def compare_backdrops(
    upload_paths,
    garment_label: str,
    fabric_label: str,
    extra_backdrop_paths,
    progress=gr.Progress(),
):
    """One or many garment photographs, each against every built-in backdrop
    (plus any backdrop photos the operator adds), as one contact sheet per
    photograph. Preview only: nothing is exported. Pick a backdrop here,
    then make the real file on the Process tab.

    The expensive step -- matting -- runs once per photograph; the eleven
    (or more) composites that follow reuse it, so a sheet costs one matte
    plus a few seconds. That is also why this is the bulk path: N
    photographs is N mattes, not N x 11.

    A generator: each finished sheet is yielded as it completes, so a
    batch of twenty photographs shows its first result after the first
    matte rather than after the twentieth.
    """
    if not upload_paths:
        yield [], "Add at least one photograph."
        return
    if isinstance(upload_paths, (str, Path)):
        upload_paths = [upload_paths]
    extra_paths = extra_backdrop_paths or []
    if isinstance(extra_paths, (str, Path)):
        extra_paths = [extra_paths]

    garment = _garment_from_label(garment_label)
    fabric = _fabric_from_label(fabric_label)
    preset_names = list(_BACKDROP_NAMES)
    extras = [(Path(p).stem, load_upload(str(p))) for p in extra_paths]
    n_bg = len(preset_names) + len(extras)
    total = len(upload_paths)

    sheets: list[tuple[Image.Image, str]] = []
    for pi, upath in enumerate(upload_paths):
        stem = _export_stem(str(upath))
        base = pi / total
        progress(base, desc=f"{stem}: removing background ({pi + 1}/{total})")
        with tempfile.TemporaryDirectory() as td:
            src_path = Path(td) / f"{stem}.png"
            load_upload(str(upath)).save(src_path)
            cfg = JobConfig(graph=Graph.FLAT, garment=garment, fabric=fabric,
                            background=preset_names[0])
            job_id = f"sheet-{stem[:16]}-{int(time.time())}"
            ctx = Context(
                job_id=job_id, source_path=src_path, cfg=cfg,
                store=ArtifactStore(job_id),
                manifest=JobManifest(job_id=job_id, source=str(src_path), profile=cfg.profile),
            )
            try:
                ctx = stages.ingest(ctx)
                ctx = stages.matte(ctx)
            except Exception as exc:  # noqa: BLE001 -- surfaced, not hidden
                sheets.append((_sheet_grid([], f"{stem}: FAILED -- {exc}"), stem))
                yield [s for s in sheets], f"{stem} failed: {exc}"
                continue

            # Shrink the working canvas for the sheet: `stages.background`
            # sizes the canvas from the source, so a smaller source means
            # smaller (faster) composites without touching the stage itself.
            w, h = ctx.source.size
            scale = _SHEET_CANVAS_LONG / max(w, h)
            if scale < 1:
                small = (max(int(w * scale), 64), max(int(h * scale), 64))
                ctx.source = ctx.source.resize(small, Image.LANCZOS)
                ctx.product = ctx.product.resize(small, Image.LANCZOS)
                ctx.alpha = np.asarray(
                    Image.fromarray((ctx.alpha * 255).astype(np.uint8), "L")
                    .resize(small, Image.LANCZOS), dtype=np.float32) / 255.0

            keep = {k: v for k, v in ctx.extra.items()
                    if k in ("matting_device", "matte_coverage", "partial_alpha_fraction")}
            cells: list[tuple[str, Image.Image]] = []
            jobs = [(n, None) for n in preset_names] + [(n, im) for n, im in extras]
            for bi, (name, custom_im) in enumerate(jobs):
                progress(base + (bi + 1) / n_bg / total,
                         desc=f"{stem}: {name} ({bi + 1}/{n_bg})")
                ctx.extra = dict(keep)
                ctx.cfg.background = name if custom_im is None else "custom"
                if custom_im is not None:
                    ctx.extra["custom_background"] = custom_im
                ctx.background = None
                ctx.composited = None
                ctx.manifest.warnings = []
                try:
                    ctx = stages.background(ctx)
                    ctx = stages.composite(ctx)
                    label = name
                    if ctx.extra.get("ground_usable") is False:
                        label = f"{name}  [!]"
                    cells.append((label, ctx.composited))
                except Exception as exc:  # noqa: BLE001
                    cells.append((f"{name}: failed", Image.new("RGB", (200, 300), (60, 20, 20))))
            sheets.append((_sheet_grid(cells, stem), stem))
            yield [s for s in sheets], f"{len(sheets)}/{total} done"
    progress(1.0, desc="done")
    yield [s for s in sheets], f"{len(sheets)}/{total} done"


def _build_preset_label_map() -> dict[str, str]:
    return {f"{name}  ({p.width}×{p.height})": name
            for name, p in EXPORT_PRESETS.items()}


#: Built once at import time, not as a side effect of constructing the UI --
#: `process()` must work whether or not `build()` has run first (it is called
#: directly by tests, and would otherwise depend on Gradio widget construction
#: order to populate a lookup table it needs).
_PRESET_LABEL_TO_NAME: dict[str, str] = _build_preset_label_map()


def _preset_choices() -> list[str]:
    return list(_PRESET_LABEL_TO_NAME)


def load_upload(file_path: str | None):
    """Decode whatever was dropped in, for the preview.

    Routed through `gr.File` rather than `gr.Image`'s own drop zone
    specifically because of `.heic`/`.heif`: `gr.Image`'s upload widget
    rejects a file client-side if the browser's own MIME sniff of it does
    not start with "image/", and on Windows a HEIC file's browser-reported
    MIME type is commonly empty -- there is no OS-level file association for
    it -- so the file never reaches this process at all, regardless of
    `dressaug`'s own HEIF support. `gr.File` with an explicit `file_types`
    list validates by *filename extension* on the server instead, which is
    unaffected by what the browser thinks the MIME type is.

    Once the file has actually arrived, decoding it is exactly what
    `stages.ingest` does -- EXIF-transpose, then RGB -- so the preview shown
    here is honest about what the pipeline will actually see, not a
    browser-rendered guess.
    """
    if file_path is None:
        return None
    return ImageOps.exif_transpose(Image.open(file_path)).convert("RGB")


def build_process_tab() -> None:
    with gr.Row():
        with gr.Column(scale=2):
            #: The required path, start to finish, grouped into one visual
            #: card so it reads as "the form" -- everything optional (a
            #: custom backdrop, saved-photo management, manual placement
            #: overrides) lives below it instead of interleaved with it.
            #: Added 2026-09-23: reported directly as "too many options,
            #: unclear what does what" once every accordion in this tab had
            #: accumulated -- numbered steps and one bordered group are the
            #: fix, not a rewrite of what any control does.
            gr.Markdown("#### ① Your photograph")
            with gr.Group():
                upload = gr.File(
                    label="Dress photograph",
                    file_types=["image", ".heic", ".heif"],
                    height=120,
                )
                image = gr.Image(
                    label="Preview", type="pil", height=340, interactive=False,
                )
                upload.change(load_upload, [upload], [image])
                with gr.Row():
                    garment = gr.Dropdown(
                        _garment_choices(), value=_GARMENT_LABELS[Garment.PARTY_DRESS],
                        label="Garment type",
                    )
                    fabric = gr.Dropdown(
                        _fabric_choices(), value=_AUTO_FABRIC,
                        label="Fabric",
                        info="Auto picks a sensible default for the garment type. "
                             "Set it explicitly for a sheer/net/lace piece.",
                    )

            gr.Markdown("#### ② Backdrop")
            with gr.Group():
                backdrop = gr.Radio(
                    [(label, value) for _, label, value in _combined_backdrop_entries()],
                    value="studio_ivory", label="Backdrop",
                    info="Pick by eye in the gallery on the right, or by name here.",
                )

            gr.Markdown(
                "#### ③ Optional -- fine-tune\n"
                "Everything in this section has a sensible default. Open one "
                "only if you need it."
            )
            with gr.Accordion("Use your own backdrop photo instead", open=False):
                gr.Markdown(
                    "Upload a photograph — your own venue, your own decor "
                    "setup, or stock you've actually licensed for commercial "
                    "use. **Not a screenshot or download from Pinterest, "
                    "Instagram, or a search engine** — those belong to "
                    "whoever photographed them, and using them on a storefront "
                    "without a licence is a real legal risk, not a formality. "
                    "**Saved automatically** once uploaded — it joins the list "
                    "above by name and the gallery by eye, and is still there "
                    "next time you open the app, until you remove it below."
                )
                custom_backdrop = gr.File(
                    label="Backdrop photograph (optional)",
                    file_types=["image", ".heic", ".heif"],
                    height=100,
                )
                custom_backdrop_category = gr.Radio(
                    list(backdrop_library.CATEGORIES),
                    value=backdrop_library.DEFAULT_CATEGORY, label="Category",
                    info="Which group this is saved under -- Studio (a venue, a "
                         "wall, an indoor set) or Nature (outdoors, a garden).",
                )
                custom_backdrop_preview = gr.Image(
                    label="Backdrop preview", type="pil", height=160, interactive=False,
                )
                custom_backdrop.change(
                    load_upload, [custom_backdrop], [custom_backdrop_preview],
                )
            with gr.Accordion("Your saved backdrop photos", open=False):
                gr.Markdown(
                    "Every photo you've uploaded above, on this machine, across "
                    "every session. Remove one you no longer want offered."
                )
                library_list = gr.Dropdown(
                    choices=_library_choices(), value=None,
                    label="Saved photo", interactive=True,
                )
                library_preview = gr.Image(
                    label="Preview", type="pil", height=160, interactive=False,
                )
                remove_btn = gr.Button("Remove")
                remove_status = gr.Markdown()
            with gr.Accordion("Placement -- automatic, with overrides", open=False):
                auto_place = gr.Checkbox(
                    value=True,
                    label="Place automatically (recommended)",
                    info="With a backdrop photo: a scene-understanding model finds "
                         "the floor, grass, rug or stairs, plants the feet there, "
                         "sizes the figure to how wide the shot is (a room gets a "
                         "smaller figure than a close drape), and warns if the photo "
                         "isn't a place a person could stand. With a preset: the "
                         "ordinary defaults. Untick to set size and position "
                         "yourself with the two sliders just below -- the lighting "
                         "sliders further down (seam softening onward) always apply, "
                         "whether this is ticked or not.",
                )
                fill_pct = gr.Slider(
                    minimum=30, maximum=100, value=88, step=1,
                    label="Size (% of the height above the floor line)",
                    info="How tall the figure is in the frame. Smaller for a wide "
                         "room; larger for a close backdrop.",
                )
                x_pct = gr.Slider(
                    minimum=0, maximum=100, value=50, step=1,
                    label="Horizontal position (% across, 50 = centred)",
                )
                floor_frac = gr.Slider(
                    minimum=0, maximum=100, value=95, step=1,
                    label="Floor line (% down the photo)",
                    info="Where the feet land. 95 = near the very bottom (a photo "
                         "shot at floor level). Lower it for a backdrop whose own "
                         "floor sits higher in frame -- a porch, a staircase.",
                )
                blur_pct = gr.Slider(
                    minimum=0, maximum=200, value=100, step=5,
                    label="Seam softening at the feet (%, 0 = off)",
                    info="A small feathered patch where the hem meets the ground -- "
                         "the only place the backdrop is softened. Nothing else in "
                         "the backdrop is ever blurred.",
                )
                light_dir_pct = gr.Slider(
                    minimum=-100, maximum=100, value=-25, step=5,
                    label="Light direction (-100 = from the left, 100 = from the right)",
                    info="Which side the light comes from, and so which way the "
                         "contact shadow falls. Automatic reads this from the "
                         "backdrop's own brightness; set it here when that reads "
                         "the scene wrong.",
                )
                tint_pct = gr.Slider(
                    minimum=0, maximum=200, value=100, step=5,
                    label="Colour tint from the backdrop (%, 0 = off)",
                    info="How much of the backdrop's own colour is lent to the "
                         "garment so it reads as lit by the same room. The colour "
                         "gate still caps this no matter what you set.",
                )
                exposure_pct = gr.Slider(
                    minimum=0, maximum=200, value=100, step=5,
                    label="Exposure match to the backdrop (%, 0 = off)",
                    info="Dims the garment a little for a dark backdrop, lifts it a "
                         "little for a bright one, and now shades one side more than "
                         "the other toward the light -- lit by the same room, not "
                         "just coloured by it. The colour gate caps it either way.",
                )
                depth_blur_pct = gr.Slider(
                    minimum=0, maximum=200, value=100, step=5,
                    label="Background softness (%, 0 = off)",
                    info="A gentle portrait-style blur on whatever is genuinely far "
                         "from the figure -- the figure itself, and the backdrop "
                         "right around it, stay sharp. Not a whole-frame blur.",
                )
                finishing_pct = gr.Slider(
                    minimum=0, maximum=200, value=100, step=5,
                    label="Photo finish -- grain, contrast, vignette (%, 0 = off)",
                    info="One last pass over the whole finished image, not just the "
                         "figure -- a touch of film grain, contrast and edge "
                         "darkening, the way a real camera's own processing does. "
                         "This is what makes the figure and the backdrop read as "
                         "one photograph instead of two separately-lit pieces.",
                )
            with gr.Accordion("Recolour (coming soon)", open=False):
                gr.Markdown(
                    "**Not built yet — Phase 3 of the roadmap.** This will let "
                    "you change the dress colour without touching its design "
                    "(embroidery, prints and folds preserved). Nothing below "
                    "does anything today."
                )
                gr.ColorPicker(label="Target colour", interactive=False)

            gr.Markdown("#### ④ Export")
            preset_defaults = _preset_choices()
            presets = gr.CheckboxGroup(
                preset_defaults,
                value=[p for p in preset_defaults if p.startswith("portrait_2x3")
                       or p.startswith("web_card_3x4")],
                label="Export sizes",
            )
            run_btn = gr.Button("Process this dress", variant="primary", size="lg")

        with gr.Column(scale=1):
            gr.Markdown(
                "#### Backdrops, sorted dark → light\n"
                "Click a photo to pick it — it selects the same backdrop as "
                "the list on the left."
            )
            backdrop_gallery = gr.Gallery(
                value=[(thumb, label) for thumb, label, _ in _combined_backdrop_entries()],
                columns=3, height=420, show_label=False, object_fit="cover",
            )

    gr.Markdown("---")
    with gr.Row():
        with gr.Column(scale=2):
            output = gr.Gallery(label="Result", columns=2, height=480)
        with gr.Column(scale=1):
            report = gr.Textbox(label="Checks", lines=6, interactive=False)
            warnings = gr.Textbox(label="Warnings", lines=6, interactive=False)

    # Clicking a thumbnail used to just open Gradio's own image preview,
    # with no effect on which backdrop would actually be used -- the
    # gallery's own caption promised "pick by eye" without that ever being
    # wired up. This is the fix, not just a new feature.
    backdrop_gallery.select(_on_backdrop_gallery_select, None, [backdrop])

    # Saving to the library, then refreshing both the radio and the gallery
    # so a newly uploaded photo is immediately pickable -- not just present
    # after a restart -- is chained onto the existing preview update rather
    # than replacing it.
    custom_backdrop.change(
        _save_uploaded_backdrop_and_refresh,
        [custom_backdrop, custom_backdrop_category], [backdrop, backdrop_gallery],
    )
    library_list.change(
        _preview_library_backdrop, [library_list], [library_preview],
    )
    remove_btn.click(
        _remove_library_backdrop, [library_list],
        [backdrop, backdrop_gallery, library_list, library_preview, remove_status],
    )

    run_btn.click(
        _process_ui,
        inputs=[image, upload, garment, fabric, backdrop, custom_backdrop, auto_place,
                fill_pct, x_pct, floor_frac, blur_pct, light_dir_pct, tint_pct,
                exposure_pct, presets, depth_blur_pct, finishing_pct],
        outputs=[output, report, warnings],
    )


def _save_extra_backdrops_to_library(file_paths, category=backdrop_library.DEFAULT_CATEGORY) -> str:
    """Fires when photos land in "Also compare against your own backdrop
    photos": saves each into the persistent library (§ `backdrop_library`),
    under the chosen category, same as the Process tab's upload. Without
    this, a photo added here only ever appeared in comparisons for the run
    it was uploaded in -- gone the moment the operator started a fresh
    batch, let alone a fresh session.
    """
    for p in file_paths or []:
        try:
            backdrop_library.add(
                load_upload(str(p)), f"Your photo: {Path(str(p)).stem}", category=category)
        except Exception:  # noqa: BLE001 -- a bad upload shouldn't crash the wiring
            continue
    n = len(backdrop_library.list_entries())
    return (f"{n} saved backdrop photo(s) — included in every comparison below "
            f"automatically, on top of anything you add here.")


def _compare_backdrops_ui(upload_paths, garment_label, fabric_label, extra_backdrop_paths,
                           progress=gr.Progress()):
    """What the Compare button actually calls. `compare_backdrops()` itself
    stays exactly as tested: this wrapper only adds every backdrop already
    saved to the library to whatever was freshly uploaded this run, so a
    photo saved once keeps showing up in every comparison after, with no
    re-upload -- the same persistence promise the Process tab's radio/
    gallery make, applied here too.

    A library photo that's identical to one just re-uploaded this run isn't
    added twice -- compared by content hash, not by filename, since the two
    uploads may well be named differently.

    Library photos are copied under a name built from their own label
    before being handed to `compare_backdrops` -- that function captions
    each sheet cell from the file's own stem (`Path(p).stem`), and a
    library photo's real filename on disk is its content hash, not
    anything readable. Without this, every library backdrop's caption on
    the sheet was a hash string instead of "Studio -- white wall", found
    on the first real bulk run that included one.
    """
    extra_paths = list(extra_backdrop_paths or [])
    fresh_hashes = set()
    for p in extra_paths:
        try:
            fresh_hashes.add(backdrop_library.hash_image(load_upload(str(p))))
        except Exception:  # noqa: BLE001
            pass
    library_entries = [e for e in backdrop_library.list_entries() if e.key not in fresh_hashes]
    with tempfile.TemporaryDirectory() as td:
        for entry in library_entries:
            named = Path(td) / f"{_sanitize_filename(f'{entry.category} - {entry.label}')}.jpg"
            shutil.copy(entry.path, named)
            extra_paths.append(str(named))
        yield from compare_backdrops(upload_paths, garment_label, fabric_label, extra_paths,
                                      progress=progress)


def _sanitize_filename(label: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9 _-]', '', label).strip()
    return cleaned[:60] or "backdrop"


def build_compare_tab() -> None:
    gr.Markdown(
        "Upload one photograph or many. Each comes back as a contact sheet -- "
        "the same garment against every built-in backdrop plus every photo "
        "you've saved to your backdrop library, placed automatically -- so "
        "you can pick by eye. **Preview only:** nothing is exported from "
        "here. Once you've chosen, go to *Process a dress*, pick that "
        "backdrop by name, and make the real file."
    )
    with gr.Row():
        with gr.Column(scale=1):
            uploads = gr.File(
                label="Dress photographs (one or many)",
                file_types=["image", ".heic", ".heif"],
                file_count="multiple",
                height=160,
            )
            with gr.Row():
                garment = gr.Dropdown(
                    _garment_choices(), value=_GARMENT_LABELS[Garment.PARTY_DRESS],
                    label="Garment type",
                    info="Applied to every photograph in this batch.",
                )
                fabric = gr.Dropdown(
                    _fabric_choices(), value=_AUTO_FABRIC, label="Fabric",
                )
            with gr.Accordion("Also compare against your own backdrop photos", open=False):
                gr.Markdown(
                    "Optional. Any photos added here appear in every sheet alongside "
                    "the built-in presets, placed automatically (floor found, figure "
                    "sized). Same licence note as the Process tab: your own venue "
                    "or decor, or licensed stock -- not screenshots or downloads. "
                    "A backdrop the detector thinks isn't a place to stand is "
                    "marked **[!]** on the sheet rather than left out."
                )
                extra_backdrops = gr.File(
                    label="Backdrop photographs (optional)",
                    file_types=["image", ".heic", ".heif"],
                    file_count="multiple",
                    height=120,
                )
                extra_backdrops_category = gr.Radio(
                    list(backdrop_library.CATEGORIES),
                    value=backdrop_library.DEFAULT_CATEGORY, label="Category",
                )
                library_note = gr.Markdown(
                    f"{len(backdrop_library.list_entries())} saved backdrop photo(s) "
                    f"already in your library -- included below automatically."
                )
            compare_btn = gr.Button("Compare backdrops", variant="primary", size="lg")
            status = gr.Textbox(label="Progress", lines=2, interactive=False)
        with gr.Column(scale=2):
            sheets = gr.Gallery(
                label="Contact sheets -- one per photograph",
                columns=1, height=760, object_fit="contain",
            )
    extra_backdrops.change(
        _save_extra_backdrops_to_library,
        [extra_backdrops, extra_backdrops_category], [library_note],
    )
    compare_btn.click(
        _compare_backdrops_ui,
        inputs=[uploads, garment, fabric, extra_backdrops],
        outputs=[sheets, status],
    )


def build_status_tab() -> None:
    n_library = len(backdrop_library.list_entries())
    gr.Markdown(
        f"""
### What this app actually does today

| Tool | Status |
|---|---|
| **Background removal** | Working |
| **Apply a new background** | Working — 1 plain white backdrop + {n_library} of your own, saved |
| **Colour change** | Not built (Phase 3) |
| **Shaded / multi-tone colour** | Not built (Phase 4) |
| **Design edit by prompt** | Not built (Phase 5) |
| **Dress on a mannequin** | Not built (Phase 6) |

Every photograph is checked automatically after processing:
- **colour_fidelity** — does the dress in the result still match the colour
  in your original photo (within a small, measured tolerance)?
- **framing** — is the dress a sensible size in the frame (not tiny, not
  overflowing)?
- **cutout_softness** — informational only, tells you how much of the edge
  is semi-transparent (relevant for net/lace/chiffon).

**Current, known limitations** (not bugs to re-report — see `CLAUDE.md`
for the reasoning behind each):
- A custom backdrop photo that's flat and out-of-focus (an abstract print, a
  macro shot) can be misread as a plain wall by the floor-finder and come
  back usable when it shouldn't. Give an ambiguous backdrop photo a glance
  before trusting it.
- The first photograph after starting the app is slower (~10-25s) than the
  ones after it — there's no background worker keeping the matting model
  warm between runs yet.
- Colour tint and exposure matching from a backdrop are both a single flat
  adjustment across the whole garment, not brighter-on-one-side-than-the-
  other. The sliders under *Placement* let you correct either by hand.
        """
    )


#: A calm, muted blue -- asked for directly, 2026-09-23, as "soothing, like
#: VS Code blue": `sky_600` (`#0284c7`) sits close to VS Code's own accent
#: (`#007ACC`), checked hex-by-hex against Gradio's built-in hue tables
#: rather than picking "blue" by name and hoping (Tailwind's plain "blue"
#: leans noticeably more purple -- `#2563eb` -- which reads as a generic
#: web-app blue, not the flatter cyan-leaning blue VS Code actually uses).
#: `neutral_hue="zinc"` for the same reason on the grey side: VS Code's own
#: dark background (`#1e1e1e`) is close to true achromatic grey, and `zinc`
#: is the least blue/brown-tinted of Gradio's built-in neutrals -- `stone`
#: (the previous warm palette's neutral) or `gray`/`slate` would each pull
#: panel backgrounds toward a tint VS Code's own chrome doesn't have.
#:
#: Was orange/amber/stone (a warm occasionwear palette) before this. The
#: `.set()` overrides below reference relative theme tokens (`*neutral_700`
#: etc.), not literal hex, specifically so a hue swap like this one only
#: needs the three names above changed -- see each override's own comment
#: for why it exists.
#:
#: Two `.set()` overrides, added 2026-09-23 after a real dark-mode screenshot
#: showed why "no overrides" wasn't actually safe: Soft's own *default* dark
#: variant for a field label is a fully-saturated solid fill
#: (`block_label_background_fill_dark = *primary_600`, white text) --
#: correct per Gradio's own theme builder, but applied to *every single*
#: label in this app it reads as a loud badge shouting on every section
#: instead of a quiet marker, which light mode's soft pale tint
#: (`*primary_100`) never does. This brings dark mode into the same
#: register light mode already uses, rather than inventing a second visual
#: language for it. Checked against the theme's own computed values
#: (`gr.themes.Soft(...).block_label_background_fill_dark` etc.) before
#: picking replacements, not guessed.
_THEME = gr.themes.Soft(
    primary_hue="sky", secondary_hue="sky", neutral_hue="zinc",
).set(
    block_label_background_fill_dark="*neutral_700",
    block_label_text_color_dark="*primary_300",
    block_title_background_fill_dark="*neutral_700",
    block_title_text_color_dark="*primary_300",
    #: A visible card edge in dark mode -- `border_color_primary_dark`
    #: defaults to `*neutral_700`, the same value a block's own background
    #: now uses two lines below by inheritance, which made every panel's
    #: boundary disappear into its neighbour. `*neutral_600` is a full step
    #: lighter, checked against both `*neutral_800` (a card) and
    #: `*neutral_950` (the page behind it) to confirm it reads against each.
    border_color_primary_dark="*neutral_600",
)

#: Small, deliberately limited CSS pass -- a header banner, a readable
#: content width on a wide monitor, and rounded corners on panels so
#: accordions and cards read as distinct surfaces. Not a redesign: every
#: control, layout and accordion below is unchanged, this only restyles
#: what is already there.
#:
#: The header banner used to be a hardcoded light cream gradient with no
#: text colour set -- invisible in dark mode, because Gradio's dark-mode
#: text colour is *light*, rendered on top of a background that stayed
#: light regardless of theme. Rewritten to use Gradio's own CSS custom
#: properties (`var(--block-background-fill)` etc., the same tokens every
#: native panel already uses) instead of literal hex, so it inherits
#: correct contrast in both modes automatically and can never drift out of
#: sync with the theme again -- see `base.py`'s `_get_theme_css` in the
#: installed gradio package for where these are generated.
_CSS = """
.gradio-container { max-width: 1400px !important; margin: 0 auto !important; }
.dress-header {
    padding: 20px 26px; border-radius: 16px; margin-bottom: 14px;
    background: var(--color-accent-soft);
    border: 1px solid var(--border-color-accent);
}
.dress-header h1 { margin: 0 0 4px 0; font-size: 1.5rem; color: var(--body-text-color); }
.dress-header p { margin: 0; font-size: 0.95rem; color: var(--body-text-color-subdued); }
.gradio-container .block { border-radius: 12px !important; }
"""


def build() -> gr.Blocks:
    with gr.Blocks(title="Dress Studio") as demo:
        gr.HTML(
            '<div class="dress-header">'
            "<h1>🪡 Dress Studio</h1>"
            "<p>Background removal &amp; backdrop compositing for occasionwear "
            "catalogue photography — sarees, lehengas, anarkalis, gowns, party "
            "dresses.</p>"
            "</div>"
        )
        with gr.Tabs():
            with gr.Tab("🧵 Process a dress"):
                build_process_tab()
            with gr.Tab("🖼️ Compare backdrops"):
                build_compare_tab()
            with gr.Tab("📋 What's built"):
                build_status_tab()
    return demo


def main() -> None:
    # Gradio 6 moved `theme`/`css` from the `Blocks` constructor to
    # `launch()` -- passed here, not in `build()`, so `build()` stays
    # exactly what every test calls directly, launch-independent.
    build().launch(theme=_THEME, css=_CSS)


if __name__ == "__main__":
    main()
