import json
from typing import Any, Dict, List, Tuple

from fastapi import status
from loguru import logger
from sqlalchemy.orm import Session

from kabel.internal.adapter.persistence import crud_sample, crud_task
from kabel.internal.application.response.label_stats import (
    LabelStatItem,
    LabelStatsResponse,
)
from kabel.internal.application.service.access import assert_task_access
from kabel.internal.common.error_code import ErrorCode, KabelException
from kabel.internal.domain.models.user import User


def _decode_json_object(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}

    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}

    return decoded if isinstance(decoded, dict) else {}


def _configured_label_statistics(
    config: Dict[str, Any],
) -> Tuple[
    List[LabelStatItem],
    Dict[str, int],
    Dict[Tuple[str, str], int],
    Dict[Tuple[str, str], int],
]:
    statistics: List[LabelStatItem] = []
    common_label_indexes: Dict[str, int] = {}
    tool_label_indexes: Dict[Tuple[str, str], int] = {}
    tag_option_indexes: Dict[Tuple[str, str], int] = {}

    def add_statistic(
        *,
        scope: str,
        label: str,
        value: str,
        tool: str | None = None,
        category: str | None = None,
        color: str | None = None,
    ) -> int:
        statistics.append(
            LabelStatItem(
                scope=scope,
                tool=tool,
                category=category,
                label=label,
                value=value,
                color=color,
            )
        )
        return len(statistics) - 1

    for attribute in config.get("attributes") or []:
        if not isinstance(attribute, dict):
            continue
        value = attribute.get("value")
        if not isinstance(value, str) or not value or value in common_label_indexes:
            continue
        common_label_indexes[value] = add_statistic(
            scope="common",
            label=attribute.get("key") or value,
            value=value,
            color=attribute.get("color"),
        )

    tag_attributes: List[Dict[str, Any]] = []
    for tool_config in config.get("tools") or []:
        if not isinstance(tool_config, dict):
            continue
        tool_name = tool_config.get("tool")
        if not isinstance(tool_name, str) or not tool_name:
            continue

        inner_config = tool_config.get("config")
        inner_config = inner_config if isinstance(inner_config, dict) else {}
        attributes = inner_config.get("attributes") or []

        if tool_name == "tagTool":
            tag_attributes.extend(
                attribute for attribute in attributes if isinstance(attribute, dict)
            )
            continue
        if tool_name == "textTool":
            continue

        for attribute in attributes:
            if not isinstance(attribute, dict):
                continue
            value = attribute.get("value")
            statistic_key = (tool_name, value)
            if (
                not isinstance(value, str)
                or not value
                or statistic_key in tool_label_indexes
            ):
                continue
            tool_label_indexes[statistic_key] = add_statistic(
                scope="tool",
                tool=tool_name,
                label=attribute.get("key") or value,
                value=value,
                color=attribute.get("color"),
            )

    if not tag_attributes:
        tag_attributes = [
            attribute
            for attribute in config.get("tagList") or []
            if isinstance(attribute, dict)
        ]

    for attribute in tag_attributes:
        category_value = attribute.get("value")
        if not isinstance(category_value, str) or not category_value:
            continue
        category = attribute.get("key") or category_value
        options = attribute.get("options") or attribute.get("subSelected") or []

        for option in options:
            if not isinstance(option, dict):
                continue
            option_value = option.get("value")
            statistic_key = (category_value, option_value)
            if (
                not isinstance(option_value, str)
                or not option_value
                or statistic_key in tag_option_indexes
            ):
                continue
            tag_option_indexes[statistic_key] = add_statistic(
                scope="tag",
                tool="tagTool",
                category=category,
                label=option.get("key") or option_value,
                value=option_value,
            )

    return (
        statistics,
        common_label_indexes,
        tool_label_indexes,
        tag_option_indexes,
    )


def _annotation_items(tool_result: Any) -> List[Dict[str, Any]]:
    if isinstance(tool_result, list):
        items = tool_result
    elif isinstance(tool_result, dict):
        items = tool_result.get("result") or []
    else:
        items = []

    return [item for item in items if isinstance(item, dict)]


def _count_tag_options(
    tool_result: Any,
    statistics: List[LabelStatItem],
    tag_option_indexes: Dict[Tuple[str, str], int],
) -> None:
    for item in _annotation_items(tool_result):
        values = item.get("value")
        if not isinstance(values, dict):
            values = item.get("result")
        if not isinstance(values, dict):
            continue

        for category_value, selected_values in values.items():
            if not isinstance(selected_values, list):
                selected_values = [selected_values]
            for option_value in selected_values:
                index = tag_option_indexes.get((category_value, option_value))
                if index is not None:
                    statistics[index].count += 1


def _count_sample_labels(
    sample_data: Any,
    statistics: List[LabelStatItem],
    common_label_indexes: Dict[str, int],
    tool_label_indexes: Dict[Tuple[str, str], int],
    tag_option_indexes: Dict[Tuple[str, str], int],
) -> None:
    data = _decode_json_object(sample_data)
    result = _decode_json_object(data.get("result"))

    for result_key, tool_result in result.items():
        if result_key == "tagTool":
            _count_tag_options(tool_result, statistics, tag_option_indexes)
            continue
        if result_key == "textTool":
            continue

        tool_name = result_key
        if isinstance(tool_result, dict) and isinstance(
            tool_result.get("toolName"), str
        ):
            tool_name = tool_result["toolName"]

        for annotation in _annotation_items(tool_result):
            label_value = annotation.get("label") or annotation.get("attribute")
            if not isinstance(label_value, str):
                continue

            index = common_label_indexes.get(label_value)
            if index is None:
                index = tool_label_indexes.get((tool_name, label_value))
            if index is not None:
                statistics[index].count += 1


def get(db: Session, task_id: int, current_user: User) -> LabelStatsResponse:
    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        logger.error("cannot find task:{}", task_id)
        raise KabelException(
            code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    assert_task_access(task, current_user)
    config = _decode_json_object(task.config)
    (
        statistics,
        common_label_indexes,
        tool_label_indexes,
        tag_option_indexes,
    ) = _configured_label_statistics(config)

    for sample_data in crud_sample.iter_done_annotation_data(db=db, task_id=task_id):
        _count_sample_labels(
            sample_data=sample_data,
            statistics=statistics,
            common_label_indexes=common_label_indexes,
            tool_label_indexes=tool_label_indexes,
            tag_option_indexes=tag_option_indexes,
        )

    return LabelStatsResponse(
        labels=statistics,
        total=sum(statistic.count for statistic in statistics),
    )
