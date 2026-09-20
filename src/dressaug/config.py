"""Vocabularies, thresholds and job settings.

Same shape as the sibling jewellery project's `imgaug/config.py` — one module
that holds every constant the pipeline argues from, so a threshold is a thing
you can read and change rather than a number buried in a stage.

What is different is the subject, and it is different in a way that matters
more than it looks. Jewellery is small, opaque and rigid. A gown is large,
often **partly transparent**, and its shape is carried by folds that are part
of the product rather than lighting error. Almost every deviation from the
sibling's numbers traces back to one of those three facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

DEFAULT_PROFILE = "dev"

#: Repo root — this file is src/dressaug/config.py.
ROOT = Path(__file__).resolve().parents[2]
#: Per-job scratch: every intermediate a stage chose to keep. Regenerable, so
#: it is gitignored and safe to delete wholesale.
WORK_DIR = ROOT / "work"
#: Finished exports.
OUT_DIR = ROOT / "output"
#: Datasets and the fixtures cut from them.
DATA_DIR = ROOT / "data"


class Phase(str, Enum):
    """The agreed roadmap, in order. Recorded here so code can say which
    phase it belongs to and so nothing claims to be further along than it is.

    Phases 1-4 are deterministic image processing and are the same shape as
    the jewellery spine. Phase 5 is the first that needs a generative model,
    and Phase 6 needs a body to hang a garment on — both are real departures
    and are treated as such, not as more of the same.
    """

    P1_CUTOUT = "1-background-removal"
    P2_BACKDROP = "2-relevant-background"
    P3_COLOURWAY = "3-recolour-preserving-design"
    P4_SHADED = "4-shaded-and-multi-tone-colour"
    P5_DESIGN_EDIT = "5-design-edit-by-prompt"
    P6_DUMMY = "6-dress-on-a-dummy"


class Garment(str, Enum):
    """What the shop actually sells. Women's occasionwear, not casual.

    Deliberately narrow. A pipeline that tries to cover t-shirts and ballgowns
    at once ends up tuned for neither, and the whole reason the sibling
    project's numbers are trustworthy is that they were measured against one
    catalogue rather than assumed from a general one.
    """

    GOWN = "gown"                 # floor-length, structured or flowing
    PARTY_DRESS = "party_dress"   # cocktail and shorter occasion dresses
    LEHENGA = "lehenga"           # skirt + blouse + dupatta, sold as a set
    SAREE = "saree"               # a single draped length; shape comes later
    ANARKALI = "anarkali"         # floor-length flared kurta


class Fabric(str, Enum):
    """Relighting and matting treatment are chosen from this.

    **Transparency is the axis that matters**, and it is the thing the
    jewellery project never had to think about. A bangle is opaque: a pixel is
    product or it is background. A tulle skirt or a chiffon dupatta is
    *genuinely* both, and a matte that forces it to one or the other either
    eats the hem or drags the old background through with it.

    So these are ordered by how much of the background shows through, and the
    matting stage reads that ordering rather than guessing per photograph.
    """

    #: Cotton, crepe, structured satin lining — opaque, behaves like any solid.
    OPAQUE = "opaque"
    #: Satin, silk, taffeta — opaque but throws real highlights along folds.
    SHEEN = "sheen"
    #: Velvet — opaque, absorbs light, and has a nap that reads darker one way.
    VELVET = "velvet"
    #: Sequins, zari, mirror work, heavy beading — specular, high frequency.
    EMBELLISHED = "embellished"
    #: Lace and net — mostly transparent between a dense, fine pattern.
    LACE = "lace"
    #: Chiffon, georgette, organza, tulle — continuously semi-transparent.
    SHEER = "sheer"


#: Fabrics whose alpha is genuinely fractional over large areas, so a hard
#: threshold on the matte destroys the product rather than tidying it.
SEMI_TRANSPARENT: frozenset = frozenset({Fabric.LACE, Fabric.SHEER})


class Graph(str, Enum):
    """Which stage list a job runs."""

    #: Phases 1-4. A garment photographed flat, folded, or on a hanger, with
    #: the background replaced and optionally recoloured.
    FLAT = "flat"
    #: Phase 6. The same garment placed onto a dress form or mannequin.
    #: Needs a body plate and its geometry — the direct analogue of the
    #: jewellery project's wrist plate, and blocked on the same kind of thing:
    #: a real photograph of the actual dummy.
    DUMMY = "dummy"


#: Which fabric a garment type is assumed to be when nobody has said.
#: A default, never a claim — the operator overrides it per photograph.
GARMENT_DEFAULTS: dict[Garment, Fabric] = {
    Garment.GOWN: Fabric.SHEEN,
    Garment.PARTY_DRESS: Fabric.OPAQUE,
    Garment.LEHENGA: Fabric.EMBELLISHED,
    Garment.SAREE: Fabric.SHEER,
    Garment.ANARKALI: Fabric.SHEER,
}

#: Source folder name -> garment type, so the operator can drop photographs
#: into a folder named after the stock and the pipeline knows what it is.
FOLDER_TO_GARMENT: dict[str, Garment] = {
    "Gowns": Garment.GOWN,
    "Gown": Garment.GOWN,
    "Party Dresses": Garment.PARTY_DRESS,
    "Dresses": Garment.PARTY_DRESS,
    "Lehengas": Garment.LEHENGA,
    "Lehenga": Garment.LEHENGA,
    "Sarees": Garment.SAREE,
    "Saree": Garment.SAREE,
    "Anarkali": Garment.ANARKALI,
}


@dataclass(frozen=True)
class Thresholds:
    """Every number the pipeline judges by.

    Where a value differs from the sibling jewellery project the comment says
    why, because "we changed it" without a reason is how a threshold becomes
    folklore.
    """

    # ---- input quality ------------------------------------------------------
    #: Reject below this. Same as the sibling: below 512px nothing downstream
    #: can recover a usable edge.
    min_short_edge_reject: int = 512
    #: Warn below this. **Higher than the sibling's 1024.** A gown is a tall
    #: subject photographed whole, so the garment's *detail* — a lace hem, a
    #: beaded neckline — occupies a far smaller share of the frame than a
    #: bangle does. The same detail therefore needs more pixels overall.
    min_short_edge_warn: int = 1400

    # ---- colour -------------------------------------------------------------
    #: The promise to the customer, in CIEDE2000. Same as the sibling, and for
    #: the same reason: a dress that arrives a different colour is a return.
    max_delta_e2000: float = 3.0
    #: Alpha at or above this counts as fully solid when measuring colour.
    #: **Lower than the sibling's 0.98.** On a sheer fabric almost nothing
    #: reaches 0.98, and at that cutoff the colour gate would end up measuring
    #: only the lining and seams — the least representative pixels in the
    #: photograph.
    alpha_solid: float = 0.90

    # ---- matting ------------------------------------------------------------
    #: Below this, a pixel is background. Deliberately low: on tulle the true
    #: alpha of a real hem is often 0.1-0.2, and a higher floor amputates it.
    alpha_floor: float = 0.04
    #: A semi-transparent garment is expected to have a wide band of partial
    #: alpha. If *less* than this fraction of the matte is partial on a fabric
    #: declared sheer, the matte has probably been hardened and the drape lost.
    min_partial_alpha_on_sheer: float = 0.06
    #: How much of the frame the garment may occupy before framing looks wrong.
    min_product_coverage: float = 0.06
    max_product_coverage: float = 0.94

    # ---- framing ------------------------------------------------------------
    #: How much of the frame height a garment fills before margins. Higher
    #: than any jewellery value: a gown is the subject of the photograph, not
    #: an object placed within one, and a generous margin makes it read as a
    #: swatch rather than as a dress.
    garment_fill: float = 0.88

    # ---- grounding, added 2026-09-19 ----------------------------------------
    # Found necessary on a real full-length photo: a subject composited onto
    # a plain gradient with nothing establishing contact with a surface reads
    # as pasted rather than photographed -- "floating in air", in the words
    # of the person who noticed it. A soft shadow at the subject's own lowest
    # contact point (feet, or a garment's hem) is the standard studio-
    # photography fix, cheaper and more robust than trying to paint an actual
    # floor plane that would have to be coordinated with wherever `place`
    # happens to put the subject.
    #: How dark the contact shadow gets at its centre. Moderate on purpose --
    #: a shadow strong enough to be unmistakable but not so strong it reads
    #: as a design element of its own. Raised from an initial 0.38 to 0.45
    #: after measuring the first value directly on a real photograph and
    #: finding the visible darkening only ~4-6% at the point closest to the
    #: subject -- most of the shadow's peak sits under the subject's own
    #: opaque pixels and is overwritten (see `contact_shadow`'s offset logic).
    contact_shadow_opacity: float = 0.45
    #: The contact band read off the bottom of the placed subject, as a
    #: fraction of its own height -- this is what the shadow's width and
    #: position are measured from, not a fixed guess independent of the
    #: actual photograph.
    contact_shadow_band: float = 0.06
    #: Below this per-column density in the contact band, a column counts as
    #: "nothing there to cast a shadow" -- keeps a stray wisp of hair at the
    #: very edge of the frame from being read as a foot.
    contact_shadow_min_density: float = 0.05
    #: Softness of the shadow's edge, as a fraction of the canvas's short
    #: side. Large on purpose -- a contact shadow that is too crisp looks
    #: painted on; real bounce light under a standing figure is diffuse.
    contact_shadow_blur: float = 0.018
    #: How much empty canvas to leave below the subject's own lowest point,
    #: as a fraction of canvas height. **The other half of the grounding fix**
    #: -- `place` used to centre the bounding box vertically, which for a
    #: full-length photo put equal empty backdrop above the head and below
    #: the feet. No real full-length photograph is framed that way; the
    #: convention is a small margin below and the rest of the slack as
    #: headroom above. Found on the same real photograph as the contact
    #: shadow -- a shadow correctly placed under feet that are themselves
    #: floating in the vertical centre of the canvas does not read as
    #: grounded, because there is visibly empty backdrop beneath the shadow
    #: too.
    bottom_margin: float = 0.05

    # ---- lighting harmonisation, added 2026-09-19 ---------------------------
    #: How much of the backdrop's own ambient colour cast to lend the subject,
    #: 0 = untouched, 1 = fully matched. Deliberately small: this is meant to
    #: read as "the same lights were on the subject and the backdrop", not to
    #: recolour the garment. Bounded further by `harmonize_gain_min/max` below
    #: and, in the end, by the `colour_fidelity` gate itself -- this setting
    #: only has to be small enough that gate stays comfortably clear of its
    #: budget on real photographs, which it was measured to do.
    harmonize_strength: float = 0.16
    #: Hard floor/ceiling on the per-channel gain regardless of strength, so a
    #: strongly saturated backdrop (midnight_velvet, wine_drape) can't swing
    #: the subject further than a believable "same room" adjustment.
    harmonize_gain_min: float = 0.92
    harmonize_gain_max: float = 1.08
    #: The same idea, applied more cautiously to an operator's own uploaded
    #: backdrop photograph. Every procedural preset above was designed with
    #: a specific, muted palette and already measured safely inside the
    #: colour_fidelity budget (§1h: 0.24-2.12 against 3.0). A photographed
    #: backdrop carries no such guarantee -- it can be any colour at all,
    #: including strongly saturated ones -- so it gets half the strength and
    #: half the deviation range. Found necessary on the first real test: a
    #: single strongly saturated flat colour pushed dE2000 to 3.26, over
    #: budget, at the ordinary preset settings.
    harmonize_strength_custom: float = 0.08
    harmonize_gain_min_custom: float = 0.96
    harmonize_gain_max_custom: float = 1.04

    # ---- recolouring (phase 3 and 4) ---------------------------------------
    #: A recolour must not move lightness structure, only hue and chroma.
    #: This is the whole of phase 3's "no change in design": the folds, the
    #: embroidery and the shadows are lightness, and they must survive.
    max_recolour_luma_shift: float = 1.5
    #: Phase 4. A garment with a shaded or ombre colour is not one colour, so
    #: recolouring it by a single hue rotation destroys the gradient. Above
    #: this spread in hue across the solid region, treat it as multi-tone and
    #: recolour by mapping the *distribution* rather than by one rotation.
    shaded_hue_spread_deg: float = 22.0
    #: Ignore hue readings from pixels this unsaturated — near-greys have a
    #: numerically unstable hue and would otherwise dominate the spread.
    min_chroma_for_hue: float = 6.0


THRESHOLDS = Thresholds()


@dataclass(frozen=True)
class ExportPreset:
    name: str
    width: int
    height: int
    quality: int = 92
    margin: float = 0.06


#: Portrait-first, unlike the jewellery project's square-first. A gown at 1:1
#: is either cropped at the hem or floating in side margins.
EXPORT_PRESETS: dict[str, ExportPreset] = {
    "portrait_2x3": ExportPreset("portrait_2x3", 1365, 2048),
    "portrait_4x5": ExportPreset("portrait_4x5", 1638, 2048),
    "story_9x16": ExportPreset("story_9x16", 1152, 2048, margin=0.12),
    "web_card_3x4": ExportPreset("web_card_3x4", 1200, 1600),
    "square": ExportPreset("square", 2048, 2048),
}

DEFAULT_PRESETS = ["portrait_2x3", "web_card_3x4"]


@dataclass
class JobConfig:
    """One garment's worth of settings."""

    graph: Graph = Graph.FLAT
    garment: Garment = Garment.PARTY_DRESS
    fabric: Fabric | None = None
    background: str = "studio_ivory"
    presets: list[str] = field(default_factory=lambda: list(DEFAULT_PRESETS))
    profile: str = DEFAULT_PROFILE
    #: Colourway names to render alongside the base image (phase 3).
    colourways: list[str] = field(default_factory=list)
    #: Phase 6 — which dummy plate to place onto.
    dummy: str | None = None

    def resolved_fabric(self) -> Fabric:
        """The declared fabric, or the garment type's default."""
        return self.fabric or GARMENT_DEFAULTS[self.garment]

    def is_semi_transparent(self) -> bool:
        return self.resolved_fabric() in SEMI_TRANSPARENT
