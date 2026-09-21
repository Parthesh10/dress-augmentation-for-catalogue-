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

import tempfile
import time
import traceback
from pathlib import Path

import gradio as gr
import numpy as np
from PIL import Image, ImageOps

from . import backgrounds, stages  # noqa: F401 -- importing stages registers them
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
            # use its defaults (position, seam softening). Setting them is
            # the override -- all four together, so "manual" has one clear
            # meaning: the sliders, exactly as they read.
            ctx.extra["custom_floor_frac"] = float(floor_frac_pct) / 100.0
            ctx.extra["subject_fill"] = float(fill_pct) / 100.0
            ctx.extra["subject_x"] = float(x_pct) / 100.0
            ctx.extra["seam_blur_strength"] = float(blur_pct) / 100.0
            # -100..100 on the slider maps to the same +-0.4 range
            # `infer_key_direction` itself clips to.
            ctx.extra["light_dir_x"] = float(light_dir_pct) / 100.0 * 0.4
            ctx.extra["tint_strength"] = float(tint_pct) / 100.0
            ctx.extra["exposure_strength"] = float(exposure_pct) / 100.0

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

        gallery = [Image.open(p).convert("RGB") for p in m.outputs]

        lines = []
        for g in m.gates:
            mark = "✓" if g.passed else "✗ FAILED"
            lines.append(f"{mark}  {g.name}: {g.detail}")
        report = "\n".join(lines) if lines else "(no gates recorded)"

        warn_lines = "\n".join(f"⚠ {w}" for w in m.warnings) if m.warnings else ""

        progress(1.0, desc="done")
        yield gallery, report, warn_lines


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
            backdrop = gr.Radio(
                _BACKDROP_NAMES, value="studio_ivory", label="Backdrop",
                info="Pick by eye in the gallery on the right, or by name here.",
            )
            with gr.Accordion("Or use your own backdrop photo", open=False):
                gr.Markdown(
                    "Upload a photograph — your own venue, your own decor "
                    "setup, or stock you've actually licensed for commercial "
                    "use. **Not a screenshot or download from Pinterest, "
                    "Instagram, or a search engine** — those belong to "
                    "whoever photographed them, and using them on a storefront "
                    "without a licence is a real legal risk, not a formality. "
                    "When a photo is uploaded here, it replaces the preset "
                    "above; the same grounding, shadow, and colour checks run "
                    "on it either way."
                )
                custom_backdrop = gr.File(
                    label="Backdrop photograph (optional)",
                    file_types=["image", ".heic", ".heif"],
                    height=100,
                )
                custom_backdrop_preview = gr.Image(
                    label="Backdrop preview", type="pil", height=160, interactive=False,
                )
                custom_backdrop.change(
                    load_upload, [custom_backdrop], [custom_backdrop_preview])
            with gr.Accordion("Placement -- automatic, with overrides", open=False):
                auto_place = gr.Checkbox(
                    value=True,
                    label="Place automatically (recommended)",
                    info="With a backdrop photo: a scene-understanding model finds "
                         "the floor, grass, rug or stairs, plants the feet there, "
                         "sizes the figure to how wide the shot is (a room gets a "
                         "smaller figure than a close drape), and warns if the photo "
                         "isn't a place a person could stand. With a preset: the "
                         "ordinary defaults. Untick to set everything below yourself.",
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
                         "little for a bright one -- lit by the same room, not just "
                         "coloured by it. Small by design (about -5% on the darkest "
                         "preset); the colour gate caps it.",
                )
            preset_defaults = _preset_choices()
            presets = gr.CheckboxGroup(
                preset_defaults,
                value=[p for p in preset_defaults if p.startswith("portrait_2x3")
                       or p.startswith("web_card_3x4")],
                label="Export sizes",
            )
            with gr.Accordion("Recolour (coming soon)", open=False):
                gr.Markdown(
                    "**Not built yet — Phase 3 of the roadmap.** This will let "
                    "you change the dress colour without touching its design "
                    "(embroidery, prints and folds preserved). Nothing below "
                    "does anything today."
                )
                gr.ColorPicker(label="Target colour", interactive=False)
            run_btn = gr.Button("Process", variant="primary")

        with gr.Column(scale=1):
            gr.Markdown("#### Backdrops, sorted dark → light")
            gr.Gallery(
                value=_BACKDROP_THUMBS, columns=3, height=420,
                show_label=False, object_fit="cover",
            )

    gr.Markdown("---")
    with gr.Row():
        with gr.Column(scale=2):
            output = gr.Gallery(label="Result", columns=2, height=480)
        with gr.Column(scale=1):
            report = gr.Textbox(label="Checks", lines=6, interactive=False)
            warnings = gr.Textbox(label="Warnings", lines=6, interactive=False)

    run_btn.click(
        process,
        inputs=[image, upload, garment, fabric, backdrop, custom_backdrop, auto_place,
                fill_pct, x_pct, floor_frac, blur_pct, light_dir_pct, tint_pct,
                exposure_pct, presets],
        outputs=[output, report, warnings],
    )


def build_compare_tab() -> None:
    gr.Markdown(
        "Upload one photograph or many. Each comes back as a contact sheet -- "
        "the same garment against every built-in backdrop, placed "
        "automatically -- so you can pick by eye. **Preview only:** nothing is "
        "exported from here. Once you've chosen, go to *Process a dress*, pick "
        "that backdrop by name, and make the real file."
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
            compare_btn = gr.Button("Compare backdrops", variant="primary")
            status = gr.Textbox(label="Progress", lines=2, interactive=False)
        with gr.Column(scale=2):
            sheets = gr.Gallery(
                label="Contact sheets -- one per photograph",
                columns=1, height=760, object_fit="contain",
            )
    compare_btn.click(
        compare_backdrops,
        inputs=[uploads, garment, fabric, extra_backdrops],
        outputs=[sheets, status],
    )


def build_status_tab() -> None:
    gr.Markdown(
        """
### What this app actually does today

| Tool | Status |
|---|---|
| **Background removal** | Working |
| **Apply a new background** | Working — 11 backdrops |
| **Colour change** | Not built (Phase 3) |
| **Shaded / multi-tone colour** | Not built (Phase 4) |
| **Design edit by prompt** | Not built (Phase 5) |
| **Dress on a mannequin** | Not built (Phase 6) |

**Known issue:** on dark backdrops a faint pale edge can show around the
garment (background-removal cleanup not finished). Prefer the lighter
backdrops until this is fixed.

Every photograph is checked automatically after processing:
- **colour_fidelity** — does the dress in the result still match the colour
  in your original photo (within a small, measured tolerance)?
- **framing** — is the dress a sensible size in the frame (not tiny, not
  overflowing)?
- **cutout_softness** — informational only, tells you how much of the edge
  is semi-transparent (relevant for net/lace/chiffon).
        """
    )


def build() -> gr.Blocks:
    with gr.Blocks(title="Dress Studio") as demo:
        gr.Markdown("## Dress Studio — background removal & backdrop tool")
        with gr.Tabs():
            with gr.Tab("Process a dress"):
                build_process_tab()
            with gr.Tab("Compare backdrops"):
                build_compare_tab()
            with gr.Tab("What's built"):
                build_status_tab()
    return demo


def main() -> None:
    build().launch()


if __name__ == "__main__":
    main()
