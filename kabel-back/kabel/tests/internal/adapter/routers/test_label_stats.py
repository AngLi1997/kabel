import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from kabel.internal.adapter.persistence import crud_sample, crud_task, crud_user
from kabel.internal.common.config import settings
from kabel.internal.common.db import begin_transaction
from kabel.internal.domain.models.sample import TaskSample
from kabel.internal.domain.models.task import Task


class TestLabelStatsRouter:
    def test_label_statistics(
        self, client: TestClient, testuser_token_headers: dict, db: Session
    ) -> None:
        current_user = crud_user.get_user_by_username(
            db=db, username="test@example.com"
        )
        config = {
            "attributes": [{"key": "通用目标", "value": "common", "color": "#ff6600"}],
            "tools": [
                {
                    "tool": "rectTool",
                    "config": {
                        "attributes": [
                            {
                                "key": "矩形目标",
                                "value": "object",
                                "color": "#11bb33",
                            },
                            {
                                "key": "未使用标签",
                                "value": "unused",
                                "color": "#999999",
                            },
                        ]
                    },
                },
                {
                    "tool": "polygonTool",
                    "config": {
                        "attributes": [
                            {
                                "key": "多边形目标",
                                "value": "object",
                                "color": "#3366ff",
                            }
                        ]
                    },
                },
                {
                    "tool": "tagTool",
                    "config": {
                        "attributes": [
                            {
                                "key": "天气",
                                "value": "weather",
                                "type": "array",
                                "options": [
                                    {"key": "晴天", "value": "sunny"},
                                    {"key": "雨天", "value": "rainy"},
                                    {"key": "阴天", "value": "cloudy"},
                                ],
                            }
                        ]
                    },
                },
                {
                    "tool": "textTool",
                    "config": {
                        "attributes": [
                            {
                                "key": "描述",
                                "value": "description",
                                "type": "string",
                            }
                        ]
                    },
                },
            ],
        }
        first_done_result = {
            "rectTool": {
                "toolName": "rectTool",
                "result": [
                    {"id": "1", "label": "common"},
                    {"id": "2", "label": "object"},
                ],
            },
            "polygonTool": {
                "toolName": "polygonTool",
                "result": [{"id": "3", "label": "object"}],
            },
            "tagTool": {
                "toolName": "tagTool",
                "result": [{"id": "4", "value": {"weather": ["sunny", "rainy"]}}],
            },
            "textTool": {
                "toolName": "textTool",
                "result": [{"id": "5", "value": {"description": "ignored"}}],
            },
        }
        second_done_result = {
            "rectTool": {
                "toolName": "rectTool",
                "result": [{"id": "6", "label": "object"}],
            },
            "tagTool": {
                "toolName": "tagTool",
                "result": [{"id": "7", "result": {"weather": "sunny"}}],
            },
        }
        ignored_result = {
            "rectTool": {
                "toolName": "rectTool",
                "result": [
                    {"id": "8", "label": "common"},
                    {"id": "9", "label": "unused"},
                ],
            },
            "tagTool": {
                "toolName": "tagTool",
                "result": [{"id": "10", "value": {"weather": ["cloudy"]}}],
            },
        }

        def sample_data(result: dict) -> str:
            return json.dumps({"result": json.dumps(result, ensure_ascii=False)})

        with begin_transaction(db):
            task = crud_task.create(
                db=db,
                task=Task(
                    name="label statistics",
                    description="description",
                    tips="tips",
                    config=json.dumps(config, ensure_ascii=False),
                    media_type="IMAGE",
                    status="INPROGRESS",
                    created_by=current_user.id,
                    updated_by=current_user.id,
                ),
            )
            crud_sample.batch(
                db=db,
                samples=[
                    TaskSample(
                        task_id=task.id,
                        created_by=current_user.id,
                        updated_by=current_user.id,
                        state="DONE",
                        data=sample_data(first_done_result),
                    ),
                    TaskSample(
                        task_id=task.id,
                        created_by=current_user.id,
                        updated_by=current_user.id,
                        state="DONE",
                        data=sample_data(second_done_result),
                    ),
                    TaskSample(
                        task_id=task.id,
                        created_by=current_user.id,
                        updated_by=current_user.id,
                        state="NEW",
                        data=sample_data(ignored_result),
                    ),
                    TaskSample(
                        task_id=task.id,
                        created_by=current_user.id,
                        updated_by=current_user.id,
                        state="SKIPPED",
                        data=sample_data(ignored_result),
                    ),
                ],
            )

        response = client.get(
            f"{settings.API_V1_STR}/tasks/{task.id}/samples/label_stats",
            headers=testuser_token_headers,
        )

        assert response.status_code == 200
        items = response.json()["data"]["labels"]
        statistics = {
            (item["scope"], item["tool"], item["category"], item["value"]): item
            for item in items
        }
        assert len(items) == 7
        assert statistics[("common", None, None, "common")]["count"] == 1
        assert statistics[("tool", "rectTool", None, "object")]["count"] == 2
        assert statistics[("tool", "rectTool", None, "unused")]["count"] == 0
        assert statistics[("tool", "polygonTool", None, "object")]["count"] == 1
        assert statistics[("tag", "tagTool", "天气", "sunny")]["count"] == 2
        assert statistics[("tag", "tagTool", "天气", "rainy")]["count"] == 1
        assert statistics[("tag", "tagTool", "天气", "cloudy")]["count"] == 0

    def test_label_statistics_not_found(
        self, client: TestClient, testuser_token_headers: dict
    ) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/tasks/0/samples/label_stats",
            headers=testuser_token_headers,
        )

        assert response.status_code == 404
        assert response.json()["err_code"] == 50002
