from __future__ import annotations

import struct

import numpy as np


def _s15(value: float) -> bytes:
    return struct.pack(">i", round(value * 65536.0))


def _xyz_tag(x: float, y: float, z: float) -> bytes:
    return b"XYZ " + b"\0\0\0\0" + _s15(x) + _s15(y) + _s15(z)


def _curv_tag(gamma: float = 2.2) -> bytes:
    return b"curv" + b"\0\0\0\0" + struct.pack(">I", 1) + struct.pack(">H", round(gamma * 256.0))


def _para_tag(function_type: int, *params: float) -> bytes:
    payload = b"para" + b"\0\0\0\0" + struct.pack(">H", function_type) + b"\0\0"
    return payload + b"".join(_s15(value) for value in params)


def _srgb_para_tag() -> bytes:
    # ICC parametric type 3 is exactly the sRGB decode curve:
    # y = (a*x + b)^g for x >= d, otherwise c*x.
    return _para_tag(
        3,
        2.4,
        1.0 / 1.055,
        0.055 / 1.055,
        1.0 / 12.92,
        0.04045,
    )


def _text_tag(text: str) -> bytes:
    return b"text" + b"\0\0\0\0" + text.encode("ascii") + b"\0"


def _desc_tag(text: str) -> bytes:
    ascii_text = text.encode("ascii") + b"\0"
    body = struct.pack(">I", len(ascii_text)) + ascii_text
    body += struct.pack(">I", 0)  # unicode language code
    body += struct.pack(">I", 0)  # unicode character count
    body += struct.pack(">H", 0)  # script code code
    body += b"\0"  # script code count
    body += b"\0" * 67  # macintosh description
    return b"desc" + b"\0\0\0\0" + body


def _rgb_to_xyz(primaries: list[tuple[float, float]], white: tuple[float, float]) -> np.ndarray:
    columns = []
    for x, y in primaries:
        columns.append(np.array([x / y, 1.0, (1.0 - x - y) / y], dtype=np.float64))
    matrix = np.stack(columns, axis=1)
    white_xyz = np.array(
        [white[0] / white[1], 1.0, (1.0 - white[0] - white[1]) / white[1]],
        dtype=np.float64,
    )
    scales = np.linalg.solve(matrix, white_xyz)
    return matrix * scales[None, :]


def _bradford(
    matrix: np.ndarray, source_white: np.ndarray, destination_white: np.ndarray
) -> np.ndarray:
    bradford = np.array(
        [
            [0.8951, 0.2664, -0.1614],
            [-0.7502, 1.7135, 0.0367],
            [0.0389, -0.0685, 1.0296],
        ]
    )
    inverse = np.linalg.inv(bradford)
    source_cone = bradford @ source_white
    destination_cone = bradford @ destination_white
    adaptation = inverse @ np.diag(destination_cone / source_cone) @ bradford
    return adaptation @ matrix


def _icc_profile(tags: dict[bytes, bytes]) -> bytes:
    header = bytearray(128)
    table_size = 4 + 12 * len(tags)
    offset = 128 + table_size
    entries: list[tuple[bytes, int, int]] = []
    data = bytearray()
    for signature, payload in tags.items():
        padding = (-offset) % 4
        if padding:
            data += b"\0" * padding
            offset += padding
        entries.append((signature, offset, len(payload)))
        data += payload
        offset += len(payload)
    total = 128 + table_size + len(data)
    total += (-total) % 4
    header[0:4] = struct.pack(">I", total)
    header[4:8] = b"lcms"
    header[8:12] = struct.pack(">I", 0x02100000)
    header[12:16] = b"mntr"
    header[16:20] = b"RGB "
    header[20:24] = b"XYZ "
    header[24:36] = struct.pack(">HHHHHH", 2026, 11, 3, 0, 0, 0)
    header[36:40] = b"acsp"
    header[44:48] = struct.pack(">I", 0)
    header[64:68] = struct.pack(">I", 0)
    header[68:80] = _s15(0.9642) + _s15(1.0) + _s15(0.8249)
    output = bytearray(header)
    output += struct.pack(">I", len(tags))
    for signature, tag_offset, size in entries:
        output += signature + struct.pack(">II", tag_offset, size)
    output += data
    output += b"\0" * (total - len(output))
    return bytes(output)


def build_display_p3_like_profile(*, description: str = "Display P3 like") -> bytes:
    """A matrix/TRC RGB profile with Display P3 primaries (D50 adapted)."""
    p3_primaries = [(0.680, 0.320), (0.265, 0.690), (0.150, 0.060)]
    d65 = (0.3127, 0.3290)
    d65_xyz = np.array([0.95047, 1.0, 1.08883], dtype=np.float64)
    d50_xyz = np.array([0.96422, 1.0, 0.82521], dtype=np.float64)
    adapted = _bradford(_rgb_to_xyz(p3_primaries, d65), d65_xyz, d50_xyz)
    tags = {
        b"desc": _desc_tag(description),
        b"cprt": _text_tag("public domain"),
        b"wtpt": _xyz_tag(0.9642, 1.0, 0.8249),
        b"rXYZ": _xyz_tag(*adapted[:, 0].tolist()),
        b"gXYZ": _xyz_tag(*adapted[:, 1].tolist()),
        b"bXYZ": _xyz_tag(*adapted[:, 2].tolist()),
        b"rTRC": _curv_tag(),
        b"gTRC": _curv_tag(),
        b"bTRC": _curv_tag(),
    }
    return _icc_profile(tags)


def build_srgb_matrix_profile(
    *,
    description: str = "sRGB matrix/TRC",
    trc: bytes | None = None,
) -> bytes:
    """A structurally exact sRGB matrix/TRC profile with a parametric TRC.

    ``trc`` overrides the default type-3 sRGB curve so tests can exercise the
    other parametric TRC types against the same exact matrix.
    """
    matrix = np.array(
        [
            [0.4360747, 0.3850649, 0.1430804],
            [0.2225045, 0.7168786, 0.0606169],
            [0.0139322, 0.0971045, 0.7141733],
        ],
        dtype=np.float64,
    )
    curve = _srgb_para_tag() if trc is None else trc
    tags = {
        b"desc": _desc_tag(description),
        b"cprt": _text_tag("public domain"),
        b"wtpt": _xyz_tag(0.9642, 1.0, 0.8249),
        b"rXYZ": _xyz_tag(*matrix[:, 0].tolist()),
        b"gXYZ": _xyz_tag(*matrix[:, 1].tolist()),
        b"bXYZ": _xyz_tag(*matrix[:, 2].tolist()),
        b"rTRC": curve,
        b"gTRC": curve,
        b"bTRC": curve,
    }
    return _icc_profile(tags)


def build_srgb_matrix_profile_with_delta(
    signs: tuple[int, ...],
    *,
    step: float = 32.0 / 65536.0,
) -> bytes:
    """An sRGB matrix/TRC profile whose matrix entries are displaced by ``signs``.

    Each of the nine matrix entries is ``sRGB + sign * step``; the tolerance
    tests use this to construct a profile that is still structurally accepted
    but whose composed transform drifts from identity.
    """
    matrix = (
        np.array(
            [
                [0.4360747, 0.3850649, 0.1430804],
                [0.2225045, 0.7168786, 0.0606169],
                [0.0139322, 0.0971045, 0.7141733],
            ],
            dtype=np.float64,
        )
        + np.array(signs, dtype=np.float64).reshape(3, 3) * step
    )
    curve = _srgb_para_tag()
    tags = {
        b"desc": _desc_tag("Perturbed sRGB matrix"),
        b"rXYZ": _xyz_tag(*matrix[:, 0].tolist()),
        b"gXYZ": _xyz_tag(*matrix[:, 1].tolist()),
        b"bXYZ": _xyz_tag(*matrix[:, 2].tolist()),
        b"rTRC": curve,
        b"gTRC": curve,
        b"bTRC": curve,
    }
    return _icc_profile(tags)


def build_structured_lut_profile(tag: str = "D2B0") -> bytes:
    """An exact sRGB matrix/TRC profile plus one v4 ``D2B*``/``B2D*`` tag.

    The tag payload is never parsed: the structured tag signature alone must
    make the profile fail closed instead of falling into the matrix/TRC path.
    """
    matrix = np.array(
        [
            [0.4360747, 0.3850649, 0.1430804],
            [0.2225045, 0.7168786, 0.0606169],
            [0.0139322, 0.0971045, 0.7141733],
        ],
        dtype=np.float64,
    )
    curve = _srgb_para_tag()
    tags = {
        b"desc": _desc_tag("Structured LUT profile"),
        b"rXYZ": _xyz_tag(*matrix[:, 0].tolist()),
        b"gXYZ": _xyz_tag(*matrix[:, 1].tolist()),
        b"bXYZ": _xyz_tag(*matrix[:, 2].tolist()),
        b"rTRC": curve,
        b"gTRC": curve,
        b"bTRC": curve,
        tag.encode("latin-1"): b"mAB " + b"\0" * 12,
    }
    return _icc_profile(tags)


def build_adobe_rgb_like_profile(*, parametric: bool = False) -> bytes:
    """An Adobe RGB (1998)-like matrix/TRC profile with gamma 2.2.

    ``parametric=True`` writes a type-0 ``para`` TRC instead of ``curv``.
    """
    primaries = [(0.64, 0.33), (0.21, 0.71), (0.15, 0.06)]
    d65 = (0.3127, 0.3290)
    d65_xyz = np.array([0.95047, 1.0, 1.08883], dtype=np.float64)
    d50_xyz = np.array([0.96422, 1.0, 0.82521], dtype=np.float64)
    adapted = _bradford(_rgb_to_xyz(primaries, d65), d65_xyz, d50_xyz)
    gamma = 2.19921875
    curve = _para_tag(0, gamma) if parametric else _curv_tag(gamma)
    tags = {
        b"desc": _desc_tag("Adobe RGB like"),
        b"cprt": _text_tag("public domain"),
        b"wtpt": _xyz_tag(0.9642, 1.0, 0.8249),
        b"rXYZ": _xyz_tag(*adapted[:, 0].tolist()),
        b"gXYZ": _xyz_tag(*adapted[:, 1].tolist()),
        b"bXYZ": _xyz_tag(*adapted[:, 2].tolist()),
        b"rTRC": curve,
        b"gTRC": curve,
        b"bTRC": curve,
    }
    return _icc_profile(tags)


def build_lut_only_profile(*, description: str = "Display P3 LUT") -> bytes:
    """A matrix profile with an A2B0 LUT tag added, so it must be rejected."""
    base = build_display_p3_like_profile()
    # Rebuild with an LUT tag; the payload never has to be a usable LUT because
    # the safe parser rejects the profile on the tag signature alone.
    p3_primaries = [(0.680, 0.320), (0.265, 0.690), (0.150, 0.060)]
    d65 = (0.3127, 0.3290)
    d65_xyz = np.array([0.95047, 1.0, 1.08883], dtype=np.float64)
    d50_xyz = np.array([0.96422, 1.0, 0.82521], dtype=np.float64)
    adapted = _bradford(_rgb_to_xyz(p3_primaries, d65), d65_xyz, d50_xyz)
    tags = {
        b"desc": _desc_tag(description),
        b"rXYZ": _xyz_tag(*adapted[:, 0].tolist()),
        b"gXYZ": _xyz_tag(*adapted[:, 1].tolist()),
        b"bXYZ": _xyz_tag(*adapted[:, 2].tolist()),
        b"rTRC": _curv_tag(),
        b"gTRC": _curv_tag(),
        b"bTRC": _curv_tag(),
        b"A2B0": b"mft1" + b"\0" * 12,
    }
    assert base
    return _icc_profile(tags)
