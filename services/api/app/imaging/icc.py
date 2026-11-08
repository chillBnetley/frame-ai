"""Minimal ICC matrix/TRC colour management for the 16-bit path.

Pillow's ``ImageCms`` cannot transform 16-bit RGB samples without going through
an 8-bit image, so the 16-bit decoder applies the profile here instead.  Only
the ICC v2/v4 matrix/TRC model is supported: ``rXYZ``/``gXYZ``/``bXYZ`` plus
``rTRC``/``gTRC``/``bTRC``.  LUT-based profiles (``A2B*``/``B2A*``/``D2B*``/
``B2D*``/``mAB``/``mBA``/``mft*``) and non-RGB or non-XYZ profiles raise
``UnsupportedProfileError`` instead of being silently treated as sRGB.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

ICC_HEADER_SIZE = 128
_ICC_TAG_TABLE_ENTRY_SIZE = 12
_MAX_TAG_COUNT = 1024
_CHUNK_ROWS = 256

# ICC PCS matrices are D50-referred.  These are the standard sRGB D50 values
# used by lcms, so a matrix/TRC profile with sRGB primaries round-trips.
_SRGB_TO_XYZ_D50 = np.array(
    [
        [0.4360747, 0.3850649, 0.1430804],
        [0.2225045, 0.7168786, 0.0606169],
        [0.0139322, 0.0971045, 0.7141733],
    ],
    dtype=np.float32,
)
_XYZ_TO_SRGB_D50 = np.linalg.inv(_SRGB_TO_XYZ_D50.astype(np.float64)).astype(np.float32)

_TRC_SIGNATURES = {"curv", "para"}
_LUT_SIGNATURES = {
    "A2B0",
    "A2B1",
    "A2B2",
    "B2A0",
    "B2A1",
    "B2A2",
    "D2B0",
    "D2B1",
    "D2B2",
    "D2B3",
    "B2D0",
    "B2D1",
    "B2D2",
    "B2D3",
    "mAB ",
    "mBA ",
    "mft1",
    "mft2",
    "mft ",
}
_REQUIRED_SIGNATURES = ("rXYZ", "gXYZ", "bXYZ", "rTRC", "gTRC", "bTRC")

# The lcms sRGB profile stores the D50 matrix quantised to s15Fixed16; its
# largest component differs from the standard values below by about 2.6e-4.
_SRGB_MATRIX_TOLERANCE = 5e-4
_SRGB_TRC_TOLERANCE = 2e-4
# The identity shortcut must not shift a sample by more than one 8-bit level.
# The element-wise tolerances above are only a cheap pre-filter; the final gate
# samples the composed transform on a 17^3 RGB grid.
_IDENTITY_MAX_ERROR = np.float32(1.0 / 255.0)
_IDENTITY_SAMPLE_STEPS = 17


class UnsupportedProfileError(ValueError):
    """The profile cannot be applied by the matrix/TRC fast path."""


@dataclass(frozen=True)
class _Curve:
    """A sampled TRC evaluated on the 16-bit input grid."""

    table: NDArray[np.float32]

    def apply(self, encoded: NDArray[np.float32]) -> NDArray[np.float32]:
        indices = np.clip(np.rint(encoded * np.float32(65535.0)), 0.0, 65535.0)
        return self.table[indices.astype(np.uint16)]


def _unsupported(detail: str) -> UnsupportedProfileError:
    return UnsupportedProfileError(detail)


def _read_tag_table(profile: bytes) -> dict[str, tuple[int, int]]:
    if len(profile) < ICC_HEADER_SIZE + 4:
        raise _unsupported("profile is shorter than the ICC header")
    declared_size = struct.unpack_from(">I", profile, 0)[0]
    if declared_size < ICC_HEADER_SIZE + 4 or declared_size > len(profile):
        raise _unsupported("profile size is outside the supplied bytes")
    if profile[36:40] != b"acsp":
        raise _unsupported("missing acsp signature")
    colour_space = profile[16:20]
    pcs = profile[20:24]
    if colour_space != b"RGB ":
        raise _unsupported(f"unsupported device colour space {colour_space!r}")
    if pcs != b"XYZ ":
        raise _unsupported(f"unsupported PCS {pcs!r}")

    tag_count = struct.unpack_from(">I", profile, ICC_HEADER_SIZE)[0]
    if tag_count == 0 or tag_count > _MAX_TAG_COUNT:
        raise _unsupported("invalid ICC tag count")
    table_end = ICC_HEADER_SIZE + 4 + tag_count * _ICC_TAG_TABLE_ENTRY_SIZE
    if table_end > declared_size:
        raise _unsupported("ICC tag table exceeds the profile size")

    tags: dict[str, tuple[int, int]] = {}
    offset = ICC_HEADER_SIZE + 4
    for _ in range(tag_count):
        signature = profile[offset : offset + 4].decode("latin-1")
        tag_offset, tag_size = struct.unpack_from(">II", profile, offset + 4)
        offset += _ICC_TAG_TABLE_ENTRY_SIZE
        if tag_size == 0:
            raise _unsupported(f"tag {signature!r} is empty")
        if tag_offset < table_end or tag_offset + tag_size > declared_size:
            raise _unsupported(f"tag {signature!r} points outside the profile")
        tags.setdefault(signature, (tag_offset, tag_size))
    return tags


def _tag_bytes(profile: bytes, tags: dict[str, tuple[int, int]], signature: str) -> bytes:
    try:
        offset, size = tags[signature]
    except KeyError as exc:
        raise _unsupported(f"missing required tag {signature!r}") from exc
    return profile[offset : offset + size]


def _has_lut_tag(tags: dict[str, tuple[int, int]]) -> bool:
    return any(
        signature in _LUT_SIGNATURES
        or signature.startswith(("A2B", "B2A", "D2B", "B2D", "mft", "mAB", "mBA"))
        for signature in tags
    )


def _s15_fixed(data: bytes, offset: int) -> float:
    value = float(struct.unpack_from(">i", data, offset)[0]) / 65536.0
    if not np.isfinite(value):
        raise _unsupported("non-finite ICC fixed-point value")
    return value


def _xyz_triplet(data: bytes, signature: str) -> NDArray[np.float32]:
    if len(data) < 20 or data[:4] != b"XYZ ":
        raise _unsupported(f"{signature} is not an XYZ tag")
    return np.array(
        [_s15_fixed(data, 8), _s15_fixed(data, 12), _s15_fixed(data, 16)],
        dtype=np.float32,
    )


def _gamma_curve(gamma: float) -> NDArray[np.float32]:
    if not np.isfinite(gamma) or gamma <= 0.0:
        raise _unsupported("invalid TRC gamma")
    values = np.linspace(0.0, 1.0, 65536, dtype=np.float32)
    return np.power(values, np.float32(gamma), dtype=np.float32)


def _para_curve(params: list[float], function_type: int) -> NDArray[np.float32]:
    x = np.linspace(0.0, 1.0, 65536, dtype=np.float32)
    if function_type == 0:
        (g,) = params
        y = np.power(x, np.float32(g))
    elif function_type == 1:
        g, a, b = params
        base = np.float32(a) * x + np.float32(b)
        y = np.where(base >= 0.0, np.power(base, np.float32(g)), 0.0)
    elif function_type == 2:
        g, a, b, c = params
        base = np.float32(a) * x + np.float32(b)
        y = np.where(base >= 0.0, np.power(base, np.float32(g)) + np.float32(c), np.float32(c))
    elif function_type == 3:
        g, a, b, c, d = params
        base = np.float32(a) * x + np.float32(b)
        y = np.where(
            x >= np.float32(d),
            np.power(np.maximum(base, 0.0), np.float32(g)),
            np.float32(c) * x,
        )
    elif function_type == 4:
        g, a, b, c, d, e, f = params
        base = np.float32(a) * x + np.float32(b)
        y = np.where(
            x >= np.float32(d),
            np.power(np.maximum(base, 0.0), np.float32(g)) + np.float32(e),
            np.float32(c) * x + np.float32(f),
        )
    else:
        raise _unsupported(f"unsupported parametric TRC type {function_type}")
    return np.clip(y, 0.0, 1.0).astype(np.float32)


def _parse_curve(data: bytes, signature: str) -> _Curve:
    if len(data) < 12:
        raise _unsupported(f"{signature} is truncated")
    kind = data[:4]
    if kind == b"curv":
        count = struct.unpack_from(">I", data, 8)[0]
        if count == 0:
            return _Curve(np.linspace(0.0, 1.0, 65536, dtype=np.float32))
        if count == 1:
            if len(data) < 14:
                raise _unsupported(f"{signature} gamma is truncated")
            gamma = struct.unpack_from(">H", data, 12)[0] / 256.0
            return _Curve(_gamma_curve(gamma))
        if len(data) < 12 + count * 2:
            raise _unsupported(f"{signature} table is truncated")
        table = np.frombuffer(data, dtype=">u2", count=count, offset=12).astype(np.float32)
        table /= np.float32(65535.0)
        sampled = np.interp(
            np.linspace(0.0, 1.0, 65536),
            np.linspace(0.0, 1.0, count),
            table,
        )
        return _Curve(sampled.astype(np.float32))
    if kind == b"para":
        if len(data) < 12:
            raise _unsupported(f"{signature} parametric TRC is truncated")
        function_type = struct.unpack_from(">H", data, 8)[0]
        parameter_count = {0: 1, 1: 3, 2: 4, 3: 5, 4: 7}.get(function_type)
        if parameter_count is None:
            raise _unsupported(f"unsupported parametric TRC type {function_type}")
        if len(data) < 12 + parameter_count * 4:
            raise _unsupported(f"{signature} parametric TRC is truncated")
        params = [_s15_fixed(data, 12 + index * 4) for index in range(parameter_count)]
        return _Curve(_para_curve(params, function_type))
    raise _unsupported(f"{signature} is not a curv/para tag")


def _srgb_encode(linear: NDArray[np.float32]) -> NDArray[np.float32]:
    clipped = np.clip(linear, 0.0, 1.0)
    low = clipped * np.float32(12.92)
    high = np.float32(1.055) * np.power(clipped, np.float32(1.0 / 2.4)) - np.float32(0.055)
    encoded = np.where(clipped <= np.float32(0.0031308), low, high)
    return np.clip(encoded, 0.0, 1.0).astype(np.float32)


def _srgb_decode(encoded: NDArray[np.float32]) -> NDArray[np.float32]:
    low = encoded / np.float32(12.92)
    high = np.power(
        (encoded + np.float32(0.055)) / np.float32(1.055),
        np.float32(2.4),
    )
    return np.where(encoded <= np.float32(0.04045), low, high).astype(np.float32)


def is_srgb_matrix_trc(raw: bytes) -> bool:
    """Return True only when treating the profile as sRGB is visually exact.

    This is the safe identity shortcut for 16-bit input.  It deliberately does
    not trust the profile description: the header, tag table, LUT signatures,
    matrices and TRC tables must all pass the same bounded parser used by
    ``transform_to_srgb``, and the composed transform must stay within one
    8-bit level of identity on a 17^3 RGB sample.  Any parse failure, LUT
    signature, or unexpected colour-space tag means the profile is not eligible
    for the shortcut (it is then converted instead of rejected).
    """
    try:
        tags = _read_tag_table(raw)
        if _has_lut_tag(tags):
            return False
        for signature in tags:
            if signature.endswith("TRC") and signature not in {
                "rTRC",
                "gTRC",
                "bTRC",
            }:
                return False

        matrix = np.stack(
            [
                _xyz_triplet(_tag_bytes(raw, tags, signature), signature)
                for signature in ("rXYZ", "gXYZ", "bXYZ")
            ],
            axis=1,
        ).astype(np.float32)
        if not np.allclose(
            matrix,
            _SRGB_TO_XYZ_D50,
            rtol=0.0,
            atol=_SRGB_MATRIX_TOLERANCE,
        ):
            return False

        reference = _srgb_decode(np.linspace(0.0, 1.0, 65536, dtype=np.float32))
        curves: list[_Curve] = []
        for signature in ("rTRC", "gTRC", "bTRC"):
            curve = _parse_curve(_tag_bytes(raw, tags, signature), signature)
            if curve.table.shape != reference.shape:
                return False
            if not np.allclose(
                curve.table,
                reference,
                rtol=0.0,
                atol=_SRGB_TRC_TOLERANCE,
            ):
                return False
            curves.append(curve)

        sample = np.linspace(0.0, 1.0, _IDENTITY_SAMPLE_STEPS, dtype=np.float32)
        grid = np.stack(np.meshgrid(sample, sample, sample, indexing="ij"), axis=-1).reshape(
            1, -1, 3
        )
        linear = np.stack(
            [curve.apply(grid[..., index]) for index, curve in enumerate(curves)],
            axis=-1,
        )
        converted = _srgb_encode(
            np.asarray(linear @ matrix.T @ _XYZ_TO_SRGB_D50.T, dtype=np.float32)
        )
        return bool(np.all(np.abs(converted - grid) <= _IDENTITY_MAX_ERROR))
    except (ValueError, TypeError, struct.error):
        # A predicate must never turn malformed metadata into an identity
        # shortcut; the caller then falls back to transform_to_srgb, whose
        # detailed error is reported as 422 unsupported_icc_profile.
        return False


def transform_to_srgb(
    rgb: NDArray[np.float32],
    profile: bytes,
) -> NDArray[np.float32]:
    """Convert encoded RGB in ``[0, 1]`` from ``profile`` to sRGB.

    The input array is treated as encoded (non-linear) device values.  Output is
    encoded sRGB in ``[0, 1]``.  Processing is row-chunked so a 24-40 MP source
    does not need a second full-size float32 scratch array.
    """
    if rgb.dtype != np.float32 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("rgb must be an HxWx3 float32 array")

    tags = _read_tag_table(profile)
    if _has_lut_tag(tags):
        raise _unsupported("LUT-based ICC profiles are not supported")
    for signature in _REQUIRED_SIGNATURES:
        if signature not in tags:
            raise _unsupported(f"missing required tag {signature!r}")
    for signature in tags:
        if signature.endswith("TRC") and signature not in {
            "rTRC",
            "gTRC",
            "bTRC",
        }:
            raise _unsupported(f"unsupported TRC tag {signature!r}")

    xyz_columns = [
        _xyz_triplet(_tag_bytes(profile, tags, signature), signature)
        for signature in ("rXYZ", "gXYZ", "bXYZ")
    ]
    curves = [
        _parse_curve(_tag_bytes(profile, tags, signature), signature)
        for signature in ("rTRC", "gTRC", "bTRC")
    ]
    matrix = np.stack(xyz_columns, axis=1).astype(np.float32)

    output = np.empty_like(rgb)
    for start in range(0, rgb.shape[0], _CHUNK_ROWS):
        chunk = rgb[start : start + _CHUNK_ROWS]
        linear = np.stack(
            [curve.apply(chunk[..., index]) for index, curve in enumerate(curves)],
            axis=-1,
        )
        xyz = linear @ matrix.T
        converted = np.asarray(xyz @ _XYZ_TO_SRGB_D50.T, dtype=np.float32)
        output[start : start + _CHUNK_ROWS] = _srgb_encode(converted)
    return np.ascontiguousarray(output)
