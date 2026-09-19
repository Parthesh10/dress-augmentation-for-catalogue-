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
