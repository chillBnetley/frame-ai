from __future__ import annotations

from app.ai.contracts import SceneLabel

SCENE_NAMES: dict[SceneLabel, str] = {
    SceneLabel.PORTRAIT: "人像",
    SceneLabel.LANDSCAPE: "风景",
    SceneLabel.STREET: "街拍",
    SceneLabel.ARCHITECTURE: "建筑",
    SceneLabel.NIGHT: "夜景",
    SceneLabel.INDOOR: "室内",
    SceneLabel.FOOD: "美食",
    SceneLabel.NATURE: "自然",
    SceneLabel.OTHER: "其他",
}

__all__ = ["SCENE_NAMES"]
