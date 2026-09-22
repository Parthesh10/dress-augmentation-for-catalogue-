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

import math

import numpy as np
from PIL import Image, ImageFilter, ImageOps

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
    if getattr(backend, "last_device", None):
        ctx.extra["matting_device"] = backend.last_device

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


def fit_custom_background(bg: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale-and-crop a photographed backdrop to the composite canvas size.

    Covers the canvas completely rather than stretching or letterboxing --
    the same "cover" fit any real photo gets when its own frame doesn't
    match the canvas exactly. Cropped from the centre: an operator's own
    backdrop photograph is more likely to have its actual subject (a floral
    arch, a doorway, a drape) centred than aligned to one edge.
    """
    cw, ch = size
    bw, bh = bg.size
    scale = max(cw / bw, ch / bh)
    nw, nh = max(int(bw * scale + 0.5), cw), max(int(bh * scale + 0.5), ch)
    resized = bg.convert("RGB").resize((nw, nh), Image.LANCZOS)
    x0, y0 = (nw - cw) // 2, (nh - ch) // 2
    return resized.crop((x0, y0, x0 + cw, y0 + ch))


def infer_key_direction(bg: Image.Image) -> tuple[float, float]:
    """A light direction guessed from a real photograph's own brightness.

    Only used for a **custom, operator-supplied** backdrop -- one of this
    project's own procedural presets carries an authored `key_direction`
    instead (see `backgrounds.key_direction`), because its light is a
    decision this project made, not something that has to be guessed. A
    real photograph's lighting can come from anywhere, including several
    sources at once or none obvious at all; this is a reasonable default so
    the contact shadow still falls in a plausible direction rather than a
    fixed one that may be wrong, not a claim to have actually found the
    light source.

    Sampled from the upper 60% of the frame -- where a real backdrop's own
    light source (a window, a sky, a lamp) shows up -- rather than the
    whole image, which would let a bright floor or a pale garment area bias
    the answer toward "brightest object" instead of "brightest direction".
    """
    arr = srgb_to_linear(_arr(bg))
    h, w = arr.shape[:2]
    luma = arr[: max(int(h * 0.6), 1)].mean(axis=2)
    weights = luma.sum(axis=0)
    if weights.sum() < 1e-6:
        return (-0.25, -0.45)
    xs = np.linspace(-1, 1, w, dtype=np.float32)
    cx = float((xs * weights).sum() / weights.sum())
    # Shadow falls away from the bright side, same convention as every
    # authored preset: key_dir points from the subject toward the light.
    return (float(np.clip(cx * 0.6, -0.4, 0.4)), -0.45)


@REGISTRY.register("background")
def background(ctx: Context) -> Context:
    """PHASE 2 — generate the backdrop the garment will stand in front of."""
    assert ctx.source is not None
    w, h = ctx.source.size
    scale = 1800 / max(w, h)
    size = (max(int(w * scale), 640), max(int(h * scale), 640)) if scale > 1 else (w, h)

    custom = ctx.extra.get("custom_background")
    if custom is not None:
        # An operator-supplied photograph, not one of this project's own
        # procedural presets -- see `ui.py`'s upload widget and the licence
        # note beside it. `key_luminance`/`key_direction` are measured from
        # the photograph itself rather than looked up, because there is no
        # authored preset to look them up from.
        ctx.background = fit_custom_background(custom, size)
        ctx.extra["backdrop_used"] = "custom"
        ctx.extra["composite_size"] = size
        lin = srgb_to_linear(_arr(ctx.background))
        ctx.extra["key_luminance"] = float((lin @ np.array([0.2126, 0.7152, 0.0722])).mean())
        ctx.extra["key_direction"] = infer_key_direction(ctx.background)

        # Where the floor is. An explicit floor line set by the operator
        # always wins; otherwise ask the ground detector (`ground.py`) --
        # run on the *original* upload, not the cover-cropped canvas, so
        # the answer is a property of the photograph and cached as one,
        # reused for every garment and every export size against it.
        want_floor = ctx.extra.get("custom_floor_frac") is None
        want_fill = ctx.extra.get("subject_fill") is None
        if want_floor or want_fill:
            from . import ground
            est = ground.detect_ground(custom)
            ctx.extra["ground_verdict"] = est.reason
            ctx.extra["ground_usable"] = est.usable
            if want_floor and est.floor_frac is not None:
                ctx.extra["custom_floor_frac"] = est.floor_frac
            if want_fill and est.suggested_fill() is not None:
                ctx.extra["subject_fill"] = est.suggested_fill()
            if not est.usable:
                # Not a hard failure: the operator may know better, and a
                # batch script may want the number to filter on rather than
                # an exception to catch. Loud, though.
                ctx.warn(f"backdrop photo looks unsuitable for a standing figure: {est.reason}")
        ctx.store.image("background", "custom", ctx.background)
        return ctx

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


def place(
    alpha: np.ndarray, product: Image.Image, size: tuple[int, int],
    floor_frac: float | None = None,
    *,
    fill: float | None = None,
    x_frac: float | None = None,
):
    """Scale the garment to fill the frame vertically, bounded by width.

    Bounded by **both**, and that is a bug inherited as a lesson rather than
    as code: the sibling scaled a decor hanging by height alone and a wide
    subject came out at 128% of the canvas, clipped off both edges, silently.
    A saree photographed spread out is exactly that shape.

    **Anchored near the bottom, not centred**, and that is a second bug found
    on a real photograph rather than inherited: centring left equal empty
    backdrop above the head and below the feet, which is not how a
    full-length photograph is ever actually framed and was a real
    contributor to a composite reading as obviously edited. Whatever
    vertical slack is left after scaling now goes almost entirely above the
    subject as headroom, with only a small margin held below -- see
    `THRESHOLDS.bottom_margin`.

    `floor_frac`, added 2026-09-20, overrides that fixed bottom margin with
    a specific line (as a fraction of canvas height) to plant the feet on
    instead. Every procedural preset's own floor is exactly at the canvas
    bottom, which is why they never needed this -- but a photographed
    backdrop's own floor can sit anywhere in frame (a table's edge, a raised
    porch, partway up a staircase), and no version of "how far above the
    bottom edge" is right for all of them. Deliberately **not** guessed
    automatically: a prototype edge-detector found *a* line in nearly every
    photograph tried, including a sea horizon and a framed painting with no
    floor in it at all, with no reliable way to tell those apart from a real
    one on pixels alone. This takes a number instead -- supplied once per
    backdrop photograph, not once per garment, which is the only reason
    "verified on 500 photographs" is a small amount of work rather than a
    large one: the number is a property of the backdrop, reused unchanged
    across every garment composited onto it.

    `fill` (2026-09-21) is how much of the available height the subject
    occupies -- `THRESHOLDS.garment_fill` when None. It exists because a
    subject the same size in every backdrop is wrong: a wide room and a
    tight drape are different distances from the camera, and a person
    should be smaller in the first. `stages.background` derives it per
    backdrop from how much floor is visible; the app can override it.
    `x_frac` is the subject's horizontal centre as a fraction of width,
    0.5 when None.
    """
    cw, ch = size
    ys, xs = np.nonzero(alpha > THRESHOLDS.alpha_floor)
    if len(xs) == 0:
        raise ValueError("nothing to composite — the matte is empty")
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    crop_a = alpha[y0:y1, x0:x1]
    crop_p = product.crop((int(x0), int(y0), int(x1), int(y1)))
    bw, bh = crop_p.size

    fill = THRESHOLDS.garment_fill if fill is None else float(np.clip(fill, 0.1, 1.0))
    # The vertical space actually available to fill against -- the whole
    # canvas ordinarily, but only down to the requested line when
    # `floor_frac` is set. Without this, a figure sized to fill 88% of the
    # *whole* canvas has no room left to also have its feet land partway
    # down the frame -- the two numbers would fight, and the fixed-size
    # figure would win, silently ignoring floor_frac whenever it asked for
    # less than the full canvas.
    ch_avail = ch * floor_frac if floor_frac is not None else ch
    scale = min(ch_avail * fill / bh, cw * fill / bw)
    nw, nh = max(int(bw * scale), 8), max(int(bh * scale), 8)

    p_res = crop_p.resize((nw, nh), Image.LANCZOS)
    a_res = np.asarray(
        Image.fromarray((np.clip(crop_a, 0, 1) * 255).astype(np.uint8), "L").resize(
            (nw, nh), Image.LANCZOS),
        dtype=np.float32,
    ) / 255.0

    xc = cw / 2 if x_frac is None else float(np.clip(x_frac, 0.0, 1.0)) * cw
    ox = int(np.clip(xc - nw / 2, 0, max(cw - nw, 0)))
    if floor_frac is not None:
        oy = int(np.clip(floor_frac, 0.0, 1.0) * ch) - nh
    else:
        bottom_margin = int(ch * THRESHOLDS.bottom_margin)
        oy = ch - nh - bottom_margin
    oy = max(oy, 0)
    return p_res, a_res, ox, oy


def contact_band(a_res: np.ndarray, ox: int, oy: int) -> tuple[float, float, float] | None:
    """Where the placed subject actually meets the ground: `(centre_x,
    contact_y, width)` in canvas pixels, read off the bottom slice of its
    own placed alpha. `None` if nothing solid reaches the bottom edge.

    One measurement, shared: the contact shadow and the contact feather
    (`soften_backdrop`) both sit on this so they cannot drift apart --
    the same reason `place` and the shadow already share `oy`.
    """
    T = THRESHOLDS
    h, w = a_res.shape
    band = max(int(h * T.contact_shadow_band), 2)
    coverage = a_res[-band:, :].mean(axis=0)
    xs = np.nonzero(coverage > T.contact_shadow_min_density)[0]
    if len(xs) == 0:
        return None
    x_lo, x_hi = float(xs.min()), float(xs.max())
    return ((x_lo + x_hi) / 2 + ox, float(oy + h), max(x_hi - x_lo, w * 0.15))


def contact_shadow(
    canvas_size: tuple[int, int],
    a_res: np.ndarray,
    ox: int,
    oy: int,
    key_dir: tuple[float, float] = (-0.25, -0.45),
) -> np.ndarray:
    """A soft shadow where the placed subject's lowest extent meets the frame.

    Read off the subject's **own** contact band -- the bottom slice of its
    already-placed alpha -- rather than a floor line guessed independently of
    where `place` happened to put things. The two are built from the same
    number this way and cannot drift apart.

    Deliberately a soft radial falloff rather than a hard-edged ellipse: a
    crisp shadow shape reads as painted on, and this only has to say "there
    is a surface here", not draw one.

    Returns a `(h, w)` field in [0, 1] at canvas resolution, 0 = no shadow.
    Composited as `canvas *= (1 - opacity * shadow)`.
    """
    T = THRESHOLDS
    cw, ch = canvas_size
    h, w = a_res.shape

    contact = contact_band(a_res, ox, oy)
    if contact is None:
        # Nothing solid enough at the bottom edge to ground -- a product shot
        # entirely in the air (e.g. jewellery, if this pipeline ever sees
        # some) has nothing to cast a shadow from, and that is correct.
        return np.zeros((ch, cw), np.float32)
    contact_cx, contact_y, contact_w = contact

    yy, xx = np.mgrid[0:ch, 0:cw].astype(np.float32)
    rx = max(contact_w * 0.55, 4.0)
    ry = max(rx * 0.32, 3.0)  # flat -- a shadow on a plane seen face-on

    # **Revised twice, 2026-09-22** -- see TASK.md §1p and §1q. The first
    # revision (pushing by 0.30 of `ry` instead of the original 0.85) was
    # still wrong: measured with an actual pixel diff against the
    # pre-revision render, it moved the peak by about 17px on a 2048px
    # frame -- a real change, too small to read as one, which is exactly
    # what the operator caught by eye when the "fixed" render still looked
    # identical. The peak now sits **exactly on the contact line** (offset
    # 0), not pushed below it at all: `shadow(contact_y) == 1.0` by
    # construction, so the darkest point of the shadow is always right
    # where the fabric ends, whatever `contact_band` measured that point
    # to be. Roughly half the ellipse's mass sits above the contact line
    # -- covered by the subject's own opaque paste wherever the fabric is
    # actually solid there -- and the other half is the visible pool below
    # it, touching by definition rather than by tuning a push distance to
    # happen to land close enough.
    off_x = -np.sign(key_dir[0]) * cw * 0.01
    off_y = 0.0

    dx = (xx - (contact_cx + off_x)) / rx
    dy = (yy - (contact_y + off_y)) / ry
    # Steeper than the original 1.4 -- concentrates the visible darkness
    # into an actual contact point instead of spreading it thin over the
    # whole ellipse. Part of the same 2026-09-22 revision (TASK.md §1q):
    # centring alone (`off_y = 0.0`, above) was still too faint to read as
    # touching anything once actually looked at, not just measured.
    ambient = np.exp(-2.2 * (dx * dx + dy * dy))

    # **A second, denser layer, added 2026-09-22 (TASK.md §1t)** -- compared
    # directly against a real contact shadow from an external tool
    # (Gemini/"Nano Banana"), the single-ellipse shadow above was still
    # visibly weaker: a real contact shadow isn't one soft gaussian, it's a
    # small, dense near-black core (where the object actually meets the
    # surface) fading into a much broader, fainter ambient falloff -- two
    # different rates of falloff, not one. `core` is the same shape at a
    # quarter the radius and a steeper coefficient; `np.maximum` with
    # `ambient` means the core only ever *adds* a wider near-max-dark
    # plateau right at the contact point, it never darkens the broad
    # ambient tail beyond what `ambient` alone already sets there.
    core_rx, core_ry = rx * 0.42, ry * 0.42
    dxc = (xx - (contact_cx + off_x)) / core_rx
    dyc = (yy - (contact_y + off_y)) / core_ry
    core = np.exp(-2.8 * (dxc * dxc + dyc * dyc))
    shadow = np.maximum(ambient, core)

    # Blurred relative to the shadow's *own* size, not the canvas as a whole
    # -- a blur radius comparable to or larger than `ry` was diluting the
    # peak by more than half before this, which was the other reason the
    # shadow was reading as invisible rather than merely soft.
    blur_px = max(int(ry * 0.35), int(min(cw, ch) * T.contact_shadow_blur * 0.4), 2)
    img = Image.fromarray((np.clip(shadow, 0, 1) * 255).astype(np.uint8), "L")
    img = img.filter(ImageFilter.GaussianBlur(blur_px))
    return np.asarray(img, dtype=np.float32) / 255.0


def harmonize_gain(
    bg_srgb: np.ndarray, ox: int, oy: int, w: int, h: int, *,
    custom: bool = False, scale: float = 1.0,
) -> np.ndarray:
    """The per-channel linear-light gain that lends the subject a sliver of
    the backdrop's own ambient colour, so it reads as lit by the same room
    rather than lit somewhere else and pasted in.

    Sampled from the backdrop pixels right around where the subject is about
    to stand -- not the whole frame, which would mix in wall and floor tones
    the subject's own lighting has no reason to share. Luminance is
    normalised out of the sample before comparing: a `cove` backdrop's floor
    is *brighter* than its wall by design (see `backgrounds._cove`), and
    that brightness step describes the backdrop's own geometry, not a colour
    the subject should be tinted toward.

    Bounded twice over -- once by `harmonize_strength`, which sets how much
    of the sampled cast is actually lent, and again by an absolute
    `harmonize_gain_min/max` clamp -- because this runs before the
    `colour_fidelity` gate, not instead of it, and the gate is the actual
    backstop against drifting the garment's true colour.

    `custom=True` halves both of those bounds -- see
    `Thresholds.harmonize_strength_custom`'s own comment for why an
    operator-uploaded backdrop photograph needs the more cautious setting
    while every built-in preset keeps the ordinary one.

    `scale` (2026-09-22) is the operator's own override on top of that --
    1.0 is the ordinary strength, 0 turns the tint off entirely. It only
    ever multiplies `strength`, never the `gmin`/`gmax` clamp: those stay
    the hard backstop against the `colour_fidelity` gate regardless of what
    the operator dials in, the same way `floor_frac` still can't place feet
    outside the canvas no matter what number is typed in.
    """
    T = THRESHOLDS
    strength = (T.harmonize_strength_custom if custom else T.harmonize_strength) * scale
    gmin = T.harmonize_gain_min_custom if custom else T.harmonize_gain_min
    gmax = T.harmonize_gain_max_custom if custom else T.harmonize_gain_max

    bh, bw = bg_srgb.shape[:2]
    cx = ox + w // 2
    radius = max(w // 2, 8)
    x0, x1 = max(cx - radius, 0), min(cx + radius, bw)
    y0, y1 = max(oy, 0), min(oy + h, bh)
    if x1 <= x0 or y1 <= y0:
        return np.ones(3, np.float32)

    patch = srgb_to_linear(bg_srgb[y0:y1, x0:x1]).reshape(-1, 3).mean(axis=0)
    luma = float(patch.mean())
    if luma < 1e-6:
        return np.ones(3, np.float32)
    cast = patch / luma  # colour only, brightness normalised out

    gain = 1.0 + strength * (cast - 1.0)
    return np.clip(gain, gmin, gmax).astype(np.float32)


def exposure_gain(
    scene_luminance: float | None, *, custom: bool = False, scale: float = 1.0,
) -> float:
    """A single brightness multiplier nudging the subject toward the
    backdrop's own light level.

    Colour cast is `harmonize_gain`'s job; this is the other half of
    "lit by the same room" -- a garment photographed in dull shade stays
    conspicuously dull against a bright sunlit backdrop, and conspicuously
    bright against a dark drape, however well its colour is matched.

    **Perceptual difference, not a linear-light ratio.** The backdrop
    library's luminance is bimodal (see
    `Thresholds.exposure_reference_luminance`); a ratio would ask for a 93%
    darkening on the darkest preset and flatten all four dark ones onto the
    clamp. The sRGB-space difference against a mid-library reference
    spreads them sensibly and keeps the nudge small.

    **This deliberately does not try to match the backdrop's brightness.**
    A white dress against a near-black drape should stay white; the claim
    is only "this scene is dimmer than average, so light the subject a
    little dimmer", never "make the subject as dark as the backdrop".

    Returns 1.0 (no change) when the backdrop's luminance is unknown.
    """
    if scene_luminance is None:
        return 1.0
    T = THRESHOLDS
    strength = (T.exposure_strength_custom if custom else T.exposure_strength) * scale
    gmin = T.exposure_gain_min_custom if custom else T.exposure_gain_min
    gmax = T.exposure_gain_max_custom if custom else T.exposure_gain_max
    pair = linear_to_srgb(
        np.array([scene_luminance, T.exposure_reference_luminance], np.float32))
    delta = float(pair[0] - pair[1])
    return float(np.clip(1.0 + strength * delta, gmin, gmax))


def soften_backdrop(
    bg: Image.Image,
    contact_y: float | None = None,
    contact_x: float | None = None,
    contact_w: float | None = None,
    strength: float | None = None,
) -> Image.Image:
    """Feather the backdrop where the subject's feet meet it. Nothing else.

    **Third design, after two were looked at and rejected on real
    photographs.** The first blurred the whole backdrop lightly and a band
    at the feet heavily: the band put a stripe across floorboards. The
    second kept the overall blur and ramped it toward the bottom edge: the
    stripe went, but the whole lower floor became a wash -- and, the actual
    finding, *any* whole-frame blur beside a razor-sharp HD cutout reads as
    a mismatch on its own. A sharp subject on a uniformly soft scene is not
    what "in focus" looks like; it's what "pasted on" looks like.

    So: **no overall blur at all.** The backdrop stays as sharp as the
    subject everywhere, which is the honest state of a real photograph at
    this scale. The only thing softened is a small, feathered zone right at
    the contact line -- the one place a paste seam actually exists -- and it
    is localised in both axes: a Gaussian in y around `contact_y`, and a
    broad Gaussian in x around `contact_x` with radius scaled to
    `contact_w`, the subject's own footprint. That second axis is what stops
    it ever becoming a stripe across a wide floor: the far left and right of
    the frame are untouched. Calibrated by eye against five variants on a
    herringbone floor (`work-reports/blur-calibration-2026-09-21/`), where
    this one was the only one that softened the seam while leaving the
    boards legible.

    `strength` scales the blur radius (1.0 = `THRESHOLDS.foot_blur_frac`,
    0 = off) so the operator can override it from the app; `None` means the
    default. With no `contact_y`, the backdrop is returned untouched.
    """
    T = THRESHOLDS
    if contact_y is None:
        return bg
    s = T.foot_blur_strength if strength is None else float(strength)
    if s <= 0:
        return bg
    short = min(bg.size)
    foot_px = int(round(short * T.foot_blur_frac * s))
    if foot_px < 1:
        return bg
    heavy = bg.filter(ImageFilter.GaussianBlur(foot_px))

    w_img, h = bg.size
    cy = float(np.clip(contact_y, 0, h - 1))
    band = max(h * T.foot_blur_band, 4.0)
    yy = np.arange(h, dtype=np.float32)
    dy = (yy - cy) / band
    # Windowed at 3 sigma so "untouched" means untouched: beyond it the
    # weight is exactly 0, not a Gaussian tail that dithers the far frame
    # by a level or two.
    wy = np.where(np.abs(dy) < 3.0, np.exp(-0.5 * dy * dy), 0.0).astype(np.float32)
    if contact_x is not None and contact_w:
        xr = max(float(contact_w) * T.foot_blur_x_radius, 8.0)
        xx = np.arange(w_img, dtype=np.float32)
        dx = (xx - float(contact_x)) / xr
        wx = np.where(np.abs(dx) < 3.0, np.exp(-0.5 * dx * dx), 0.0).astype(np.float32)
    else:
        wx = np.ones(w_img, np.float32)
    weight = (wy[:, None] * wx[None, :])[..., None]
    base_arr = np.asarray(bg, np.float32)
    heavy_arr = np.asarray(heavy, np.float32)
    out = base_arr * (1.0 - weight) + heavy_arr * weight
    # rint, not a bare astype: the blend of two identical values lands on
    # e.g. 119.99999 in float32, and astype truncates that to 119 -- a
    # one-level dither across the whole backdrop, caught by the flat-field
    # test rather than assumed away.
    return Image.fromarray(np.clip(np.rint(out), 0, 255).astype(np.uint8), "RGB")


def depth_blur_backdrop(
    bg: Image.Image, ox: int, oy: int, w: int, h: int, strength: float | None = None,
) -> Image.Image:
    """Soften whatever in the backdrop is genuinely far from the subject, while
    leaving the subject's own depth -- its silhouette and whatever immediately
    flanks it -- sharp. The portrait-lens look asked for directly, 2026-09-22:
    subject in focus, background gently soft, the way a real shallow depth of
    field looks, not a uniform wash.

    **Distinct from the whole-frame blur already tried and rejected twice**
    (`soften_backdrop`'s docstring, and `Thresholds.foot_blur_frac`'s): both
    of those applied one strength across the *entire* backdrop, including the
    wall and floor immediately beside the subject -- which is what read as "a
    sharp cutout on a uniformly soft photo" rather than "a sharp subject with
    a naturally soft background". This is zero within a margin around the
    subject's own footprint (an elliptical near-zone, wider than tall -- a
    standing figure's own depth-of-field "safe zone" in a typical portrait
    framing is mostly horizontal) and only grows with real distance from it.

    `strength` scales the blur radius (1.0 = ordinary, 0 = off), the same
    convention as `soften_backdrop`'s own `strength`; `None` means the
    default. Works identically on a procedural preset or a photographed
    custom backdrop -- there is no depth model to be wrong about, only
    distance from the subject in the frame.
    """
    T = THRESHOLDS
    s = T.depth_blur_strength if strength is None else float(strength)
    if s <= 0 or w <= 0 or h <= 0:
        return bg
    blur_px = max(int(round(min(bg.size) * T.depth_blur_frac * s)), 0)
    if blur_px < 1:
        return bg

    cw, ch = bg.size
    cx, cy = ox + w / 2.0, oy + h / 2.0
    near_x = max(w * T.depth_blur_near_x / 2.0, cw * 0.06)
    near_y = max(h * T.depth_blur_near_y / 2.0, ch * 0.06)
    yy, xx = np.mgrid[0:ch, 0:cw].astype(np.float32)
    d = np.hypot((xx - cx) / near_x, (yy - cy) / near_y)
    t = np.clip((d - 1.0) / T.depth_blur_falloff, 0.0, 1.0)
    weight = (t * t * (3 - 2 * t))[..., None]  # smoothstep; 0 at/near the subject

    heavy = bg.filter(ImageFilter.GaussianBlur(blur_px))
    base_arr = np.asarray(bg, np.float32)
    heavy_arr = np.asarray(heavy, np.float32)
    out = base_arr * (1.0 - weight) + heavy_arr * weight
    # rint, not a bare astype -- see `soften_backdrop`'s own comment; the
    # same one-level dither on an otherwise-flat region was found here too.
    return Image.fromarray(np.clip(np.rint(out), 0, 255).astype(np.uint8), "RGB")


def exposure_gain_field(
    shape: tuple[int, int], key_dir: tuple[float, float],
    scene_luminance: float | None, *, custom: bool = False, scale: float = 1.0,
) -> np.ndarray:
    """`exposure_gain`'s directional refinement: an `(h, w)` field of
    per-pixel brightness multipliers across the subject's own footprint,
    instead of one flat number applied everywhere.

    A flat multiplier reads as "the exposure slider was nudged", because
    real light never lands on a standing figure evenly -- the side toward
    the key light is a little brighter, the side away from it a little
    darker. This shapes the *same* budget `exposure_gain` already spends
    into a gradient along `key_dir` instead of spreading it evenly, which
    is what makes it read as shaped by the scene's light rather than
    merely dimmed or brightened by it -- covered by the shading-only
    relighting exception (CLAUDE.md, 2026-09-21): a pure per-pixel scalar
    on luminance, nothing touching hue, print or embroidery.

    **Centred on the same flat gain, not a bigger swing on top of it** --
    `Thresholds.shading_spread` sets how much the two sides diverge from
    it, and that divergence is deliberately allowed to be more visible
    than the flat clamp alone: `gates()` compares the *mean* Lab colour of
    the whole product region, and a swing that is brighter on one side and
    darker on the other in roughly equal measure moves that mean only
    slightly even when the swing itself is larger than the flat version's
    own bound -- measured on a real photograph before being trusted (see
    TASK.md §1o), not assumed from the arithmetic alone.
    """
    flat = exposure_gain(scene_luminance, custom=custom, scale=scale)
    h, w = shape
    h, w = max(h, 1), max(w, 1)
    # No known backdrop luminance means no adjustment at all -- `exposure_
    # gain` returns exactly 1.0 for this case, and the field must match it
    # exactly rather than inventing a directional shading pattern with
    # nothing to base it on.
    if scene_luminance is None:
        return np.full((h, w), flat, np.float32)

    nx, ny = key_dir
    norm = math.hypot(nx, ny) or 1.0
    nx, ny = nx / norm, ny / norm
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    # -1..1 across the subject along the key-light axis, zero-mean by
    # construction (a linear ramp centred on the footprint) -- which is
    # exactly what keeps the *mean* colour shift close to the flat
    # version's while the local swing is bigger.
    proj = (xx / max(w - 1, 1) - 0.5) * nx + (yy / max(h - 1, 1) - 0.5) * ny
    proj = proj / (np.abs(proj).max() + 1e-6)

    T = THRESHOLDS
    spread = (T.shading_strength_custom if custom else T.shading_spread) * scale
    field = flat + spread * -proj
    gmin = T.exposure_gain_min_custom if custom else T.exposure_gain_min
    gmax = T.exposure_gain_max_custom if custom else T.exposure_gain_max
    # A wider safety margin than the flat clamp, not the same one -- the
    # mean-preserving argument above bounds the *gate's* exposure, not
    # what an individual pixel could swing to, and this is the backstop
    # against that regardless of how large `shading_spread` is tuned.
    return np.clip(field, gmin * 0.9, gmax * 1.15).astype(np.float32)


def apply_finishing(
    canvas_srgb: np.ndarray, strength: float | None = None, seed: int = 0,
    *, custom: bool = False,
) -> np.ndarray:
    """One last pass over the **entire finished frame** -- subject and
    backdrop alike -- the thing nothing else in this pipeline touches.
    Every other realism fix (tint, exposure, the two blurs, the shadow)
    operates on the subject region or the contact area only; this is what
    was missing to make the *whole photograph* read as one exposure
    rather than a subject placed onto a backdrop, however well each part
    was separately handled. See `Thresholds`' own "whole-frame finishing
    pass" comment for the reasoning this was built from -- a direct
    comparison against an external tool's output on 2026-09-22.

    Three small, ordinary things a camera's own JPEG pipeline already
    does, applied here explicitly:

    1. **Grain, uniform across the whole canvas.** `backgrounds.render`'s
       own grain lives in the backdrop only, baked in before the subject
       is pasted -- so the pasted subject always had *less* grain than
       what surrounds it, a small but real mismatch a real single-exposure
       photograph never has.
    2. **A mild contrast lift**, in sRGB space around the 0.5 midpoint --
       gamma-encoded space, matching where a camera's own tone curve
       actually applies it, not linear light.
    3. **A whole-frame vignette** -- unlike the procedural backdrops' own
       vignette (baked into the backdrop only), this darkens the true
       corners of the finished canvas, subject included.

    `strength` scales all three together (1.0 = ordinary, 0 = off), same
    convention as every other override in this module. Deliberately one
    knob, not three -- these read as a single "how much does this look
    like one photograph" effect, not three independent choices.

    `custom=True` (2026-09-22, CLAUDE.md "Next actionables" §1) raises
    grain and vignette to their `_custom` values -- found necessary on a
    real photographed backdrop (a gravel path) where the ordinary strength
    measured as present but read as invisible against the backdrop's own
    texture. Contrast is left at the ordinary value regardless: it is the
    one knob here with the least measured headroom under `colour_fidelity`
    (TASK.md §1t), and raising it for custom backdrops needs the same
    real-photo measurement before it can be trusted, not a guess.
    """
    T = THRESHOLDS
    s = T.finishing_strength if strength is None else float(strength)
    if s <= 0:
        return canvas_srgb

    h, w = canvas_srgb.shape[:2]
    out = canvas_srgb.astype(np.float32)

    # Contrast: an S-curve around the midpoint, small enough to answer to
    # the same colour_fidelity budget as every other knob here (measured,
    # not assumed -- see TASK.md §1t).
    contrast = T.finishing_contrast * s
    out = 0.5 + (out - 0.5) * (1.0 + contrast)

    # Vignette across the *whole* canvas -- aspect-corrected so it reads as
    # a lens falloff, not an oval stretched to the frame's own shape.
    vignette = T.finishing_vignette_custom if custom else T.finishing_vignette
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ar = w / h
    nx, ny = (xx / w - 0.5) * 2 * ar, (yy / h - 0.5) * 2
    r = np.clip(np.hypot(nx, ny) / 1.9, 0, 1)
    out *= (1 - vignette * s * r * r)[..., None]

    # Grain: zero-mean, so it doesn't shift measured colour on average,
    # only adds the texture a real sensor always has.
    grain_amp = T.finishing_grain_custom if custom else T.finishing_grain
    rng = np.random.default_rng(seed)
    grain = rng.normal(0.0, grain_amp * s, (h, w, 1)).astype(np.float32)
    out += grain

    return np.clip(out, 0, 1)


def compose(
    bg: Image.Image,
    product: Image.Image,
    alpha: np.ndarray,
    key_dir: tuple[float, float] = (-0.25, -0.45),
    *,
    custom_backdrop: bool = False,
    floor_frac: float | None = None,
    fill: float | None = None,
    x_frac: float | None = None,
    blur_strength: float | None = None,
    key_dir_x: float | None = None,
    harmonize_scale: float | None = None,
    scene_luminance: float | None = None,
    exposure_scale: float | None = None,
    depth_blur_strength: float | None = None,
    finishing_strength: float | None = None,
    finishing_seed: int = 0,
):
    """Alpha-composite in linear light. Fractional alpha is honoured exactly.

    The contact shadow is drawn into the canvas **before** the subject is
    pasted, not after -- pasting afterwards would either paint the shadow
    over the subject's own feet or need a second mask to avoid it. Drawing
    it first and letting the paste's own alpha blend over it means the
    shadow only ever shows where there is no subject, which is exactly the
    area it exists to describe.

    `floor_frac`, `fill`, `x_frac`, `blur_strength`, `key_dir_x`,
    `harmonize_scale`, `depth_blur_strength` and `finishing_strength` are
    all `None` for "decide automatically" -- the app's override controls
    set them. `key_dir_x` replaces only the horizontal component of
    `key_dir` (which side the shadow falls away from, and now which side
    reads brighter under `exposure_gain_field`); the vertical component --
    how steep the light is -- stays whatever the backdrop's own authored
    or inferred value was, since nothing asked for control over that.
    """
    if key_dir_x is not None:
        key_dir = (float(key_dir_x), key_dir[1])
    p_res, a_res, ox, oy = place(alpha, product, bg.size, floor_frac, fill=fill, x_frac=x_frac)
    h, w = a_res.shape

    # The backdrop softens in two independent ways before the subject is
    # pasted on top of it: a broad, distance-from-subject depth-of-field
    # blur (the portrait-lens look -- see `depth_blur_backdrop`), and a
    # small feathered patch right at the feet where an actual paste seam
    # exists (see `soften_backdrop` for the two whole-frame designs tried
    # and rejected before that one). Done here, per call, so both are sized
    # to whatever resolution this particular export actually is (`export`
    # calls `compose` once per preset size).
    bg = depth_blur_backdrop(bg, ox, oy, w, h, strength=depth_blur_strength)
    contact = contact_band(a_res, ox, oy)
    if contact is not None:
        cx, cy, cw_ = contact
        bg = soften_backdrop(bg, contact_y=cy, contact_x=cx, contact_w=cw_,
                             strength=blur_strength)
    bg_srgb = _arr(bg)
    canvas = srgb_to_linear(bg_srgb)

    shadow = contact_shadow(bg.size, a_res, ox, oy, key_dir)
    shadow_opacity = (THRESHOLDS.contact_shadow_opacity_custom if custom_backdrop
                       else THRESHOLDS.contact_shadow_opacity)
    canvas *= (1 - shadow_opacity * shadow)[..., None]

    gain = harmonize_gain(bg_srgb, ox, oy, w, h, custom=custom_backdrop,
                          scale=1.0 if harmonize_scale is None else harmonize_scale)
    # Colour cast and exposure are the two halves of "lit by the same
    # room"; both multiply the subject in linear light, both bounded, and
    # both answerable to the colour_fidelity gate downstream. Exposure is
    # now a field, not a scalar -- see `exposure_gain_field` for why a
    # directional swing here is affordable against the same gate.
    exp_field = exposure_gain_field(
        (h, w), key_dir, scene_luminance, custom=custom_backdrop,
        scale=1.0 if exposure_scale is None else exposure_scale)
    piece = srgb_to_linear(_arr(p_res)) * gain[None, None, :] * exp_field[..., None]
    region = canvas[oy:oy + h, ox:ox + w]
    a = a_res[..., None]
    canvas[oy:oy + h, ox:ox + w] = piece * a + region * (1 - a)
    scene_alpha = np.zeros(canvas.shape[:2], np.float32)
    scene_alpha[oy:oy + h, ox:ox + w] = a_res
    out_srgb = linear_to_srgb(np.clip(canvas, 0, 1))
    out_srgb = apply_finishing(out_srgb, finishing_strength, seed=finishing_seed,
                                custom=custom_backdrop)
    return _img(out_srgb), scene_alpha


def _placement_overrides(ctx: Context) -> dict:
    """The operator's (or the detector's) placement decisions, as `compose`
    kwargs. One place, because `composite` and `export` both call
    `compose` and an override honoured by one but not the other would
    make the preview lie about the file.

    `finishing_seed` is derived from the job id, not left at `compose`'s
    own default -- deterministic per job (the same job re-exported lands
    on the same grain), but not identical across every different photo the
    way a bare default of 0 would be.
    """
    return dict(
        floor_frac=ctx.extra.get("custom_floor_frac"),
        fill=ctx.extra.get("subject_fill"),
        x_frac=ctx.extra.get("subject_x"),
        blur_strength=ctx.extra.get("seam_blur_strength"),
        key_dir_x=ctx.extra.get("light_dir_x"),
        harmonize_scale=ctx.extra.get("tint_strength"),
        scene_luminance=ctx.extra.get("key_luminance"),
        exposure_scale=ctx.extra.get("exposure_strength"),
        depth_blur_strength=ctx.extra.get("depth_blur_strength"),
        finishing_strength=ctx.extra.get("finishing_strength"),
        finishing_seed=abs(hash(ctx.job_id)) % 9973,
    )


@REGISTRY.register("composite")
def composite(ctx: Context) -> Context:
    assert ctx.background is not None and ctx.product is not None and ctx.alpha is not None
    key_dir = ctx.extra.get("key_direction", (-0.25, -0.45))
    is_custom = ctx.extra.get("custom_background") is not None
    out, scene_alpha = compose(
        ctx.background, ctx.product, ctx.alpha, key_dir, custom_backdrop=is_custom,
        **_placement_overrides(ctx))
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
    key_dir = ctx.extra.get("key_direction", (-0.25, -0.45))
    custom = ctx.extra.get("custom_background")
    seed = abs(hash(ctx.job_id)) % 9973

    for name in ctx.cfg.presets:
        preset = EXPORT_PRESETS[name]
        # Each export size gets the backdrop rendered fresh at its own exact
        # resolution, rather than resizing `composite`'s single working-size
        # canvas -- a procedural preset renders identically either way, but
        # a photographed one does not: resizing an already-cover-cropped
        # canvas a second time would crop it twice. `fit_custom_background`
        # re-covers straight from the original upload each time instead.
        canvas = (
            fit_custom_background(custom, (preset.width, preset.height))
            if custom is not None
            else backgrounds.render(backdrop, (preset.width, preset.height), seed=seed)
        )
        out, _ = compose(
            canvas, ctx.product, ctx.alpha, key_dir, custom_backdrop=custom is not None,
            **_placement_overrides(ctx))
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
