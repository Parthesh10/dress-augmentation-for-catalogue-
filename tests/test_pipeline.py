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
