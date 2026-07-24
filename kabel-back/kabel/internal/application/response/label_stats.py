from typing import List, Union

from pydantic import BaseModel, Field


class LabelStatItem(BaseModel):
    scope: str = Field(description="description: label scope, common, tool, or tag")
    tool: Union[str, None] = Field(
        default=None, description="description: annotation tool name"
    )
    category: Union[str, None] = Field(
        default=None, description="description: tag category name"
    )
    label: str = Field(description="description: configured label name")
    value: str = Field(description="description: configured label value")
    color: Union[str, None] = Field(
        default=None, description="description: configured label color"
    )
    count: int = Field(
        default=0, description="description: annotation count for this label"
    )


class LabelStatsResponse(BaseModel):
    labels: List[LabelStatItem] = Field(
        default_factory=list, description="description: label statistics list"
    )
    total: int = Field(default=0, description="description: total annotation count")
