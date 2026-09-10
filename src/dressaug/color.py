"""Colour science for the fidelity gate.

**Taken verbatim from the sibling jewellery project** (`Image Augmentation`,
`src/imgaug/color.py`), because CIEDE2000 is colour science and knows nothing
about what it is measuring. It is conformance-tested there against the
Sharma, Wu & Dalal reference pairs, and copying it unchanged means those
tests still describe this file.

The requirement it serves is the same and matters more here, not less: a
garment's colour has to survive the pipeline within a measured tolerance,
because a gown that ships a different red than the listing showed is a
return. Phase 3 of this project -- recolouring a dress without touching its
design -- is *entirely* a colour-accuracy problem, so this module is load
bearing rather than a gate at the end.

Everything here is numpy-only and runs on any machine; no GPU involved.
"""

from __future__ import annotations

import numpy as np

# D65 white point, 2° observer.
_WHITE = np.array([0.95047, 1.00000, 1.08883])

# sRGB (linear) -> XYZ
_M = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    """rgb in [0,1]. The piecewise sRGB transfer function, not a 2.2 gamma —
    the difference lands squarely in the dark tones, which is where thread
    and shadow detail lives."""
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(lin: np.ndarray) -> np.ndarray:
    lin = np.clip(lin, 0.0, 1.0)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """(..., 3) sRGB in [0,1] -> (..., 3) CIELAB."""
    xyz = srgb_to_linear(rgb) @ _M.T / _WHITE
    eps = 216 / 24389
    kappa = 24389 / 27
    f = np.where(xyz > eps, np.cbrt(xyz), (kappa * xyz + 16) / 116)
    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], axis=-1)


def delta_e2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIEDE2000 between two (..., 3) Lab arrays.

    Implemented from Sharma, Wu & Dalal (2005). The hue-difference and
    rotation terms are the reason this is not just Euclidean distance:
    perceptual tolerance is much tighter in the neutrals and much looser in
    saturated blues, and this catalogue is mostly saturated reds — where
    ΔE76 would happily report a visible shift as passing.
    """
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]

    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    C_bar = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(C_bar**7 / (C_bar**7 + 25.0**7 + 1e-12)))

    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360

    dLp = L2 - L1
    dCp = C2p - C1p

    dhp = h2p - h1p
    dhp = np.where(dhp > 180, dhp - 360, dhp)
    dhp = np.where(dhp < -180, dhp + 360, dhp)
    dhp = np.where(C1p * C2p == 0, 0.0, dhp)
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp / 2))

    Lp_bar = (L1 + L2) / 2
    Cp_bar = (C1p + C2p) / 2

    hsum = h1p + h2p
    hdiff = np.abs(h1p - h2p)
    hp_bar = np.where(
        C1p * C2p == 0,
        hsum,
        np.where(
            hdiff <= 180,
            hsum / 2,
            np.where(hsum < 360, (hsum + 360) / 2, (hsum - 360) / 2),
        ),
    )

    T = (
        1
        - 0.17 * np.cos(np.radians(hp_bar - 30))
        + 0.24 * np.cos(np.radians(2 * hp_bar))
        + 0.32 * np.cos(np.radians(3 * hp_bar + 6))
        - 0.20 * np.cos(np.radians(4 * hp_bar - 63))
    )

    d_theta = 30 * np.exp(-(((hp_bar - 275) / 25) ** 2))
    R_C = 2 * np.sqrt(Cp_bar**7 / (Cp_bar**7 + 25.0**7 + 1e-12))
    S_L = 1 + (0.015 * (Lp_bar - 50) ** 2) / np.sqrt(20 + (Lp_bar - 50) ** 2)
    S_C = 1 + 0.045 * Cp_bar
    S_H = 1 + 0.015 * Cp_bar * T
    R_T = -np.sin(np.radians(2 * d_theta)) * R_C

    return np.sqrt(
        (dLp / S_L) ** 2
        + (dCp / S_C) ** 2
        + (dHp / S_H) ** 2
        + R_T * (dCp / S_C) * (dHp / S_H)
    )


def mean_product_lab(rgb: np.ndarray, alpha: np.ndarray, solid: float = 0.98) -> np.ndarray:
    """Average Lab of the pixels that are unambiguously product.

    Only fully-opaque pixels are sampled. Edge pixels are a blend of product
    and whatever was behind it, so including them would measure the old
    background as much as the product, and the gate would fail on a correct
    composite purely because the backdrop changed.
    """
    mask = alpha >= solid
    if mask.sum() < 32:  # too little solid product to say anything useful
        mask = alpha >= 0.5
    if mask.sum() == 0:
        return np.array([np.nan, np.nan, np.nan])
    return rgb_to_lab(rgb[mask]).mean(axis=0)


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """(..., 3) CIELAB -> (..., 3) sRGB in [0,1], clipped to gamut."""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200
    eps = 216 / 24389
    kappa = 24389 / 27

    def finv(t):
        t3 = t**3
        return np.where(t3 > eps, t3, (116 * t - 16) / kappa)

    xyz = np.stack([finv(fx), np.where(L > kappa * eps, fy**3, L / kappa), finv(fz)], -1)
    xyz = xyz * _WHITE
    lin = xyz @ np.linalg.inv(_M).T
    return np.clip(linear_to_srgb(lin), 0, 1)


def lab_to_lch(lab: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Lab -> (L, C, h) with h in degrees [0, 360)."""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    return L, np.hypot(a, b), np.degrees(np.arctan2(b, a)) % 360


def lch_to_lab(L: np.ndarray, C: np.ndarray, h: np.ndarray) -> np.ndarray:
    r = np.radians(h)
    return np.stack([L, C * np.cos(r), C * np.sin(r)], axis=-1)


def angular_distance(h1: np.ndarray, h2: float) -> np.ndarray:
    """Shortest distance between hue angles, in degrees [0, 180]."""
    d = np.abs((h1 - h2 + 180) % 360 - 180)
    return d
