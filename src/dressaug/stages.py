"""The stages. Phases 1 and 2 are built; the rest declare themselves unbuilt.

Same contract as the sibling jewellery project: a stage is a function from
`Context` to `Context`, registered by name, and a graph is a list of those
names. Everything a stage measured goes into `ctx.extra`, and the small named
subset in `pipeline.DIAGNOSTIC_KEYS` reaches the manifest on disk.

The one structural difference worth knowing about is **transparency**. Every
stage here that touches alpha treats a fractional value as real rather than
as something to be tidied into 0 or 1, because on a chiffon or tulle garment
the fractional band *is* the product.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageOps

from . import backgrounds
from .backends import get_backend
from .color import delta_e2000, linear_to_srgb, mean_product_lab, rgb_to_lab, srgb_to_linear
from .config import EXPORT_PRESETS, OUT_DIR, THRESHOLDS, Fabric, Phase
from .pipeline import REGISTRY, Context, GateResult


def _arr(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0


def _img(arr: np.ndarray) -> Image.Image:
    return Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), "RGB")


def not_built(phase: Phase):
    """A stage that refuses rather than quietly doing nothing.

    The roadmap has six phases and two are built. A stage for a later one that
    returned `ctx` unchanged would make a run *look* complete, which is the
    single most expensive kind of wrong in a pipeline whose whole point is
    that its output can be trusted.
    """
    def stage(ctx: Context) -> Context:
        raise NotImplementedError(
            f"phase {phase.value} is not built yet — see TASK.md for what it needs"
        )
    return stage


# ---------------------------------------------------------------- 1. ingest


@REGISTRY.register("ingest")
def ingest(ctx: Context) -> Context:
    """Load, respect EXIF orientation, and judge the input honestly."""
    im = ImageOps.exif_transpose(Image.open(ctx.source_path)).convert("RGB")
    short = min(im.size)
    if short < THRESHOLDS.min_short_edge_reject:
        raise ValueError(
            f"short edge {short}px is below the {THRESHOLDS.min_short_edge_reject}px "
            "floor — nothing downstream can recover a usable edge from this"
        )
    if short < THRESHOLDS.min_short_edge_warn:
        ctx.warn(
            f"short edge {short}px is below {THRESHOLDS.min_short_edge_warn}px. A gown "
            "is photographed whole, so its detail -- a lace hem, a beaded neckline -- "
            "occupies a much smaller share of the frame than a small object would, and "
            "needs more pixels overall to survive"
        )
    ctx.source = im
    ctx.product = im
    ctx.extra["source_size"] = im.size
    ctx.store.image("ingest", "source", im)
    return ctx


# ------------------------------------------------- 2. matte  (PHASE 1)


def decontaminate(rgb: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Recover the garment's true colour at semi-transparent edge pixels.

    **This is the fix for the pale halo** -- the known defect recorded in
    TASK.md since 2026-09-11. A matte cut from a white studio background
    carries a trace of that white in every semi-transparent edge pixel
    (anti-aliased hems, wisps of hair-fine trim, the soft border of a net
    skirt). Composite that pixel onto midnight velvet and the white bleeds
    through as a pale fringe, regardless of how good the alpha itself is.

    The fix, ported from the sibling jewellery project's `matte` stage:
    estimate the old background's colour from the pixels the matte calls
    empty, then invert the compositing equation

        observed = true_colour * a + old_bg * (1 - a)
        true_colour = (observed - old_bg * (1 - a)) / a

    **This is not only correct for opaque garments with soft edges -- it is
    also correct for genuinely sheer fabric**, and that is worth spelling
    out because it looks at first like it should only apply to one case.
    A chiffon or net pixel is not an edge artefact; the fabric really is
    partly see-through there, and the physical thing the camera recorded
    really is `garment_tint * a + whatever_was_behind_it * (1 - a)`. The
    inversion above recovers `garment_tint` -- the colour of the fabric
    itself -- which is exactly what standard alpha compositing needs to
    place that same sheer fabric correctly over a *different* backdrop.
    Skipping decontamination on sheer fabric would have been the actual bug;
    it is not an exception to the fix, it is the case that needs it most.

    Alpha is returned unchanged. Only colour moves.
    """
    a = alpha[..., None]
    bg_mask = alpha < 0.05
    if bg_mask.sum() > 64:
        bg_colour = rgb[bg_mask].mean(axis=0)
    else:
        bg_colour = np.array([1.0, 1.0, 1.0], dtype=np.float32)  # studio white default

    safe = np.maximum(a, 0.12)
    recovered = np.clip((rgb - bg_colour * (1 - a)) / safe, 0, 1)
    # Below the matting stage's own floor there is no product signal to
    # recover at all -- leave those pixels as observed rather than manufacture
    # a colour from noise.
    out = np.where(a > THRESHOLDS.alpha_floor, recovered, rgb)
    return out, bg_colour


def partial_alpha_fraction(alpha: np.ndarray) -> float:
    """How much of the matte is genuinely fractional rather than 0 or 1.

    This is the number that tells you whether a sheer garment survived. A
    hardened matte of a tulle skirt looks tidy and has thrown the skirt away;
    a good one has a wide band of partial alpha along every layered edge.
    """
    a = np.asarray(alpha, dtype=np.float32)
    inside = a > THRESHOLDS.alpha_floor
    if inside.sum() < 64:
        return 0.0
    partial = inside & (a < THRESHOLDS.alpha_solid)
    return float(partial.sum()) / float(inside.sum())


@REGISTRY.register("matte")
def matte(ctx: Context) -> Context:
    """PHASE 1 — separate the garment from whatever it was photographed on."""
    assert ctx.source is not None
    backend = get_backend(ctx.extra.get("backend", "local_cpu"))
    alpha = backend.matte(ctx.source)
    if alpha.shape[:2] != (ctx.source.size[1], ctx.source.size[0]):
        alpha = np.asarray(
            Image.fromarray((alpha * 255).astype(np.uint8), "L").resize(
                ctx.source.size, Image.LANCZOS),
            dtype=np.float32,
        ) / 255.0

    coverage = float((alpha > THRESHOLDS.alpha_floor).mean())
    partial = partial_alpha_fraction(alpha)
    ctx.extra["matte_coverage"] = round(coverage, 4)
    ctx.extra["partial_alpha_fraction"] = round(partial, 4)

    if coverage < 0.01:
        ctx.warn(f"matte found almost no garment ({coverage:.1%} of the frame)")

    fabric = ctx.cfg.resolved_fabric()
    if fabric in (Fabric.SHEER, Fabric.LACE):
        if partial < THRESHOLDS.min_partial_alpha_on_sheer:
            ctx.warn(
                f"this garment is declared {fabric.value} but only {partial:.1%} of its "
                "matte is partially transparent. A sheer fabric should show a wide band "
                "of soft alpha; this one came back hard-edged, which usually means the "
                "net or chiffon was dropped rather than matted. Check the cutout before "
                "trusting it"
            )
    rgb = _arr(ctx.source)
    decontaminated, bg_colour = decontaminate(rgb, alpha)
    ctx.extra["old_background_rgb"] = [round(float(v), 4) for v in bg_colour]

    ctx.alpha = alpha
    ctx.product = _img(decontaminated)
    ctx.store.mask("matte", "alpha", alpha)
    ctx.store.image("matte", "product-decontaminated", ctx.product)
    return ctx


# -------------------------------------------- 3. background  (PHASE 2)


@REGISTRY.register("background")
def background(ctx: Context) -> Context:
    """PHASE 2 — generate the backdrop the garment will stand in front of."""
    assert ctx.source is not None
    w, h = ctx.source.size
    scale = 1800 / max(w, h)
    size = (max(int(w * scale), 640), max(int(h * scale), 640)) if scale > 1 else (w, h)

    preset = ctx.cfg.background
    seed = abs(hash(ctx.job_id)) % 9973
    ctx.background = backgrounds.render(preset, size, seed=seed)
    ctx.extra["backdrop_used"] = preset
    ctx.extra["composite_size"] = size
    ctx.extra["key_luminance"] = backgrounds.key_luminance(preset)
    ctx.extra["key_direction"] = backgrounds.key_direction(preset)
    ctx.store.image("background", preset, ctx.background)
    return ctx


# ---------------------------------------------------------------- composite


def place(alpha: np.ndarray, product: Image.Image, size: tuple[int, int]):
    """Scale the garment to fill the frame vertically, bounded by width.

    Bounded by **both**, and that is a bug inherited as a lesson rather than
    as code: the sibling scaled a decor hanging by height alone and a wide
    subject came out at 128% of the canvas, clipped off both edges, silently.
    A saree photographed spread out is exactly that shape.
    """
    cw, ch = size
    ys, xs = np.nonzero(alpha > THRESHOLDS.alpha_floor)
    if len(xs) == 0:
        raise ValueError("nothing to composite — the matte is empty")
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    crop_a = alpha[y0:y1, x0:x1]
    crop_p = product.crop((int(x0), int(y0), int(x1), int(y1)))
    bw, bh = crop_p.size

    fill = THRESHOLDS.garment_fill
    scale = min(ch * fill / bh, cw * fill / bw)
    nw, nh = max(int(bw * scale), 8), max(int(bh * scale), 8)

    p_res = crop_p.resize((nw, nh), Image.LANCZOS)
    a_res = np.asarray(
        Image.fromarray((np.clip(crop_a, 0, 1) * 255).astype(np.uint8), "L").resize(
            (nw, nh), Image.LANCZOS),
        dtype=np.float32,
    ) / 255.0
    return p_res, a_res, int(cw / 2 - nw / 2), int(ch / 2 - nh / 2)


def compose(bg: Image.Image, product: Image.Image, alpha: np.ndarray):
    """Alpha-composite in linear light. Fractional alpha is honoured exactly."""
    p_res, a_res, ox, oy = place(alpha, product, bg.size)
    canvas = srgb_to_linear(_arr(bg))
    piece = srgb_to_linear(_arr(p_res))
    h, w = a_res.shape
    region = canvas[oy:oy + h, ox:ox + w]
    a = a_res[..., None]
    canvas[oy:oy + h, ox:ox + w] = piece * a + region * (1 - a)
    scene_alpha = np.zeros(canvas.shape[:2], np.float32)
    scene_alpha[oy:oy + h, ox:ox + w] = a_res
    return _img(linear_to_srgb(np.clip(canvas, 0, 1))), scene_alpha


@REGISTRY.register("composite")
def composite(ctx: Context) -> Context:
    assert ctx.background is not None and ctx.product is not None and ctx.alpha is not None
    out, scene_alpha = compose(ctx.background, ctx.product, ctx.alpha)
    ctx.composited = out
    ctx.composited_alpha = scene_alpha
    ctx.store.image("composite", "result", out)
    return ctx


# ---------------------------------------------------------------- gates


@REGISTRY.register("gates")
def gates(ctx: Context) -> Context:
    assert ctx.source is not None and ctx.composited is not None
    src_lab = mean_product_lab(_arr(ctx.source), ctx.alpha, solid=THRESHOLDS.alpha_solid)
    out_lab = mean_product_lab(
        _arr(ctx.composited), ctx.composited_alpha, solid=THRESHOLDS.alpha_solid)
    de = float(delta_e2000(src_lab[None, :], out_lab[None, :])[0])
    ctx.manifest.gates.append(GateResult(
        "colour_fidelity", de <= THRESHOLDS.max_delta_e2000,
        round(de, 3), THRESHOLDS.max_delta_e2000,
        f"dE2000 {de:.2f} against a {THRESHOLDS.max_delta_e2000} budget",
    ))

    frac = float((ctx.composited_alpha > THRESHOLDS.alpha_floor).mean())
    ctx.manifest.gates.append(GateResult(
        "framing",
        THRESHOLDS.min_product_coverage <= frac <= THRESHOLDS.max_product_coverage,
        round(frac, 4), THRESHOLDS.max_product_coverage,
        f"garment occupies {frac:.1%} of the frame",
    ))

    partial = ctx.extra.get("partial_alpha_fraction", 0.0)
    # Reported, never failed. How soft a cutout *should* be is a property of
    # the fabric, and nobody has measured this catalogue's yet -- so this
    # records the number and leaves the judgement to the operator.
    ctx.manifest.gates.append(GateResult(
        "cutout_softness", True, round(partial, 4), None,
        f"{partial:.1%} of the cutout is partially transparent "
        f"(fabric declared {ctx.cfg.resolved_fabric().value})",
    ))
    return ctx


# ---------------------------------------------------------------- export


@REGISTRY.register("export")
def export(ctx: Context) -> Context:
    assert ctx.composited is not None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = ctx.source_path.stem.replace(" ", "-").lower()[:48]
    backdrop = ctx.extra.get("backdrop_used", ctx.cfg.background)
    seed = abs(hash(ctx.job_id)) % 9973

    for name in ctx.cfg.presets:
        preset = EXPORT_PRESETS[name]
        canvas = backgrounds.render(backdrop, (preset.width, preset.height), seed=seed)
        out, _ = compose(canvas, ctx.product, ctx.alpha)
        path = OUT_DIR / f"{stem}--{name}.jpg"
        out.save(path, "JPEG", quality=preset.quality, subsampling=1, optimize=True)
        ctx.exports[name] = str(path)
    ctx.store.json("export", "written", ctx.exports)
    return ctx


# ---- later phases, registered so a graph naming them fails loudly ---------

REGISTRY.register("recolour")(not_built(Phase.P3_COLOURWAY))
REGISTRY.register("shaded_recolour")(not_built(Phase.P4_SHADED))
REGISTRY.register("design_edit")(not_built(Phase.P5_DESIGN_EDIT))
REGISTRY.register("dummy")(not_built(Phase.P6_DUMMY))
