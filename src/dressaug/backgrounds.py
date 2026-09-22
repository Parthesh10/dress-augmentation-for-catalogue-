"""Procedural backdrop library — phase 2, "putting relevant background".

**Engine inherited from the sibling jewellery project**
(`Image Augmentation`, `src/imgaug/backgrounds.py`): backdrops are generated
arithmetically rather than diffused, so they cost ~50 ms on any CPU, need no
weights, and are deterministic — the same preset gives the same backdrop every
time, which is what makes a catalogue look like a catalogue instead of like
thirty different rooms.

**Trimmed to a single preset, 2026-09-22 (TASK.md §1v)** -- this library
held up to 40 procedural presets across the occasionwear palette at one
point; asked for directly, it now keeps just one neutral white/ivory
option (`studio_ivory`). The real backdrop variety in the app now comes
from the operator's own photographed backdrops (`backdrop_library.py`),
not from this module. `PRESETS` having exactly one entry is deliberate,
not a stub -- see TASK.md §1v for the reasoning and what was removed.

All compositing arithmetic happens in linear light and is encoded to sRGB
once, at the end.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image

from .color import linear_to_srgb, srgb_to_linear


def _hex(c: str) -> np.ndarray:
    c = c.lstrip("#")
    return np.array([int(c[i : i + 2], 16) / 255 for i in (0, 2, 4)], dtype=np.float32)


def _grid(w: int, h: int) -> tuple[np.ndarray, np.ndarray]:
    """Normalised coordinates, aspect-corrected so circles stay circular."""
    ar = w / h
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    return (x / w - 0.5) * 2 * ar, (y / h - 0.5) * 2


def _grain(w: int, h: int, amount: float, seed: int) -> np.ndarray:
    """A little noise. Smooth 8-bit gradients band visibly on a phone screen;
    noise below the quantisation step dithers it away for free."""
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, amount, (h, w, 1)).astype(np.float32)


@dataclass(frozen=True)
class Preset:
    name: str
    kind: str          # "surface" | "wall" | "doorway" | "cove"
    base: str          # hex, the lit colour
    shade: str         # hex, the colour it falls off to
    #: Where the key light sits, in normalised coords.
    light: tuple[float, float] = (-0.25, -0.45)
    falloff: float = 1.35
    vignette: float = 0.22
    grain: float = 0.006
    #: Suits which graph, for the UI to filter sensibly.
    graphs: tuple[str, ...] = ("flat_lay",)
    #: `kind="cove"` only -- where the wall curves into the floor, in the
    #: same normalised [-1, 1] y-space `_grid` uses (0.15 is roughly 57%
    #: down the frame). 1.15 -- off the bottom edge entirely -- for every
    #: other kind, so nothing else has to know this field exists.
    horizon: float = 1.15
    #: Plaster/wall mottling amplitude, `_wall`'s own low-frequency noise
    #: layer. Was a hardcoded 0.030 until 2026-09-22; kept as that default
    #: so the original 11 presets render identically, exposed per-preset so
    #: a newer one can read as a rougher, more textured surface rather than
    #: a perfectly smooth gradient -- asked for directly ("not just plain
    #: colour mats").
    mottle: float = 0.030
    #: Soft vertical fold modulation -- a handful of irregular wide waves
    #: across the width, the way a hung drape or curtain actually looks
    #: rather than a flat-painted wall. 0 (the default, and every original
    #: preset) is off entirely. Deliberately small even where used --
    #: this library's whole aesthetic is muted and not meant to compete
    #: with the garment, so a "fabric drape" preset reads as gently
    #: textured cloth, not a stripe pattern.
    fold: float = 0.0


#: **Trimmed to one, 2026-09-22 (TASK.md §1v)** -- asked for directly: keep
#: a single Plain option, a white/neutral one, and drop the other 39 (the
#: "40 procedural presets" section above described the library this dict
#: held before this change; see TASK.md §1v for why and what was removed).
#: `studio_ivory` was already the app's own default (`ui.py`'s Backdrop
#: radio) and the nearest thing to a clean white in the set, so it's the one
#: kept rather than a fresh addition.
PRESETS: dict[str, Preset] = {
    "studio_ivory": Preset(
        "studio_ivory", "cove", "#F4EEE6", "#D6CDC0",
        light=(-0.20, -0.50), falloff=1.30, vignette=0.24, grain=0.005,
        graphs=("flat", "dummy"), horizon=0.15,
    ),
}


def presets_for(graph: str) -> list[str]:
    return [n for n, p in PRESETS.items() if graph in p.graphs]


# ---------------------------------------------------------------- generation


def _surface(p: Preset, w: int, h: int, seed: int) -> np.ndarray:
    """A lit plane seen face-on: radial falloff from the key, plus vignette."""
    x, y = _grid(w, h)
    d = np.hypot(x - p.light[0], y - p.light[1])
    t = np.clip(d / p.falloff, 0, 1)[..., None]
    # smoothstep, so the falloff has no visible edge where it reaches the shade
    t = t * t * (3 - 2 * t)

    base, shade = srgb_to_linear(_hex(p.base)), srgb_to_linear(_hex(p.shade))
    img = base * (1 - t) + shade * t

    r = np.hypot(x, y)[..., None]
    img *= 1 - p.vignette * np.clip(r / 1.9, 0, 1) ** 2
    return img


def _wall(p: Preset, w: int, h: int, seed: int) -> np.ndarray:
    """A wall: same falloff, but lit from above and with a broad vertical
    gradient, because walls are lit by rooms rather than by softboxes."""
    x, y = _grid(w, h)
    img = _surface(p, w, h, seed)
    img *= (1 - 0.16 * np.clip((y + 1) / 2, 0, 1))[..., None]

    # Plaster mottling: two octaves of smoothed noise. Amplitude is a
    # per-preset field since 2026-09-22 (`p.mottle`, default 0.030 --
    # exactly the old hardcoded value, so the original 11 presets are
    # bit-identical); a higher value reads as a rougher, more textured
    # surface instead of a perfectly smooth gradient.
    rng = np.random.default_rng(seed + 7)
    small = rng.normal(0, 1, (max(h // 24, 2), max(w // 24, 2))).astype(np.float32)
    mottle = np.asarray(
        Image.fromarray(small).resize((w, h), Image.BICUBIC), dtype=np.float32
    )
    img *= 1 + p.mottle * mottle[..., None]

    # Soft vertical folds, `p.fold` (default 0, off) -- a hung-drape
    # texture instead of a flat wall. Two irregular wide waves, offset by
    # the preset's own seed so neighbouring drape presets don't repeat the
    # same fold positions.
    if p.fold > 0:
        wave = (0.6 * np.sin(x * 2.3 + seed * 0.7)
                + 0.4 * np.sin(x * 5.1 - seed * 0.3 + 1.7))
        img *= (1 + p.fold * wave)[..., None]
    return img


def _doorway(p: Preset, w: int, h: int, seed: int) -> np.ndarray:
    """A doorway seen straight on: two jambs, a lintel, a darker opening.

    Deliberately soft-edged and low contrast. It reads as an architectural
    context at a glance without pretending to be a photograph of a real door,
    which a hard-edged rendering would — and would then lose to, badly.
    """
    img = _wall(p, w, h, seed)
    frame = srgb_to_linear(_hex(p.shade))
    x, y = _grid(w, h)
    ar = w / h

    jamb_x, lintel_y = 0.62 * ar, -0.34
    edge = 0.05 * ar

    def band(v, lo, hi, soft):
        return np.clip((v - lo) / soft, 0, 1) * np.clip((hi - v) / soft, 0, 1)

    inner = band(x, -jamb_x, jamb_x, edge) * np.clip((y - lintel_y) / 0.09, 0, 1)
    inner = inner[..., None]

    # The opening is darker than the wall, and cooler.
    opening = frame * 0.42
    img = img * (1 - 0.80 * inner) + opening * (0.80 * inner)

    # A soft ambient-occlusion line where frame meets wall.
    ao_x = np.exp(-(((np.abs(x) - jamb_x) / (edge * 1.6)) ** 2))
    ao_y = np.exp(-(((y - lintel_y) / 0.07) ** 2))
    ao = np.clip(ao_x + ao_y * (np.abs(x) < jamb_x), 0, 1)[..., None]
    img *= 1 - 0.22 * ao
    return img


def _cove(p: Preset, w: int, h: int, seed: int) -> np.ndarray:
    """A wall curving into a floor -- the seamless "cove" backdrop every real
    photography studio actually uses, one continuous sweep of paper or vinyl
    from the wall down onto the floor with no visible seam.

    Built specifically because the flat-gradient wall, however well lit, gave
    a full-length subject nothing to stand *on* -- reported plainly as
    "looks like floating in air, definitely edited" even after grounding
    (bottom-anchored placement, a contact shadow) was already in place. A
    shadow cast onto an undifferentiated tint still looks like a shadow
    painted onto a tint; the same shadow landing on an actual rendered floor
    plane reads as a shadow on a floor, which is the entire point of it.
    This does not replace `stages.contact_shadow` -- the two are meant to
    work together, and neither alone was the full fix.
    """
    x, y = _grid(w, h)
    wall = _wall(p, w, h, seed)

    # Depth: 0 at the horizon (far), 1 at the bottom edge (closest to
    # camera) -- brighter near the front is where a real floor catches the
    # most bounce light off the subject's own key. This depth cue, not
    # colour alone, is most of what makes it read as "floor" rather than
    # "more wall".
    depth = np.clip((y - p.horizon) / max(1.0 - p.horizon, 0.05), 0, 1)[..., None]

    # Lifted from `_surface`'s lighting, not from `wall`'s own output --
    # measured and found necessary. `_wall` carries its own downward
    # darkening gradient (real rooms get dimmer toward the floor as bounce
    # light falls off), and lifting *from* an already-darkening curve just
    # produces a floor that is merely "less dark" than the wall beside it
    # rather than visibly brighter -- the first version of this fix did
    # exactly that and measured a **negative** wall-to-floor delta on every
    # preset (champagne_silk: -13.5 sRGB units, the floor reading *darker*
    # than the wall above it). A photographed floor is a different, closer
    # surface catching different light, not the wall continuing to dim.
    #
    # The lift itself is computed in sRGB space rather than as a linear-light
    # ratio, and that distinction matters separately: a ratio-based lift
    # toward `base`/`shade` all but disappears into gamma compression on a
    # dark preset -- measured at ~2.5 sRGB units of wall/floor separation on
    # `midnight_velvet` against 9-11 on a pale preset using the identical
    # formula. A fixed sRGB lift keeps the floor visibly distinct regardless
    # of how dark the preset is.
    surface_srgb = np.clip(linear_to_srgb(np.clip(_surface(p, w, h, seed), 0, None)), 0, 1)
    lift = 0.08 + 0.10 * depth
    floor = srgb_to_linear(np.clip(surface_srgb + lift, 0, 1))

    # A soft sheen along the centre, the way a matte or lightly glossy
    # studio floor catches an overhead key -- not a mirror reflection, just
    # enough falloff across x that the floor does not read as flat paint.
    sheen = np.exp(-((x / 0.9) ** 2))[..., None]
    floor = floor * (1 + 0.04 * sheen * depth)

    # Blend wall into floor across a soft band -- the coving curve itself.
    # No hard seam: real backdrop paper has no edge here either, and a crisp
    # line would read as two flat planes glued together rather than one
    # continuous sweep.
    band = 0.07
    blend = np.clip((y - (p.horizon - band)) / (2 * band), 0, 1)[..., None]
    blend = blend * blend * (3 - 2 * blend)  # smoothstep
    return wall * (1 - blend) + floor * blend


_KINDS = {"surface": _surface, "wall": _wall, "doorway": _doorway, "cove": _cove}


def render(preset: str, size: tuple[int, int], seed: int = 0) -> Image.Image:
    """Generate a backdrop. Deterministic for a given (preset, size, seed)."""
    if preset not in PRESETS:
        raise KeyError(f"unknown background {preset!r}; have {sorted(PRESETS)}")
    p = PRESETS[preset]
    w, h = size
    img = _KINDS[p.kind](p, w, h, seed)
    img = img + _grain(w, h, p.grain, seed + 11)
    out = (np.clip(linear_to_srgb(np.clip(img, 0, None)), 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(out, "RGB")


def key_direction(preset: str) -> tuple[float, float]:
    """Where the light comes from, for the relight and shadow stages to agree
    with the backdrop rather than contradict it."""
    return PRESETS[preset].light


@lru_cache(maxsize=None)
def key_luminance(preset: str, size: tuple[int, int] = (256, 256)) -> float:
    """Mean luminance of the backdrop, used to match the product to it.

    Cached because ranking the whole library asks for all thirteen at once and
    the answer is a property of the preset, not of any run.
    """
    bg = np.asarray(render(preset, size), dtype=np.float32) / 255
    lin = srgb_to_linear(bg)
    return float((lin @ np.array([0.2126, 0.7152, 0.0722])).mean())


def luminance_distance(preset: str, product_key: float) -> float:
    """How hard `relight` will have to work to marry the two, as a log ratio.

    The distance is multiplicative rather than absolute because that is the
    form `stages.relight` actually uses: it solves for
    `ratio = 1 + match * (backdrop_key / product_key - 1)` and then bisects
    the blend down until the resulting Lab shift fits the budget. A backdrop
    twice as bright as the product and one half as bright are equally far from
    it in that arithmetic, and `abs(log(...))` is the metric that says so --
    a subtraction would call the dark one much closer than it is.
    """
    k = max(float(product_key), 1e-4)
    return abs(math.log(max(key_luminance(preset), 1e-4) / k))


def rank_by_luminance(presets: list[str], product_key: float) -> list[str]:
    """`presets`, nearest in luminance to the product first.

    This is a preference, never a filter: the whole pool comes back, reordered.
    A dark piece on a dark backdrop is the *easy* render, not always the good
    one, and an operator who wants the dramatic pale-on-charcoal shot must
    still be able to reach it. Ordering only decides what gets offered first.
    """
    return sorted(presets, key=lambda name: luminance_distance(name, product_key))


class DiffusionBackground:
    """Seam for SD1.5-class scene generation (FR-3, doc 06).

    Not wired up. The procedural library covers flat-lay and suggested
    architecture; this is for when a real scene is wanted. Implementing it
    means adding diffusers + ~4 GB of weights to `modal_app.py` and giving it
    the same `render(preset, size, seed)` signature as above.
    """

    def render(self, prompt: str, size: tuple[int, int], seed: int = 0):
        raise NotImplementedError(
            "diffusion backgrounds are not wired up; use a procedural preset. "
            "See backgrounds.DiffusionBackground for what implementing it involves."
        )
