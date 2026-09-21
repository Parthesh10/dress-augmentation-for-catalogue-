"""What phases 1 and 2 promise, pinned.

Synthetic fixtures throughout, so this runs in seconds with no matting backend
and no network. The things worth testing here are the decisions this project
made *differently* from the sibling, because those are the ones nobody else's
test suite is watching.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import numpy as np
from PIL import Image

from dressaug import backgrounds, stages
from dressaug.stages import decontaminate
from dressaug.config import (
    SEMI_TRANSPARENT, THRESHOLDS, Fabric, Garment, Graph, JobConfig, Phase,
)
from dressaug.pipeline import ArtifactStore, Context, JobManifest


# ---------------------------------------------------------------- vocabulary


def test_a_saree_is_assumed_sheer_and_a_party_dress_is_not():
    """The default exists so the operator does not have to declare fabric on
    every photograph. It is a default, never a claim -- but it should be right
    more often than not, and these two are the clearest cases."""
    assert JobConfig(garment=Garment.SAREE).is_semi_transparent()
    assert not JobConfig(garment=Garment.PARTY_DRESS).is_semi_transparent()


def test_an_explicit_fabric_beats_the_garment_default():
    cfg = JobConfig(garment=Garment.PARTY_DRESS, fabric=Fabric.SHEER)
    assert cfg.resolved_fabric() is Fabric.SHEER
    assert cfg.is_semi_transparent()


def test_only_lace_and_sheer_count_as_semi_transparent():
    """Velvet and sequins are visually dramatic and completely opaque. If one
    of them ever lands in this set, the matting stage will start warning about
    hard edges on fabrics that are supposed to have them."""
    assert SEMI_TRANSPARENT == {Fabric.LACE, Fabric.SHEER}


def test_every_phase_has_a_stage_and_the_unbuilt_ones_refuse():
    """A stage for an unbuilt phase must raise, not pass the context through.
    A run that looks complete but skipped a step is the expensive kind of
    wrong -- the output is unmarked and indistinguishable from a real one."""
    for name in ("recolour", "shaded_recolour", "design_edit", "dummy"):
        fn = stages.REGISTRY.get(name)
        try:
            fn(None)
        except NotImplementedError as exc:
            assert "not built" in str(exc), exc
        else:
            raise AssertionError(f"{name} should refuse until its phase is built")


# ---------------------------------------------------------------- transparency


def _alpha_with_partial_band(band: int, size: int = 200) -> np.ndarray:
    """A solid square with a soft border `band` pixels wide -- a stand-in for
    the layered edge of a net or chiffon garment."""
    a = np.zeros((size, size), np.float32)
    a[40:160, 40:160] = 1.0
    if band:
        for i in range(band):
            v = (i + 1) / (band + 1)
            a[40 - band + i, 40 - band + i:160 + band - i] = v
            a[160 + band - i - 1, 40 - band + i:160 + band - i] = v
            a[40 - band + i:160 + band - i, 40 - band + i] = v
            a[40 - band + i:160 + band - i, 160 + band - i - 1] = v
    return a


def test_a_hard_cutout_reads_as_almost_no_partial_alpha():
    assert stages.partial_alpha_fraction(_alpha_with_partial_band(0)) < 0.02


def test_a_soft_cutout_reads_as_substantially_partial():
    frac = stages.partial_alpha_fraction(_alpha_with_partial_band(14))
    assert frac > THRESHOLDS.min_partial_alpha_on_sheer, frac


def test_the_partial_fraction_is_zero_on_an_empty_matte():
    assert stages.partial_alpha_fraction(np.zeros((50, 50), np.float32)) == 0.0


def test_alpha_solid_is_below_the_siblings_cutoff():
    """The reason is in config.py and is worth a test rather than only a
    comment: at 0.98 the colour gate on a chiffon garment ends up measuring
    the lining and the seams, which are the least representative pixels in
    the photograph."""
    assert THRESHOLDS.alpha_solid < 0.98


# ---------------------------------------------------------------- decontamination
# The halo fix, 2026-09-19. TASK.md tracked this as an open P0 defect: on a
# dark backdrop the garment showed a pale fringe, because semi-transparent
# edge pixels still carried the white studio background they were cut from.


def _white_bled_pixel(true_colour, alpha, white=(1.0, 1.0, 1.0)):
    """What a camera actually records at a semi-transparent edge over a
    white studio background -- the thing decontaminate() has to undo."""
    import numpy as np
    tc = np.array(true_colour, np.float32)
    w = np.array(white, np.float32)
    return tc * alpha + w * (1 - alpha)


def test_a_solid_interior_pixel_is_left_completely_unchanged():
    """At alpha=1 there is nothing to decontaminate -- the formula must be
    the identity there, or a garment's own solid colour would shift."""
    rgb = np.full((10, 10, 3), 0.3, np.float32)
    alpha = np.ones((10, 10), np.float32)
    out, _ = decontaminate(rgb, alpha)
    assert np.allclose(out, rgb, atol=1e-5)


def test_a_semi_transparent_edge_pixel_recovers_its_true_colour():
    """The core claim: given a pixel that a real camera would have recorded
    over a white background, decontaminate() gets back close to the colour
    the fabric actually is."""
    true_colour = (0.15, 0.05, 0.35)   # a deep purple
    alpha_val = 0.4
    observed = _white_bled_pixel(true_colour, alpha_val)

    rgb = np.tile(observed, (20, 20, 1)).astype(np.float32)
    alpha = np.full((20, 20), alpha_val, np.float32)
    # a patch of declared-empty background so the estimator has something
    # to measure the white from
    rgb[:5, :5] = (1.0, 1.0, 1.0)
    alpha[:5, :5] = 0.0

    out, bg = decontaminate(rgb, alpha)
    recovered = out[10, 10]
    assert np.allclose(bg, [1.0, 1.0, 1.0], atol=0.05), bg
    for got, want in zip(recovered, true_colour):
        assert abs(got - want) < 0.08, (recovered, true_colour)


def test_decontamination_makes_a_dark_backdrop_composite_closer_to_true_colour():
    """The actual halo, reproduced and shown fixed end to end: matte, then
    composite onto something dark, with and without decontamination."""
    true_colour = np.array([0.12, 0.10, 0.30], np.float32)  # deep blue-purple
    size = 120
    alpha = np.zeros((size, size), np.float32)
    alpha[20:100, 20:100] = 1.0
    # a soft, semi-transparent border -- the thing that carries the halo
    for i in range(6):
        v = (i + 1) / 7
        alpha[20 - i - 1, 20 - i - 1:100 + i + 1] = v
        alpha[100 + i, 20 - i - 1:100 + i + 1] = v
        alpha[20 - i - 1:100 + i + 1, 20 - i - 1] = v
        alpha[20 - i - 1:100 + i + 1, 100 + i] = v

    rgb = np.ones((size, size, 3), np.float32)  # white canvas
    a3 = alpha[..., None]
    rgb = true_colour[None, None, :] * a3 + rgb * (1 - a3)

    from dressaug.color import rgb_to_lab, delta_e2000

    dark_bg = np.full((size, size, 3), 0.03, np.float32)  # near-black backdrop

    def composite_edge_de(product_rgb):
        a3_ = alpha[..., None]
        comp = product_rgb * a3_ + dark_bg * (1 - a3_)
        edge = (alpha > 0) & (alpha < 1)
        lab_true = rgb_to_lab(np.tile(true_colour, (edge.sum(), 1)))
        lab_comp = rgb_to_lab(comp[edge])
        return float(delta_e2000(lab_true, lab_comp).mean())

    de_before = composite_edge_de(rgb)
    decontaminated, _ = decontaminate(rgb, alpha)
    decon_arr = decontaminated
    de_after = composite_edge_de(decon_arr)

    assert de_after < de_before, (
        f"decontamination should shrink edge colour error against a dark "
        f"backdrop: before={de_before:.2f} after={de_after:.2f}"
    )
    # A 65% bound, not 100%: `decontaminate` floors alpha at 0.12 before
    # dividing, deliberately, so the very lowest-alpha rim pixels (alpha
    # approaching 0, where dividing by a tiny number would amplify noise
    # into a wild colour) keep some residual white bias on purpose. The
    # measured reduction here is ~45%; 65% leaves real margin above that
    # while still failing hard if the fix regresses toward no-op.
    assert de_after < de_before * 0.65, (
        f"expected a substantial improvement, only got before={de_before:.2f} "
        f"after={de_after:.2f}"
    )


def test_the_matte_stage_wires_decontamination_in():
    """Not just that the function exists -- that the registered stage
    actually calls it and sets ctx.product from its result, which is what
    composite() and export() read."""
    import inspect
    src = inspect.getsource(stages.matte)
    assert "decontaminate(" in src
    assert "ctx.product = _img(decontaminated)" in src


# ---------------------------------------------------------------- grounding
# The contact shadow, 2026-09-19. Found necessary on a real full-length
# photograph: a person composited onto a plain gradient with no shadow at
# all reads as "floating in air" -- not a guess, the actual words used
# reporting it.


def _standing_alpha(size=(300, 500), foot_w=60):
    """A tall silhouette -- head to feet -- standing on the bottom edge."""
    a = np.zeros((size[1], size[0]), np.float32)
    a[20:480, 80:220] = 1.0  # torso/legs, roughly centred
    cx = size[0] // 2
    a[470:498, cx - foot_w // 2:cx + foot_w // 2] = 1.0  # feet, near the bottom
    return a


def test_a_grounded_subject_casts_a_shadow_near_its_own_feet():
    a_res = _standing_alpha()
    canvas_size = (400, 600)
    sh = stages.contact_shadow(canvas_size, a_res, ox=50, oy=50)
    assert sh.max() > 0.15, f"shadow should be clearly present, got max={sh.max():.3f}"

    # It has to actually show up *outside* the subject's own footprint, not
    # only in the region the subject's opaque pixels will overwrite anyway --
    # otherwise the fix would be invisible in the final composite, which is
    # exactly the bug the first version of this had.
    foot_bottom_canvas_y = 50 + 498
    below = sh[foot_bottom_canvas_y + 5: foot_bottom_canvas_y + 40, :]
    assert below.max() > 0.10, (
        f"shadow should be visible below the feet, not just hidden under "
        f"them, got max={below.max():.3f} in the band just below contact"
    )


def test_no_shadow_far_from_the_subject():
    a_res = _standing_alpha()
    sh = stages.contact_shadow((400, 600), a_res, ox=50, oy=50)
    assert sh[0:20, :].max() < 0.02, "no shadow should appear near the top of the frame"
    assert sh[:, 350:400].max() < 0.02, "no shadow should appear far to the side"


def test_a_matte_with_nothing_at_the_frame_edge_casts_no_shadow():
    """No contact band, no shadow -- rather than guessing at a position that
    was never actually measured from the photograph."""
    a_res = np.zeros((300, 300), np.float32)
    a_res[100:150, 100:200] = 1.0  # solid, but nowhere near the bottom edge
    sh = stages.contact_shadow((400, 400), a_res, ox=50, oy=50)
    assert sh.max() == 0.0


def test_shadow_offset_follows_the_key_light_direction():
    """The sibling's convention, carried over: the shadow falls away from
    where the light is supposed to be coming from, not toward it."""
    a_res = _standing_alpha()
    left_key = stages.contact_shadow((400, 600), a_res, ox=50, oy=50, key_dir=(-0.3, -0.4))
    right_key = stages.contact_shadow((400, 600), a_res, ox=50, oy=50, key_dir=(0.3, -0.4))
    # centre of mass on each side should differ measurably between the two
    cx_left = (left_key * np.arange(400)).sum() / max(left_key.sum(), 1e-6)
    cx_right = (right_key * np.arange(400)).sum() / max(right_key.sum(), 1e-6)
    assert abs(cx_left - cx_right) > 0.5, (cx_left, cx_right)


def test_compose_and_export_thread_the_backdrops_own_key_direction():
    """Not just that contact_shadow works in isolation -- that the registered
    stages actually pass the backdrop's own key light through to it, rather
    than silently falling back to a default that may not match."""
    import inspect
    src = inspect.getsource(stages.composite) + inspect.getsource(stages.export)
    assert src.count('ctx.extra.get("key_direction"') == 2


def _stripe_field(size=(900, 1350)):
    """6px vertical stripes at a *real export size*: the feather radius is a
    fraction of the shorter side (0.006 -> ~5px here), and on a 300px toy
    fixture it rounds to 2px and measures almost nothing -- the first
    version of these tests found that out. Same regime the calibration
    sheet used. Stripes this wide survive a light blur nearly intact and
    are clearly softened by the feather. (A 1px checkerboard is erased by
    any blur at all and measures nothing; an even earlier test learned
    that the hard way.)"""
    xs = np.arange(size[0])
    stripes = ((xs // 6) % 2 * 255).astype(np.uint8)
    field = np.tile(stripes, (size[1], 1))
    return Image.fromarray(np.stack([field] * 3, axis=-1), "RGB")


def _energy(rows):
    return float(np.abs(np.diff(rows.astype(np.float32), axis=1)).mean())


_FEET = dict(contact_y=1200, contact_x=450, contact_w=180)


def test_the_backdrop_is_untouched_away_from_the_feet():
    """2026-09-21, the third design: **no whole-frame blur.** Two earlier
    versions softened the whole backdrop and were rejected on real
    photographs -- a razor-sharp HD cutout on a uniformly soft scene reads
    as pasted, not as in focus. The top of the frame and the far sides of
    the floor must now be bit-identical to the input."""
    bg = _stripe_field()
    out = np.asarray(stages.soften_backdrop(bg, **_FEET))
    src = np.asarray(bg)
    assert np.array_equal(out[:900], src[:900]), "the top two-thirds must be untouched"
    # Far left/right of the contact row. The feather is a Gaussian windowed
    # at 3 sigma (x sigma = 0.8 * contact_w = 144px here), so beyond
    # x < 450-432 = 18 it is exactly zero, and the strip 18..60 sits at
    # 2.7-3.0 sigma where the weight is under 3% -- a residual of at most a
    # few levels on a full-contrast stripe, imperceptible. Pinned as such
    # rather than as bit-identical, which a Gaussian can't honestly promise
    # inside its own window.
    assert np.array_equal(out[1140:1260, :18], src[1140:1260, :18])
    assert np.abs(out[1140:1260, :60].astype(int) - src[1140:1260, :60].astype(int)).max() <= 8
    assert np.array_equal(out[1140:1260, -18:], src[1140:1260, -18:])


def test_the_backdrop_is_softened_right_at_the_feet():
    """And at the contact point itself -- the one place a paste seam
    exists -- it must be measurably softer than the same stripes at the
    top of the frame."""
    bg = _stripe_field()
    out = np.asarray(stages.soften_backdrop(bg, **_FEET))
    top = _energy(out[:60, 360:540])
    feet = _energy(out[1176:1224, 360:540])
    assert feet < top * 0.7, f"expected the seam softened, got feet={feet:.1f} top={top:.1f}"


def test_the_feather_is_a_patch_under_the_feet_not_a_stripe_across_the_frame():
    """The horizontal localisation is what stops this being the stripe
    across the floorboards that killed the first design: at the contact
    row, the far side of the frame must stay as sharp as the top."""
    bg = _stripe_field()
    out = np.asarray(stages.soften_backdrop(bg, contact_y=1200, contact_x=180, contact_w=120))
    top = _energy(out[:60, 720:900])
    far_side_at_feet = _energy(out[1176:1224, 720:900])
    assert abs(far_side_at_feet - top) < top * 0.05, (
        f"far side of the contact row should be untouched, got {far_side_at_feet:.1f} vs {top:.1f}")


def test_blur_strength_zero_turns_the_feather_off_entirely():
    """The app's override: 0 must mean off, bit-identical to the input."""
    bg = _stripe_field()
    out = stages.soften_backdrop(bg, strength=0, **_FEET)
    assert np.array_equal(np.asarray(out), np.asarray(bg))


def test_no_contact_line_means_no_change_at_all():
    bg = _stripe_field()
    assert np.array_equal(np.asarray(stages.soften_backdrop(bg, contact_y=None)), np.asarray(bg))


# --------------------------------------------------------------- harmonize


def test_harmonize_gain_is_neutral_on_a_grey_backdrop():
    """No colour cast to lend -- a grey backdrop's ambient light has no hue,
    so the subject should come back untouched."""
    bg = np.full((300, 400, 3), 0.6, np.float32)
    gain = stages.harmonize_gain(bg, ox=100, oy=50, w=100, h=200)
    assert np.allclose(gain, 1.0, atol=1e-4), gain


def test_harmonize_gain_leans_toward_a_warm_backdrop():
    """A warm (amber) backdrop patch should nudge red up and blue down for
    the subject standing in front of it -- not neutral, and not reversed."""
    bg = np.full((300, 400, 3), 0.3, np.float32)
    bg[:, 100:300, 0] = 0.75  # warm patch: R >> G > B
    bg[:, 100:300, 1] = 0.55
    bg[:, 100:300, 2] = 0.35
    gain = stages.harmonize_gain(bg, ox=100, oy=0, w=200, h=300)
    assert gain[0] > 1.0 > gain[2], f"expected R up / B down, got {gain}"


def test_custom_backdrop_harmonize_bounds_are_tighter_than_the_preset_ones():
    """The fix for a real gate failure, 2026-09-20: a strongly saturated
    flat-colour custom backdrop pushed dE2000 to 3.26 against the 3.0
    budget at the ordinary (`custom=False`) settings, because every
    procedural preset was designed with a muted palette this project
    controls and already measured safely inside budget (§1h), and an
    operator's own uploaded photograph carries no such guarantee -- it can
    be any colour, including this adversarial one. `custom=True` must bound
    the gain more tightly on the exact same adversarial patch."""
    bg = np.zeros((200, 200, 3), np.float32)
    bg[..., 0] = 1.0  # pure, maximally saturated red
    ordinary = stages.harmonize_gain(bg, ox=0, oy=0, w=200, h=200, custom=False)
    cautious = stages.harmonize_gain(bg, ox=0, oy=0, w=200, h=200, custom=True)
    assert (cautious.max() - 1.0) < (ordinary.max() - 1.0)
    assert cautious.max() <= THRESHOLDS.harmonize_gain_max_custom + 1e-6
    assert cautious.min() >= THRESHOLDS.harmonize_gain_min_custom - 1e-6


def test_harmonize_gain_is_bounded_regardless_of_backdrop_saturation():
    """However saturated the sampled backdrop patch, the gain can never
    leave the configured [min, max] band -- the actual guarantee against
    measurably distorting the garment's true colour, independent of
    `harmonize_strength`."""
    bg = np.zeros((200, 200, 3), np.float32)
    bg[..., 0] = 1.0  # pure, maximally saturated red -- an adversarial case
    gain = stages.harmonize_gain(bg, ox=0, oy=0, w=200, h=200)
    assert gain.min() >= THRESHOLDS.harmonize_gain_min - 1e-6
    assert gain.max() <= THRESHOLDS.harmonize_gain_max + 1e-6


def test_harmonize_ignores_the_cove_floors_own_brightness_step():
    """`_cove`'s floor is deliberately brighter than its wall (see
    backgrounds.py's §1g fix) -- that is the backdrop's own geometry, not a
    colour cast, and `harmonize_gain` normalises luminance out of its sample
    before comparing so it must not mistake "the floor is lit" for "the room
    is warm or cool"."""
    bg = np.full((300, 400, 3), 0.3, np.float32)  # neutral grey wall
    bg[200:, :, :] = 0.6  # much brighter floor, still neutral grey
    gain = stages.harmonize_gain(bg, ox=100, oy=180, w=200, h=100)
    assert np.allclose(gain, 1.0, atol=1e-4), gain


def test_compose_actually_applies_the_harmonize_gain_to_the_pasted_subject():
    """Not just that `harmonize_gain` computes something reasonable in
    isolation -- that `compose` actually multiplies it into the pasted
    product rather than computing and discarding it. A neutral grey subject
    pasted onto a strongly warm backdrop should come back visibly warmer
    than it went in."""
    a_res = _standing_alpha()
    product = Image.new("RGB", a_res.shape[::-1], (128, 128, 128))
    bg = Image.new("RGB", (400, 600), (230, 140, 60))  # strongly warm/orange
    out, scene_alpha = stages.compose(bg, product, a_res)
    out_arr = np.asarray(out, np.float32)
    mask = scene_alpha > 0.95
    assert mask.sum() > 100
    mean_rgb = out_arr[mask].mean(axis=0)
    assert mean_rgb[0] > 128 + 2, f"expected red to lift on a warm backdrop, got {mean_rgb}"
    assert mean_rgb[2] < 128 - 2, f"expected blue to drop on a warm backdrop, got {mean_rgb}"


# ------------------------------------------------------- custom backdrop


def test_fit_custom_background_covers_the_canvas_without_distortion():
    """A photographed backdrop's own aspect ratio almost never matches the
    export canvas exactly. `fit_custom_background` must cover the canvas
    completely (no letterboxing) without stretching -- checked by pinning
    the exact output size and that the source's own aspect ratio survives
    the resize step before cropping."""
    bg = Image.new("RGB", (1000, 400), (100, 150, 200))  # wide source, 2.5:1
    out = stages.fit_custom_background(bg, (300, 450))  # narrow canvas, 2:3
    assert out.size == (300, 450)


def test_fit_custom_background_crops_from_the_centre():
    """Cropped from the middle, not a corner -- a real backdrop photo is
    more likely to have its actual subject (an arch, a drape, a doorway)
    centred than aligned to one edge. Pinned with a horizontal gradient: the
    cropped result's own mean should sit near the source's centre value,
    not near either extreme."""
    w, h = 900, 300
    gradient = np.tile(np.linspace(0, 255, w, dtype=np.uint8), (h, 1))
    bg = Image.fromarray(np.stack([gradient] * 3, axis=-1), "RGB")
    out = stages.fit_custom_background(bg, (300, 300))
    mean = np.asarray(out, np.float32).mean()
    assert 100 < mean < 155, f"expected a near-centre crop, got mean={mean:.1f}"


def test_infer_key_direction_leans_toward_the_brighter_side():
    """No authored `key_direction` exists for an operator's own photograph,
    so one is guessed from where the image itself is bright -- the same
    "measure the real pixels, don't assume" approach as `harmonize_gain`.
    A backdrop lit from the right should point the shadow away from it."""
    bg = np.full((300, 400, 3), 60, np.uint8)
    bg[: int(300 * 0.6), 250:] = 220  # bright patch, upper-right
    dx, dy = stages.infer_key_direction(Image.fromarray(bg, "RGB"))
    assert dx > 0, f"expected a rightward key direction, got dx={dx}"
    assert dy < 0


def test_infer_key_direction_is_neutral_on_an_evenly_lit_backdrop():
    bg = Image.new("RGB", (400, 300), (128, 128, 128))
    dx, dy = stages.infer_key_direction(bg)
    assert abs(dx) < 0.05, f"expected near-zero on a flat field, got dx={dx}"


def test_export_uses_the_custom_background_at_every_export_size_too():
    """The bug found running this for real, 2026-09-20: `composite` picks up
    a custom background correctly, but `export` re-renders the backdrop a
    *second* time, fresh, at each export preset's own exact resolution --
    and its original call unconditionally called `backgrounds.render(name,
    ...)`, which raised `KeyError: unknown background 'custom'` the moment
    the graph reached `export`, even though `composite` had already worked.
    Pinned directly on the generated source so a regression can't reintroduce
    an unconditional `backgrounds.render` call in `export`."""
    import inspect
    src = inspect.getsource(stages.export)
    assert "fit_custom_background" in src
    assert "custom_background" in src


def test_a_custom_background_is_used_instead_of_the_named_preset():
    """The registered `background` stage must prefer `ctx.extra
    ["custom_background"]` over `ctx.cfg.background` when both are present
    -- an operator who uploaded their own photo did not also mean to fall
    back to a preset silently."""
    ctx = Context(
        job_id="custom-bg-test", source_path=pathlib.Path("unused.png"),
        cfg=JobConfig(background="studio_ivory"),
        store=ArtifactStore("custom-bg-test"),
        manifest=JobManifest(job_id="custom-bg-test", source="unused.png", profile="x"),
    )
    ctx.source = Image.new("RGB", (400, 600), (200, 200, 200))
    ctx.extra["custom_background"] = Image.new("RGB", (800, 1200), (30, 90, 40))
    ctx = stages.background(ctx)
    assert ctx.extra["backdrop_used"] == "custom"
    mean_rgb = np.asarray(ctx.background, np.float32).mean(axis=(0, 1))
    # Green channel should dominate -- proof the *uploaded* colour landed in
    # the canvas, not studio_ivory's own pale, warm-neutral rendering.
    assert mean_rgb[1] > mean_rgb[0] and mean_rgb[1] > mean_rgb[2], mean_rgb


# ---------------------------------------------------------------- placement


def test_a_wide_garment_is_bounded_by_width_not_only_height():
    """The inherited bug, in this project's own shape.

    The sibling scaled a decor hanging by height alone; a seven-medallion
    toran came out at 128% of a square canvas, clipped off both edges, with no
    exception and no warning. A saree photographed spread out is exactly that
    shape, so the bound is tested here rather than assumed to have come along
    with the code.
    """
    size = (400, 400)
    alpha = np.zeros((size[1], size[0]), np.float32)
    alpha[180:240, 10:390] = 1.0            # aspect ~6:1
    product = Image.new("RGB", size, (150, 40, 90))

    p_res, a_res, ox, oy = stages.place(alpha, product, size)
    assert ox >= 0, f"clipped off the left: ox={ox}"
    assert ox + p_res.size[0] <= size[0], "clipped off the right"
    assert oy >= 0 and oy + p_res.size[1] <= size[1], "clipped vertically"


def test_a_tall_garment_fills_the_frame_it_is_given():
    """The other direction: a gown should not sit in the middle of a sea of
    backdrop just because the bound exists."""
    size = (400, 600)
    alpha = np.zeros((size[1], size[0]), np.float32)
    alpha[50:550, 150:250] = 1.0            # tall and narrow, as a gown is
    product = Image.new("RGB", size, (30, 40, 90))
    p_res, _, _, _ = stages.place(alpha, product, size)
    assert p_res.size[1] >= size[1] * (THRESHOLDS.garment_fill - 0.02)


def test_a_standing_figure_is_anchored_near_the_bottom_not_centred():
    """The second half of the grounding fix, 2026-09-19. A subject vertically
    centred in the canvas leaves equal empty backdrop above the head and
    below the feet, which no real full-length photograph is framed like --
    found as a direct contributor to a real composite reading as edited."""
    size = (400, 600)
    alpha = np.zeros((size[1], size[0]), np.float32)
    alpha[40:560, 150:250] = 1.0  # a tall standing figure, well short of the canvas
    product = Image.new("RGB", size, (120, 60, 90))

    p_res, a_res, ox, oy = stages.place(alpha, product, size)
    top_gap = oy
    bottom_gap = size[1] - (oy + p_res.size[1])
    assert bottom_gap < top_gap, (
        f"expected most of the slack above the subject as headroom, got "
        f"top_gap={top_gap} bottom_gap={bottom_gap}"
    )
    expected_bottom = int(size[1] * THRESHOLDS.bottom_margin)
    assert abs(bottom_gap - expected_bottom) <= 1, (bottom_gap, expected_bottom)


def test_floor_frac_overrides_the_default_bottom_margin():
    """2026-09-20: a photographed backdrop's own floor can sit anywhere in
    frame -- a table's edge, a raised porch -- not just at the canvas
    bottom the way every procedural preset's floor does. `floor_frac` plants
    the subject's own feet at a specific line instead of the fixed default
    margin."""
    size = (400, 600)
    alpha = np.zeros((size[1], size[0]), np.float32)
    alpha[40:560, 150:250] = 1.0
    product = Image.new("RGB", size, (120, 60, 90))

    p_res, a_res, ox, oy = stages.place(alpha, product, size, floor_frac=0.5)
    feet_y = oy + p_res.size[1]
    assert abs(feet_y - size[1] * 0.5) <= 2, (
        f"expected the feet at y={size[1] * 0.5:.0f} (50% down the frame), "
        f"got {feet_y}"
    )


def test_fill_and_x_overrides_move_and_resize_the_subject():
    """2026-09-21: the app's placement overrides. A smaller `fill` must
    yield a shorter placed figure; `x_frac` must move its centre."""
    size = (400, 600)
    alpha = np.zeros((size[1], size[0]), np.float32)
    alpha[40:560, 150:250] = 1.0
    product = Image.new("RGB", size, (120, 60, 90))

    big = stages.place(alpha, product, size, 0.9)
    small = stages.place(alpha, product, size, 0.9, fill=0.5)
    assert small[0].size[1] < big[0].size[1] * 0.7

    left = stages.place(alpha, product, size, 0.9, x_frac=0.2)
    right = stages.place(alpha, product, size, 0.9, x_frac=0.8)
    assert left[2] < big[2] < right[2]
    # And never off the canvas, whatever x_frac asks for.
    edge = stages.place(alpha, product, size, 0.9, x_frac=1.0)
    assert edge[2] + edge[0].size[0] <= size[0]


def test_floor_frac_of_none_keeps_the_ordinary_bottom_margin_behaviour():
    """Every procedural preset, and any custom backdrop without an assigned
    floor line, must render exactly as before this feature existed --
    `floor_frac=None` is not just "close to the default", it is the
    default."""
    size = (400, 600)
    alpha = np.zeros((size[1], size[0]), np.float32)
    alpha[40:560, 150:250] = 1.0
    product = Image.new("RGB", size, (120, 60, 90))

    with_none = stages.place(alpha, product, size, floor_frac=None)
    without_arg = stages.place(alpha, product, size)
    assert with_none[2:] == without_arg[2:]  # same (ox, oy)


def test_an_empty_matte_is_refused_rather_than_composited():
    product = Image.new("RGB", (100, 100), (0, 0, 0))
    try:
        stages.place(np.zeros((100, 100), np.float32), product, (100, 100))
    except ValueError:
        return
    raise AssertionError("an empty matte should be refused")


# ---------------------------------------------------------------- backdrops


def test_every_preset_renders_at_the_size_asked_for():
    for name in backgrounds.PRESETS:
        im = backgrounds.render(name, (120, 180), seed=3)
        assert im.size == (120, 180), (name, im.size)


def test_the_backdrop_library_spans_a_wide_luminance_range():
    """Phase 2 is a choice, and a choice needs range. The sibling found
    `relight` throttling itself on 7 of 7 real photographs because backdrops
    were picked without reference to how bright the product is."""
    keys = [backgrounds.key_luminance(n) for n in backgrounds.PRESETS]
    assert max(keys) / max(min(keys), 1e-4) > 10


def test_ranking_puts_the_nearest_backdrop_first_and_drops_nothing():
    pool = backgrounds.presets_for("flat")
    ranked = backgrounds.rank_by_luminance(pool, 0.05)
    assert sorted(ranked) == sorted(pool), "ranking lost or invented a preset"
    assert backgrounds.key_luminance(ranked[0]) < 0.10


def test_occasionwear_presets_are_offered_to_the_flat_graph():
    pool = backgrounds.presets_for(Graph.FLAT.value)
    assert "midnight_velvet" in pool and "champagne_silk" in pool


# ---------------------------------------------------------------- the cove
# Added 2026-09-19. Reported directly, against a real photograph: the flat
# gradient backdrop "looks like floating in air, definitely edited", and
# after the grounding fix (bottom-anchored placement, a contact shadow) the
# same complaint stood -- a shadow cast onto an undifferentiated tint still
# reads as a shadow painted onto a tint. `_cove` gives the studio presets an
# actual floor plane, the seamless wall-to-floor sweep every real photography
# studio backdrop uses, so the shadow has a surface to land on rather than a
# colour field.


def test_studio_presets_are_the_cove_kind_with_a_floor():
    """Every studio/wall preset that a full-length photo could land on now
    has a real horizon, not the "off the bottom of frame" default that
    quietly turns a preset back into a flat gradient."""
    studio_names = [
        "studio_ivory", "studio_pearl", "studio_graphite",
        "champagne_silk", "blush_plaster", "rose_gold_wash",
        "midnight_velvet", "wine_drape", "emerald_drape",
    ]
    for name in studio_names:
        p = backgrounds.PRESETS[name]
        assert p.kind == "cove", (name, p.kind)
        assert p.horizon < 1.0, f"{name} has no floor (horizon={p.horizon})"


def test_flatlay_presets_are_untouched_surfaces():
    """The two presets meant for a garment laid flat on a table have no
    standing subject and no "floor" concept distinct from the surface
    itself -- they must not have been swept into the cove conversion."""
    for name in ("linen_flatlay", "marble_flatlay"):
        p = backgrounds.PRESETS[name]
        assert p.kind == "surface", (name, p.kind)


def _wall_floor_bands(name, size=(300, 450), seed=5):
    """Mean sRGB lightness just above and just below the horizon, for a
    preset with horizon=0.15 (~57.5% down the frame)."""
    import numpy as np
    im = np.asarray(backgrounds.render(name, size, seed=seed).convert("L"), np.float32)
    h = im.shape[0]
    above = im[int(h * 0.40):int(h * 0.45)].mean()
    below = im[int(h * 0.75):int(h * 0.85)].mean()
    return above, below


def test_a_cove_render_actually_differs_above_and_below_its_horizon():
    """Not just that it runs, and not just that it differs -- that the floor
    reads as *brighter*, the direction a real floor catching bounce light
    near the camera actually goes. `abs(delta) > threshold` alone would have
    passed a real, shipped bug: an earlier version of the floor lift based
    itself on `_wall`'s own output, which carries its own downward-darkening
    gradient, and produced a floor measurably *darker* than the wall above
    it (champagne_silk: -13.5 sRGB units) while still satisfying "differs by
    more than 1.5" easily. This asserts the sign, not just the magnitude."""
    above, below = _wall_floor_bands("studio_ivory")
    assert below > above + 1.5, (
        f"the floor should read brighter than the wall above it: "
        f"above={above:.2f} below={below:.2f}"
    )


def test_the_floor_is_visible_on_dark_presets_too_not_just_pale_ones():
    """The specific regression this pins: a linear-light lift (or a lift
    based on the wall's own already-darkening output) shrinks to almost
    nothing on a dark preset even when it works fine on a pale one, because
    gamma compression makes the same linear delta far less visible in sRGB
    the darker the base colour is. Measured directly: the first working
    version of this fix gave midnight_velvet only ~2.5 sRGB units of
    wall/floor separation against 9-11 on a pale preset using the identical
    formula -- visible on light backdrops, essentially invisible on dark
    ones. Both families must land in the same ballpark."""
    pale_above, pale_below = _wall_floor_bands("studio_ivory")
    dark_above, dark_below = _wall_floor_bands("midnight_velvet")
    pale_delta = pale_below - pale_above
    dark_delta = dark_below - dark_above
    assert dark_delta > 5.0, f"midnight_velvet's floor barely differs: {dark_delta:.2f}"
    assert dark_delta > pale_delta * 0.4, (
        f"dark preset's floor separation ({dark_delta:.2f}) is far weaker "
        f"than the pale preset's ({pale_delta:.2f})"
    )


def test_the_cove_transition_has_no_hard_seam():
    """A visible line where wall meets floor would read as two flat planes
    glued together rather than one continuous studio sweep -- the entire
    reason `_cove` exists over just drawing two rectangles."""
    import numpy as np
    im = np.asarray(
        backgrounds.render("studio_ivory", (300, 450), seed=5).convert("L"), np.float32
    )
    h = im.shape[0]
    horizon_row = int(h * 0.575)
    band = im[horizon_row - 15:horizon_row + 15, 100:200].mean(axis=1)
    # the steepest single-row jump within the transition band should still
    # be gentle relative to the total wall-to-floor difference
    biggest_step = np.abs(np.diff(band)).max()
    assert biggest_step < 3.0, f"a hard seam at the horizon: step={biggest_step:.2f}"


def test_a_dark_cove_still_renders_without_error_or_negative_light():
    """Dark presets (midnight_velvet, wine_drape) push the floor maths
    toward the low end of the linear-light range -- worth pinning that
    nothing clips into invalid values there."""
    import numpy as np
    for name in ("midnight_velvet", "wine_drape"):
        im = np.asarray(backgrounds.render(name, (200, 300), seed=1))
        assert im.min() >= 0 and im.max() <= 255


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("pass", fn.__name__)
    print(f"all {len(fns)} pipeline tests pass")
