from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.models.recipe import EditRecipe
from app.models.schemas import CamelModel

RenderTier = Literal["draft", "final"]


class RenderRequest(CamelModel):
    recipe: EditRecipe
    max_edge: int | None = Field(default=None, ge=1, le=2560)
    quality: RenderTier = "final"


class RenderResponse(CamelModel):
    preview_url: str
    width: int
    height: int
    quality: RenderTier
    cache_hit: bool
