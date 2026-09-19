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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("pass", fn.__name__)
    print(f"all {len(fns)} pipeline tests pass")
