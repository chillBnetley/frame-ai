from __future__ import annotations

import struct

import numpy as np


def _s15(value: float) -> bytes:
    return struct.pack(">i", round(value * 65536.0))


def _xyz_tag(x: float, y: float, z: float) -> bytes:
    return b"XYZ " + b"\0\0\0\0" + _s15(x) + _s15(y) + _s15(z)


def _curv_tag(gamma: float = 2.2) -> bytes:
    return b"curv" + b"\0\0\0\0" + struct.pack(">I", 1) + struct.pack(">H", round(gamma * 256.0))


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


def build_display_p3_like_profile() -> bytes:
    """A matrix/TRC RGB profile with Display P3 primaries (D50 adapted)."""
    p3_primaries = [(0.680, 0.320), (0.265, 0.690), (0.150, 0.060)]
    d65 = (0.3127, 0.3290)
    d65_xyz = np.array([0.95047, 1.0, 1.08883], dtype=np.float64)
    d50_xyz = np.array([0.96422, 1.0, 0.82521], dtype=np.float64)
    adapted = _bradford(_rgb_to_xyz(p3_primaries, d65), d65_xyz, d50_xyz)
    tags = {
        b"desc": _desc_tag("Display P3 like"),
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
