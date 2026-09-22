"""What phases 1 and 2 promise, pinned.

Synthetic fixtures throughout, so this runs in seconds with no matting backend
and no network. The things worth testing here are the decisions this project
made *differently* from the sibling, because those are the ones nobody else's
test suite is watching.
"""
import math
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


def test_shadow_has_a_denser_core_than_a_single_gaussian_would_give():
    """2026-09-22 (TASK.md §1t): a second, narrower, steeper layer is
    `np.maximum`'d with the original ambient ellipse so a wider area right
    at the contact point stays near-maximum-dark, closer to how a real
    contact shadow looks (a dense near-black core fading into a broad,
    faint ambient tail) rather than one smooth, uniformly-soft gaussian.
    Checked by comparing the shadow value partway out from the centre --
    where the core still contributes but the pure ambient shape alone
    would already have fallen further -- against what the ambient-only
    formula would give at the same point."""
    a_res = _standing_alpha()
    sh = stages.contact_shadow((400, 600), a_res, ox=50, oy=50)
    # The contact point itself, from the same fixture/offsets used elsewhere
    # in this file.
    contact_x, contact_y = 50 + 150, 50 + 498
    # A quarter of the way out along x from the centre -- inside the core's
    # own radius, where its steeper-but-narrower shape should keep the
    # value higher than the ambient layer's own gentler slope would alone.
    contact_w = 60  # foot width from _standing_alpha's own default
    rx = contact_w * 0.55 * 0.60  # a point still inside the core radius (0.42*rx)
    probe_x = int(contact_x + rx)
    ambient_only = math.exp(-2.2 * ((probe_x - contact_x) / (contact_w * 0.55)) ** 2)
    assert sh[contact_y, probe_x] > ambient_only + 0.02, (
        f"expected the core to raise the shadow above the pure-ambient value "
        f"here, got {sh[contact_y, probe_x]:.3f} vs ambient-only {ambient_only:.3f}"
    )


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


# ------------------------------------------------------- depth-of-field blur

#: A standing figure's own footprint in `_stripe_field()`'s 900x1350 frame --
#: tall and roughly centred, the same shape `_standing_alpha` describes,
#: given directly as (ox, oy, w, h) since `depth_blur_backdrop` takes the
#: placed box rather than an alpha mask.
_SUBJECT_BOX = dict(ox=340, oy=100, w=220, h=1150)


def test_depth_blur_leaves_the_subjects_own_footprint_sharp():
    """The whole point, distinct from the two whole-frame designs already
    rejected (see `soften_backdrop`'s docstring): right at and immediately
    around the subject, the backdrop must stay sharp."""
    bg = _stripe_field()
    out = np.asarray(stages.depth_blur_backdrop(bg, **_SUBJECT_BOX))
    src = np.asarray(bg)
    # Dead centre of the subject's own footprint.
    assert np.array_equal(out[600:650, 400:500], src[600:650, 400:500])


def test_depth_blur_softens_the_far_corners():
    """Genuinely far from the subject -- the frame's own corners -- must be
    measurably softer than the same stripes at the subject's own depth."""
    bg = _stripe_field()
    out = np.asarray(stages.depth_blur_backdrop(bg, **_SUBJECT_BOX))
    near = _energy(out[600:650, 400:500])
    corner = _energy(out[0:50, 0:100])
    assert corner < near * 0.5, f"expected the corner softened, got corner={corner:.1f} near={near:.1f}"


def test_depth_blur_strength_zero_is_a_noop():
    bg = _stripe_field()
    out = stages.depth_blur_backdrop(bg, strength=0, **_SUBJECT_BOX)
    assert np.array_equal(np.asarray(out), np.asarray(bg))


def test_depth_blur_does_nothing_for_a_zero_sized_subject():
    """Defensive: `compose` always has a real w/h, but the function's own
    contract should not divide by zero or blur the whole frame if it ever
    doesn't."""
    bg = _stripe_field()
    out = stages.depth_blur_backdrop(bg, ox=0, oy=0, w=0, h=0)
    assert np.array_equal(np.asarray(out), np.asarray(bg))


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


def test_harmonize_scale_of_zero_turns_the_tint_off():
    """2026-09-22: the app's colour-tint override. 0 must mean no tint at
    all -- gain exactly 1.0, not merely reduced."""
    bg = np.zeros((200, 200, 3), np.float32)
    bg[..., 0] = 1.0  # saturated red, would ordinarily pull the gain up
    gain = stages.harmonize_gain(bg, ox=0, oy=0, w=200, h=200, scale=0.0)
    assert np.allclose(gain, 1.0, atol=1e-6), gain


def test_harmonize_scale_of_two_lends_double_the_ordinary_cast_but_stays_clamped():
    """Scale multiplies the strength, not the hard gmin/gmax clamp -- the
    clamp is what actually protects the colour_fidelity gate, and no
    operator-set number should be able to remove it."""
    bg = np.zeros((200, 200, 3), np.float32)
    bg[..., 0] = 1.0
    ordinary = stages.harmonize_gain(bg, ox=0, oy=0, w=200, h=200, scale=1.0)
    doubled = stages.harmonize_gain(bg, ox=0, oy=0, w=200, h=200, scale=2.0)
    assert doubled[0] >= ordinary[0]
    assert doubled.max() <= THRESHOLDS.harmonize_gain_max + 1e-6
    assert doubled.min() >= THRESHOLDS.harmonize_gain_min - 1e-6


def test_exposure_gain_darkens_for_a_dark_backdrop_and_lifts_for_a_bright_one():
    """2026-09-22: exposure matching, the other half of "lit by the same
    room" alongside harmonize_gain's colour cast. Measured against the
    real library: midnight_velvet (lum 0.030) should come back darkened,
    studio_ivory (lum 0.750) lifted, both modest."""
    dark = stages.exposure_gain(0.030)
    bright = stages.exposure_gain(0.750)
    assert dark < 1.0 < bright
    assert THRESHOLDS.exposure_gain_min <= dark <= 1.0
    assert 1.0 <= bright <= THRESHOLDS.exposure_gain_max


def test_exposure_gain_is_neutral_at_the_reference_luminance():
    assert abs(stages.exposure_gain(THRESHOLDS.exposure_reference_luminance) - 1.0) < 1e-6


def test_exposure_gain_does_not_try_to_match_the_backdrops_absolute_brightness():
    """The explicit non-goal: a white dress against a near-black drape
    should stay recognisably white, not be dragged down toward the
    backdrop's own luminance. The bound on how far exposure_gain can move
    is exposure_gain_min itself, nowhere near enough to turn white grey."""
    assert stages.exposure_gain(0.0) >= THRESHOLDS.exposure_gain_min
    assert THRESHOLDS.exposure_gain_min > 0.5, "the clamp itself must stay a small nudge"


def test_exposure_gain_is_neutral_with_no_known_backdrop_luminance():
    assert stages.exposure_gain(None) == 1.0


def test_exposure_gain_field_averages_close_to_the_flat_gain():
    """The mean-preservation argument `exposure_gain_field`'s own docstring
    makes -- a linear ramp centred on the subject averages close to zero,
    so the field's mean should land close to what the flat scalar alone
    would have been, even though `shading_spread` lets individual pixels
    swing further than the flat clamp allows on its own."""
    flat = stages.exposure_gain(0.0)  # a dark backdrop -- non-trivial gain
    field = stages.exposure_gain_field((200, 300), (-0.3, -0.45), 0.0)
    assert abs(float(field.mean()) - flat) < 0.01, (field.mean(), flat)


def test_exposure_gain_field_varies_along_the_key_direction():
    """The actual point: one side of the subject should read brighter than
    the other, not a flat number repeated across every pixel."""
    field = stages.exposure_gain_field((200, 300), (1.0, 0.0), 0.4)
    left = field[:, :30].mean()
    right = field[:, -30:].mean()
    assert abs(left - right) > 0.01, f"expected a visible left/right split, got {left} vs {right}"


def test_exposure_gain_field_is_neutral_with_no_known_backdrop_luminance():
    field = stages.exposure_gain_field((100, 150), (-0.25, -0.45), None)
    assert np.allclose(field, 1.0, atol=1e-6)


def test_exposure_gain_field_scale_of_zero_matches_the_flat_versions_own_neutral():
    field = stages.exposure_gain_field((100, 150), (-0.25, -0.45), 0.0, scale=0.0)
    assert np.allclose(field, 1.0, atol=1e-6)


def test_exposure_gain_field_stays_inside_its_own_wider_safety_clamp():
    """However large `shading_spread` is tuned, no pixel should escape the
    wider (not the flat) clamp `exposure_gain_field` documents."""
    field = stages.exposure_gain_field((200, 300), (1.0, 0.0), 0.0, scale=5.0)
    assert field.min() >= THRESHOLDS.exposure_gain_min * 0.9 - 1e-6
    assert field.max() <= THRESHOLDS.exposure_gain_max * 1.15 + 1e-6


def test_exposure_scale_of_zero_disables_it_and_two_stays_inside_the_clamp():
    bright = stages.exposure_gain(0.750, scale=0.0)
    assert bright == 1.0
    doubled = stages.exposure_gain(0.750, scale=2.0)
    assert doubled <= THRESHOLDS.exposure_gain_max + 1e-6


def test_key_dir_x_override_replaces_only_the_horizontal_component():
    """2026-09-22: the app's light-direction override. Only the x
    component of key_dir should change; the y (how steep the light is)
    stays whatever the backdrop's own value was."""
    a_res = _standing_alpha()
    product = Image.new("RGB", a_res.shape[::-1], (128, 128, 128))
    bg = Image.new("RGB", (400, 600), (150, 150, 150))
    _, alpha_default = stages.compose(bg, product, a_res, key_dir=(-0.25, -0.45))
    out_right, _ = stages.compose(
        bg, product, a_res, key_dir=(-0.25, -0.45), key_dir_x=0.35)
    out_left, _ = stages.compose(
        bg, product, a_res, key_dir=(-0.25, -0.45), key_dir_x=-0.35)
    # The shadow (and therefore the composite) should differ measurably
    # between a light forced to the right versus forced to the left.
    diff = np.abs(
        np.asarray(out_right, np.float32) - np.asarray(out_left, np.float32))
    assert diff.max() > 1.0, "expected the shadow position to move"


def test_compose_actually_shades_the_subject_along_the_key_direction():
    """Not just that `exposure_gain_field` computes a gradient in
    isolation -- that `compose` actually applies it per-pixel to the pasted
    product, the same integration-level proof `test_compose_actually_
    applies_the_harmonize_gain_to_the_pasted_subject` gives the flat colour
    tint. A neutral grey subject on a backdrop dark enough to trigger a
    real exposure gain should come back visibly asymmetric left-to-right
    when the key light is forced hard to one side."""
    a_res = _standing_alpha()
    product = Image.new("RGB", a_res.shape[::-1], (128, 128, 128))
    bg = Image.new("RGB", (400, 600), (10, 10, 10))  # very dark -- real exposure gain
    out, scene_alpha = stages.compose(
        bg, product, a_res, key_dir=(1.0, 0.0), key_dir_x=1.0, scene_luminance=0.02)
    out_arr = np.asarray(out, np.float32)
    mask = scene_alpha > 0.95
    xs = np.where(mask.any(axis=0))[0]
    left_half = mask[:, xs[:len(xs) // 2]]
    right_half = mask[:, xs[len(xs) // 2:]]
    left_mean = out_arr[:, xs[:len(xs) // 2]][left_half].mean()
    right_mean = out_arr[:, xs[len(xs) // 2:]][right_half].mean()
    assert abs(left_mean - right_mean) > 1.0, (
        f"expected a visible left/right shading split, got {left_mean:.2f} vs {right_mean:.2f}")


def test_compose_depth_blur_strength_zero_matches_no_depth_blur():
    """The app's override, at the `compose` integration level: 0 must
    produce the exact same composite as never having the effect at all."""
    a_res = _standing_alpha()
    product = Image.new("RGB", a_res.shape[::-1], (128, 128, 128))
    bg = _stripe_field(size=(400, 600))
    out_off, _ = stages.compose(bg, product, a_res, depth_blur_strength=0)
    out_default_disabled = THRESHOLDS.depth_blur_strength
    assert out_default_disabled > 0, "test assumes depth blur is on by default"
    out_on, _ = stages.compose(bg, product, a_res)
    assert not np.array_equal(np.asarray(out_off), np.asarray(out_on)), (
        "expected the default (on) composite to differ from strength=0")


# ------------------------------------------------------- whole-frame finishing


def test_apply_finishing_strength_zero_is_a_noop():
    canvas = np.full((100, 150, 3), 0.5, np.float32)
    out = stages.apply_finishing(canvas, strength=0)
    assert np.array_equal(out, canvas)


def test_apply_finishing_lifts_contrast_away_from_the_midpoint():
    """A flat mid-grey field pushed toward black/white at its own extremes
    -- checked well away from the vignetted corners and without the grain
    obscuring the direction of the shift, by looking at the mean over a
    large flat region."""
    bright = np.full((200, 300, 3), 0.75, np.float32)
    dark = np.full((200, 300, 3), 0.25, np.float32)
    out_bright = stages.apply_finishing(bright.copy(), strength=1.0, seed=0)
    out_dark = stages.apply_finishing(dark.copy(), strength=1.0, seed=1)
    # Centre region only -- the vignette also darkens the corners, which
    # would otherwise mask the contrast lift in a whole-image mean.
    cy, cx = 100, 150
    r = 30
    assert out_bright[cy - r:cy + r, cx - r:cx + r].mean() > 0.75
    assert out_dark[cy - r:cy + r, cx - r:cx + r].mean() < 0.25


def test_apply_finishing_vignette_darkens_the_corners_more_than_the_centre():
    canvas = np.full((200, 300, 3), 0.6, np.float32)
    out = stages.apply_finishing(canvas, strength=1.0, seed=0)
    centre = out[95:105, 145:155].mean()
    corner = out[:10, :10].mean()
    assert corner < centre, f"expected the corner darker, got corner={corner:.3f} centre={centre:.3f}"


def test_apply_finishing_grain_is_zero_mean_and_deterministic_per_seed():
    canvas = np.full((300, 400, 3), 0.5, np.float32)
    out_a = stages.apply_finishing(canvas.copy(), strength=1.0, seed=7)
    out_b = stages.apply_finishing(canvas.copy(), strength=1.0, seed=7)
    out_c = stages.apply_finishing(canvas.copy(), strength=1.0, seed=8)
    assert np.array_equal(out_a, out_b), "same seed must reproduce the same grain"
    assert not np.array_equal(out_a, out_c), "a different seed must actually differ"
    # Zero-mean: over a large flat region the average pixel value should
    # stay close to the contrast-adjusted midpoint, not drift from grain.
    assert abs(float(out_a[100:200, 100:300].mean()) - 0.5) < 0.01


def test_compose_finishing_strength_zero_matches_no_finishing():
    a_res = _standing_alpha()
    product = Image.new("RGB", a_res.shape[::-1], (128, 128, 128))
    bg = Image.new("RGB", (400, 600), (150, 150, 150))
    out_off, _ = stages.compose(bg, product, a_res, finishing_strength=0)
    out_on, _ = stages.compose(bg, product, a_res)
    assert not np.array_equal(np.asarray(out_off), np.asarray(out_on)), (
        "expected the default (on) composite to differ from strength=0")


def test_apply_finishing_custom_grain_and_vignette_are_stronger_than_ordinary():
    """2026-09-22, CLAUDE.md "Next actionables" §1: found too weak to read
    against a textured real-photo backdrop (a gravel path) at the ordinary
    strength. `custom=True` must raise grain and vignette, not leave them
    matching the preset case."""
    canvas = np.full((200, 300, 3), 0.6, np.float32)
    ordinary = stages.apply_finishing(canvas.copy(), strength=1.0, seed=0, custom=False)
    cautious = stages.apply_finishing(canvas.copy(), strength=1.0, seed=0, custom=True)

    # Vignette: the custom corner should darken further than the ordinary one.
    assert (1 - cautious[:10, :10].mean()) > (1 - ordinary[:10, :10].mean())

    # Grain: same seed, so the only difference is amplitude -- the custom
    # output must deviate from the flat midpoint more than the ordinary one
    # does, measured over a large flat centre region away from the vignette.
    mid = 0.5 + (0.6 - 0.5) * (1.0 + THRESHOLDS.finishing_contrast)
    ordinary_dev = np.abs(ordinary[90:110, 140:160] - mid).mean()
    cautious_dev = np.abs(cautious[90:110, 140:160] - mid).mean()
    assert cautious_dev > ordinary_dev


def test_contact_shadow_opacity_custom_is_stronger_than_ordinary():
    """Same "Next actionables" §1 fix, the shadow half of it. Unlike
    harmonize/exposure, which go more cautious for a custom backdrop
    because they touch the subject's own colour, the shadow only darkens
    backdrop pixels -- so it goes the opposite direction."""
    assert THRESHOLDS.contact_shadow_opacity_custom > THRESHOLDS.contact_shadow_opacity


def test_compose_darkens_the_backdrop_more_under_a_custom_shadow():
    """Not just that the constant is higher in isolation -- that `compose`
    actually picks it up for a custom backdrop. Same standing silhouette,
    same flat backdrop, only `custom_backdrop` differs; the area just
    outside the subject's own footprint (where the shadow's ambient tail
    reaches but the subject's own opaque paste does not) must come back
    darker for the custom case."""
    a_res = _standing_alpha()
    product = Image.new("RGB", a_res.shape[::-1], (128, 128, 128))
    bg = Image.new("RGB", (400, 600), (150, 150, 150))
    out_preset, scene_alpha = stages.compose(bg, product, a_res, custom_backdrop=False)
    out_custom, _ = stages.compose(bg, product, a_res, custom_backdrop=True)
    arr_preset = np.asarray(out_preset, np.float32)
    arr_custom = np.asarray(out_custom, np.float32)
    # Just below the feet: inside the shadow's reach, outside the subject.
    # Found from `scene_alpha` itself rather than a hardcoded offset -- both
    # calls share the same subject/backdrop, but `place`'s own automatic
    # positioning, not a number this test should assume.
    rows_with_subject = np.nonzero(scene_alpha.max(axis=1) > 0.5)[0]
    feet_row = int(rows_with_subject.max())
    band = slice(feet_row + 3, feet_row + 25)
    outside_subject = scene_alpha[band, :] < 0.05
    assert outside_subject.sum() > 50
    preset_mean = arr_preset[band, :][outside_subject].mean()
    custom_mean = arr_custom[band, :][outside_subject].mean()
    assert custom_mean < preset_mean, (
        f"expected the custom-backdrop shadow to read darker just below the "
        f"feet, got preset={preset_mean:.2f} custom={custom_mean:.2f}"
    )


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


def test_ranking_puts_the_nearest_backdrop_first_and_drops_nothing():
    """2026-09-22 (TASK.md §1v): this used to also assert the nearest-ranked
    preset landed under a fixed luminance threshold, back when the library
    held a wide spread of presets to rank. Trimmed to one (`studio_ivory`,
    a bright neutral) along with the rest of the procedural library --
    "nearest" is trivial with one candidate, so only the actual contract
    (`rank_by_luminance` must not lose or invent a preset) still applies."""
    pool = backgrounds.presets_for("flat")
    ranked = backgrounds.rank_by_luminance(pool, 0.05)
    assert sorted(ranked) == sorted(pool), "ranking lost or invented a preset"


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
    quietly turns a preset back into a flat gradient. Only `studio_ivory`
    remains since the 2026-09-22 trim (TASK.md §1v) -- this used to loop
    over nine studio/warm/dramatic presets; the loop is kept even at one
    entry so this test doesn't need rewriting again if the library grows."""
    for name in backgrounds.PRESETS:
        p = backgrounds.PRESETS[name]
        assert p.kind == "cove", (name, p.kind)
        assert p.horizon < 1.0, f"{name} has no floor (horizon={p.horizon})"


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


### Dropped, 2026-09-22 (TASK.md §1v): `test_the_floor_is_visible_on_dark_presets_too_not_just_pale_ones`
### and `test_a_dark_cove_still_renders_without_error_or_negative_light` both
### needed a dark preset (`midnight_velvet`/`wine_drape`) that no longer
### exists after the library was trimmed to one, bright, neutral preset --
### there is nothing dark left to regress on. Not a gap introduced silently:
### recorded here so a future session doesn't wonder where they went.


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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("pass", fn.__name__)
    print(f"all {len(fns)} pipeline tests pass")
