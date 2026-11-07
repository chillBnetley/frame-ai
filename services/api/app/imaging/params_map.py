from __future__ import annotations

ENGINE_VERSION = "frame-engine/10"

# Tone
HIGHLIGHTS_EV = 1.0
SHADOWS_EV = 1.5
WHITES_EV = 0.7
# Lightroom/ACR convention: a positive Blacks value raises the black point and
# darkens the shadow end, hence the negative sign where the EV is applied.
BLACKS_EV = -1.0
# Narrower than the old 0.30 so Blacks overlaps Shadows (0.0-0.5) less.
BLACKS_MASK_END = 0.20
WHITES_MASK_START = 0.70
TONE_MASK_SIGMA_RATIO = 0.004
WHITE_BALANCE_RED_GAIN = 0.25
WHITE_BALANCE_BLUE_GAIN = 0.25
WHITE_BALANCE_GREEN_TINT_GAIN = 0.12
CONTRAST_STRENGTH = 1.0
# Contrast keeps its luma curve but may only move chroma by this relative amount.
CONTRAST_CHROMA_TOLERANCE = 0.05

# Color
VIBRANCE_EXPONENT = 1.5

# HSL (band order matches HSL_BANDS)
HSL_BAND_HUES = (0.0, 30.0, 60.0, 120.0, 180.0, 240.0, 285.0, 330.0)
HSL_HUE_LUT_STEP = 0.25
HSL_HUE_MIN_SLOPE = 0.05
HSL_HUE_LIMIT_SWEEPS = 32
HSL_LUMINANCE_EV = 1.0
# Hue is undefined as chroma approaches zero, so it keeps the wide gate.
HSL_HUE_GATE_LOW = 0.02
HSL_HUE_GATE_HIGH = 0.10
# Saturation/luminance stay meaningful on near-neutral pixels (skin, sky,
# pale backgrounds); the narrow gate keeps the sliders responsive there.
HSL_TONE_GATE_LOW = 0.005
HSL_TONE_GATE_HIGH = 0.03
HSL_CHUNK_PIXELS = 1_000_000

# Color grading
COLOR_GRADING_STRENGTH = 0.30
COLOR_GRADING_BALANCE_SHIFT = 0.25
COLOR_GRADING_SHADOW_SPLIT = 0.35
COLOR_GRADING_HIGHLIGHT_SPLIT = 0.65
COLOR_GRADING_BLEND_MIN = 0.08
COLOR_GRADING_BLEND_MAX = 0.60
COLOR_GRADING_CHUNK_PIXELS = 1_000_000

# Local masks
LOCAL_MASK_CHUNK_PIXELS = 1_000_000

# Local
CLARITY_SIGMA_RATIO = 0.015
CLARITY_MIN_SIGMA = 4.0
CLARITY_MAX_SIGMA = 80.0
CLARITY_STRENGTH = 0.8
VIGNETTE_POSITIVE_EV = 1.6
VIGNETTE_NEGATIVE_EV = 1.0

# Detail
DENOISE_H = 12.0
DENOISE_TEMPLATE_DRAFT = 5
DENOISE_SEARCH_DRAFT = 11
DENOISE_TEMPLATE_FINAL = 7
DENOISE_SEARCH_FINAL = 21
EXPORT_DENOISE_SIMPLIFY_PIXELS = 12_000_000
SHARPEN_SIGMA_RATIO = 0.0007
SHARPEN_MIN_SIGMA = 0.5
SHARPEN_MAX_SIGMA = 2.0
SHARPEN_STRENGTH = 1.5
SHARPEN_THRESHOLD = 2.0 / 255.0
GRAIN_AMPLITUDE = 0.05
GRAIN_BLUR_SIGMA_RATIO = 0.0005
GRAIN_MIN_SIGMA = 0.4
GRAIN_MAX_SIGMA = 1.2
GRAIN_SEED_SUFFIX = "|grain|v1"

# Render tiers
DRAFT_MAX_EDGE = 960
FINAL_MAX_EDGE = 1600

# Export memory estimate, calibrated against the review G4 peak-RSS run (single
# process, absolute RSS of the API process tree, 1 sample per case).  Measured
# against the pixels an export actually decodes, the worst full-recipe
# coefficient is 131 B/px (24 MP + 3 locals, 2999 MB) after the curve LUT cut
# the old curve stage from 4.3 GB to 1.2 GB of transient arrays; Task 8's 215
# B/px no longer describes the pipeline.  Neutral stays at 45 B/px (24 MP
# 1043 MB, 40 MP 1635 MB).
EXPORT_BYTES_PER_PIXEL_NEUTRAL = 45
EXPORT_BYTES_PER_PIXEL_FULL = 160
# Each active local adjustment builds a full-canvas float32 weight map (4 B/px)
# plus blend temporaries.  G4 measured the peak delta of adding 3 locals at
# +92 MB over the 24 MP full recipe (3.8 B/px), so this stays a small reserve.
EXPORT_BYTES_PER_PIXEL_LOCAL = 8
# Alpha-capable inputs (PNG/WebP/TIFF) add one float32 coverage plane while
# decoding and another through geometry/render. JPEG inputs never pay this
# reserve.
EXPORT_BYTES_PER_PIXEL_ALPHA = 4
# 16-bit paths. The loader holds the uint16 decode buffer next to the float32
# pipeline image, and the 16-bit output adds a uint16 quantisation plane plus
# the encoder's working copy.  The B5b 24/40 MP peak-RSS run measured only
# +60/+109 MB for neutral recipes over 8-bit and identical peaks for full
# recipes (render-bound), so 18 B/px for each side is a conservative bound, not
# a fitted coefficient; it deliberately rejects 40 MP neutral 16-bit under the
# default budget even though the measured peak is lower.  See
# docs/performance.md.
EXPORT_BYTES_PER_PIXEL_SOURCE_16 = 18
EXPORT_BYTES_PER_PIXEL_OUTPUT_16 = 18
EXPORT_BASELINE_MB = 150
