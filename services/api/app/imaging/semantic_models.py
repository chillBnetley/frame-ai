from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger("frame_ai.semantic")

SemanticClass = Literal["person", "sky"]
SEMANTIC_DIR = Path(__file__).with_name("semantic")
MANIFEST_PATH = SEMANTIC_DIR / "manifest.json"
_MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@dataclass(frozen=True, slots=True)
class ModelSpec:
    kind: SemanticClass
    model_id: str
    version: str
    filename: str
    bytes: int
    sha256: str
    input_size: tuple[int, int]
    mean: tuple[float, float, float]
    bundled: bool
    experimental: bool
    source_url: str


def _spec(kind: SemanticClass) -> ModelSpec:
    entry = _MANIFEST["models"][kind]
    mean = (0.0, 0.0, 0.0) if kind == "person" else (123.675, 116.28, 103.53)
    return ModelSpec(
        kind=kind,
        model_id=str(entry["modelId"]),
        version=str(entry["version"]),
        filename=str(entry["file"]),
        bytes=int(entry["bytes"]),
        sha256=str(entry["sha256"]),
        input_size=(int(entry["input"][0]), int(entry["input"][1])),
        mean=mean,
        bundled=bool(entry["bundled"]),
        experimental=bool(entry.get("experimental", False)),
        source_url=str(entry["sourceUrl"]),
    )


PERSON_SPEC = _spec("person")
SKY_SPEC = _spec("sky")
SPECS: dict[SemanticClass, ModelSpec] = {"person": PERSON_SPEC, "sky": SKY_SPEC}
PREPROCESS_VERSION = str(_MANIFEST["preprocessVersion"])


def file_matches(path: Path, expected_bytes: int, expected_sha256: str) -> bool:
    try:
        if path.stat().st_size != expected_bytes:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == expected_sha256


def ascii_cache_root(data_dir: Path) -> Path:
    if os.name == "nt":
        public = os.environ.get("PUBLIC") or "C:/Users/Public"
        return Path(public) / "FRAME-AI" / "models"
    return _posix_ascii_cache_root(
        data_dir,
        os.environ.get("XDG_CACHE_HOME"),
        Path.home(),
    )


def _posix_ascii_cache_root(data_dir: Path, xdg_home: str | None, home: Path) -> Path:
    if os.fspath(data_dir).isascii():
        return data_dir / "models" / "semantic"
    candidates: list[Path] = []
    if xdg_home is not None and xdg_home.strip():
        candidates.append(Path(xdg_home) / "frame-ai" / "models")
    candidates.append(home / ".cache" / "frame-ai" / "models")
    candidates.append(Path("/tmp/frame-ai-models"))
    for candidate in candidates:
        if os.fspath(candidate).isascii():
            return candidate
    return Path("/tmp/frame-ai-models")


def _cache_writable(root: Path) -> bool:
    try:
        root.mkdir(parents=True, exist_ok=True)
        descriptor, path = tempfile.mkstemp(dir=root, prefix=".write-probe-")
        os.close(descriptor)
        os.unlink(path)
    except OSError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class ModelStatus:
    available: bool
    version: str | None


class SemanticModelRegistry:
    """Validates bundled/local models and loads them from an ASCII path.

    OpenCV DNN cannot open model paths containing non-ASCII characters and
    crashes when handed bytes, so every model is copied to an ASCII cache with a
    verified SHA-256 before ``readNetFrom*`` sees it.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._lock = threading.RLock()
        self._validated: dict[str, tuple[int, int, bool]] = {}
        self._statuses: dict[SemanticClass, ModelStatus] = {
            "person": ModelStatus(False, None),
            "sky": ModelStatus(False, None),
        }
        self._nets: dict[SemanticClass, cv2.dnn.Net] = {}
        self.refresh()

    def source_path(self, kind: SemanticClass) -> Path:
        spec = SPECS[kind]
        if spec.bundled:
            return SEMANTIC_DIR / spec.filename
        return self._data_dir / "models" / "semantic" / spec.filename

    def refresh(self) -> None:
        writable = _cache_writable(ascii_cache_root(self._data_dir))
        if not writable:
            logger.warning("semantic_model_cache_unwritable")
        for kind, spec in SPECS.items():
            path = self.source_path(kind)
            available = writable and self._validated_source(path, spec)
            if not available:
                logger.warning("semantic_model_unavailable kind=%s", kind)
            self._statuses[kind] = ModelStatus(available, spec.version if available else None)

    def status(self, kind: SemanticClass) -> ModelStatus:
        return self._statuses[kind]

    def model_version(self, kind: SemanticClass) -> str | None:
        return self._statuses[kind].version

    def load(self, kind: SemanticClass) -> cv2.dnn.Net | None:
        spec = SPECS[kind]
        if not self._statuses[kind].available:
            return None
        with self._lock:
            cached = self._nets.get(kind)
            if cached is not None:
                return cached
            path = self._prepare_ascii(kind, spec)
            if path is None:
                self._statuses[kind] = ModelStatus(False, None)
                return None
            try:
                if kind == "person":
                    net = cv2.dnn.readNetFromTFLite(str(path))
                else:
                    net = cv2.dnn.readNetFromONNX(str(path))
            except Exception as exc:  # cv2 raises generic cv2.error subclasses
                logger.warning(
                    "semantic_model_load_failed kind=%s error_type=%s",
                    kind,
                    type(exc).__name__,
                )
                self._statuses[kind] = ModelStatus(False, None)
                return None
            self._nets[kind] = net
            return net

    def infer(self, kind: SemanticClass, rgb: NDArray[np.float32]) -> NDArray[np.uint8] | None:
        net = self.load(kind)
        if net is None:
            return None
        spec = SPECS[kind]
        clipped = np.clip(rgb, 0.0, 1.0)
        bgr = np.ascontiguousarray((clipped[..., ::-1] * 255.0).round().astype(np.uint8))
        blob = cv2.dnn.blobFromImage(
            bgr,
            scalefactor=1.0 / 255.0,
            size=spec.input_size,
            mean=spec.mean,
            swapRB=True,
            crop=False,
        )
        try:
            with self._lock:
                net.setInput(blob)
                output = net.forward()
        except Exception as exc:
            logger.warning(
                "semantic_model_forward_failed kind=%s error_type=%s",
                kind,
                type(exc).__name__,
            )
            return None
        plane = output[0, 0] if output.ndim == 4 else output[0]
        resized = cv2.resize(
            plane,
            (rgb.shape[1], rgb.shape[0]),
            interpolation=cv2.INTER_LINEAR,
        )
        raw = np.rint(np.clip(resized, 0.0, 1.0) * 255.0).astype(np.uint8)
        return np.ascontiguousarray(raw)

    def _validated_source(self, path: Path, spec: ModelSpec) -> bool:
        try:
            stat = path.stat()
        except OSError:
            return False
        key = (int(stat.st_mtime_ns), int(stat.st_size))
        cached = self._validated.get(str(path))
        if cached is not None and cached[:2] == key:
            return cached[2]
        valid = file_matches(path, spec.bytes, spec.sha256)
        self._validated[str(path)] = (key[0], key[1], valid)
        return valid

    def _prepare_ascii(self, kind: SemanticClass, spec: ModelSpec) -> Path | None:
        source = self.source_path(kind)
        root = ascii_cache_root(self._data_dir)
        target = root / spec.sha256 / Path(spec.filename).name
        if not os.fspath(target).isascii():
            logger.warning("semantic_model_ascii_path_unavailable kind=%s", kind)
            return None
        temporary: Path | None = None
        try:
            if file_matches(target, spec.bytes, spec.sha256):
                return target
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".tmp")
            with source.open("rb") as src, temporary.open("wb") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
            os.replace(temporary, target)
        except OSError as exc:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            logger.warning(
                "semantic_model_cache_failed kind=%s error_type=%s",
                kind,
                type(exc).__name__,
            )
            return None
        if not file_matches(target, spec.bytes, spec.sha256):
            logger.warning("semantic_model_cache_mismatch kind=%s", kind)
            return None
        return target


__all__ = [
    "MANIFEST_PATH",
    "PERSON_SPEC",
    "PREPROCESS_VERSION",
    "SEMANTIC_DIR",
    "SKY_SPEC",
    "SPECS",
    "ModelSpec",
    "ModelStatus",
    "SemanticClass",
    "SemanticModelRegistry",
    "ascii_cache_root",
    "file_matches",
]
