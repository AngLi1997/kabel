#!/usr/bin/env python3
"""从 Kabel MySQL 数据库导出版面检测1～6的 YOLO 标签。"""

from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import io
import json
import math
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from zipfile import ZIP_DEFLATED, ZipFile

TASK_NAMES = [f"版面检测{i}" for i in range(1, 7)]
ARCHIVE_ROOT = "版面检测1-版面检测6-yolo"
MANIFEST_FIELDS = [
    "task_id",
    "task_name",
    "sample_id",
    "inner_id",
    "source_image_path",
    "label_path",
    "image_width",
    "image_height",
    "rotate",
    "box_count",
    "sample_updated_at",
]
SKIPPED_FIELDS = ["task_id", "task_name", "sample_id", "inner_id", "reason"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "导出版面检测1～6中有效任务的 DONE 样本，生成只包含标签的 YOLO zip。"
        )
    )
    parser.add_argument(
        "--host", default=os.getenv("KABEL_DB_HOST", "10.20.0.14")
    )
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("KABEL_DB_PORT", "13306"))
    )
    parser.add_argument(
        "--database", default=os.getenv("KABEL_DB_NAME", "labelu")
    )
    parser.add_argument("--user", default=os.getenv("KABEL_DB_USER", "root"))
    parser.add_argument(
        "--password",
        default=os.getenv("KABEL_DB_PASSWORD"),
        help="数据库密码；建议改用 KABEL_DB_PASSWORD 环境变量",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("exports"),
        help="输出目录或以 .zip 结尾的输出文件（默认：exports）",
    )
    return parser.parse_args()


def connect_mysql(args: argparse.Namespace, password: str):
    """同时兼容 pymysql 和项目 mysql 可选依赖 mysqlclient。"""
    common = {
        "host": args.host,
        "port": args.port,
        "user": args.user,
        "password": password,
        "database": args.database,
        "charset": "utf8mb4",
        "connect_timeout": 10,
    }
    try:
        import pymysql

        return pymysql.connect(
            **common,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
            read_timeout=60,
        )
    except ImportError:
        try:
            import MySQLdb
            import MySQLdb.cursors

            mysqlclient_args = dict(common)
            mysqlclient_args["passwd"] = mysqlclient_args.pop("password")
            mysqlclient_args["db"] = mysqlclient_args.pop("database")
            return MySQLdb.connect(
                **mysqlclient_args,
                cursorclass=MySQLdb.cursors.DictCursor,
                autocommit=False,
            )
        except ImportError as exc:
            raise RuntimeError(
                "缺少 MySQL 驱动。请执行：uv sync --extra mysql，"
                "或：uv pip install pymysql"
            ) from exc


def unique_classes(config_text: str) -> list[str]:
    config = json.loads(config_text)
    raw_classes: list[str] = []
    for tool in config.get("tools", []):
        raw_classes.extend(
            attr.get("value")
            for attr in tool.get("config", {}).get("attributes", [])
            if attr.get("value") is not None
        )
    raw_classes.extend(
        attr.get("value")
        for attr in config.get("attributes", [])
        if attr.get("value") is not None
    )
    # 部分旧任务在 config.tools 和 config.attributes 中重复配置了类别。
    return list(dict.fromkeys(raw_classes))


def get_tasks(cursor: Any) -> list[dict[str, Any]]:
    placeholders = ",".join(["%s"] * len(TASK_NAMES))
    cursor.execute(
        f"""
        SELECT id, name, config
        FROM task
        WHERE name IN ({placeholders}) AND deleted_at IS NULL
        """,
        TASK_NAMES,
    )
    rows = cursor.fetchall()
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_name.setdefault(row["name"], []).append(row)

    missing = [name for name in TASK_NAMES if name not in by_name]
    duplicates = [name for name, tasks in by_name.items() if len(tasks) != 1]
    if missing or duplicates:
        details = []
        if missing:
            details.append(f"缺少有效任务：{', '.join(missing)}")
        if duplicates:
            details.append(f"存在多个同名有效任务：{', '.join(duplicates)}")
        raise RuntimeError("；".join(details))
    return [by_name[name][0] for name in TASK_NAMES]


def get_done_samples(cursor: Any, task_ids: list[int]) -> list[dict[str, Any]]:
    placeholders = ",".join(["%s"] * len(task_ids))
    # FIELD 仅用于让清单按版面检测1～6、inner_id 的顺序稳定输出。
    order = ",".join(str(task_id) for task_id in task_ids)
    cursor.execute(
        f"""
        SELECT s.id AS sample_id, s.task_id, s.inner_id, s.updated_at,
               s.data, a.path
        FROM task_sample s
        JOIN task_attachment a ON a.id = s.file_id
        WHERE s.task_id IN ({placeholders})
          AND s.deleted_at IS NULL
          AND a.deleted_at IS NULL
          AND s.state = 'DONE'
        ORDER BY FIELD(s.task_id, {order}), s.inner_id, s.id
        """,
        task_ids,
    )
    return cursor.fetchall()


def safe_source_path(sample_id: int, raw_path: str | None) -> PurePosixPath:
    source = PurePosixPath((raw_path or "").replace("\\", "/"))
    if source.is_absolute() or ".." in source.parts or not source.name:
        raise ValueError(f"样本 {sample_id} 的原图路径无效：{raw_path!r}")
    return source


def yolo_lines(
    sample_id: int,
    result: dict[str, Any],
    class_to_id: dict[str, int],
) -> tuple[list[str], int, int | float, int | float, int | float]:
    width = result.get("width", 0)
    height = result.get("height", 0)
    rotate = result.get("rotate", 0) or 0
    if (
        not isinstance(width, (int, float))
        or not isinstance(height, (int, float))
        or width <= 0
        or height <= 0
    ):
        raise ValueError(f"样本 {sample_id} 的图片尺寸无效：{width}x{height}")

    rect_tool = result.get("rectTool", {})
    boxes = rect_tool.get("result", []) if isinstance(rect_tool, dict) else []
    lines = []
    for box in boxes:
        label = box.get("label", "")
        if label not in class_to_id:
            raise ValueError(f"样本 {sample_id} 存在未知类别：{label!r}")
        x = box.get("x", 0)
        y = box.get("y", 0)
        box_width = box.get("width", 0)
        box_height = box.get("height", 0)
        values = [x, y, box_width, box_height]
        if not all(
            isinstance(value, (int, float)) and math.isfinite(value)
            for value in values
        ):
            raise ValueError(f"样本 {sample_id} 的标注坐标无效：{values}")

        normalized = [
            (x + box_width / 2) / width,
            (y + box_height / 2) / height,
            box_width / width,
            box_height / height,
        ]
        epsilon = 1e-9
        if not all(-epsilon <= value <= 1 + epsilon for value in normalized):
            raise ValueError(
                f"样本 {sample_id} 的归一化坐标超出 [0, 1]：{normalized}"
            )
        # 消除类似 1.0000000000000002 的浮点计算误差，但不掩盖真实越界。
        normalized = [min(1.0, max(0.0, value)) for value in normalized]
        lines.append(
            f"{class_to_id[label]} "
            + " ".join(f"{value:.12g}" for value in normalized)
        )
    return lines, len(boxes), width, height, rotate


def write_csv(rows: Iterable[dict[str, Any]], fields: list[str]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    # BOM 让 Excel 直接打开时可以正确识别中文。
    return "\ufeff" + stream.getvalue()


def resolve_output_path(output: Path) -> Path:
    if output.suffix.lower() == ".zip":
        zip_path = output.expanduser().resolve()
    else:
        timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        zip_path = (
            output.expanduser().resolve()
            / f"版面检测1-版面检测6-yolo-{timestamp}.zip"
        )
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        raise FileExistsError(f"输出文件已存在，不会覆盖：{zip_path}")
    return zip_path


def export(
    args: argparse.Namespace, password: str
) -> tuple[Path, dict[str, Any]]:
    zip_path = resolve_output_path(args.output)
    connection = connect_mysql(args, password)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            tasks = get_tasks(cursor)
            task_ids = [task["id"] for task in tasks]
            classes_by_task = [
                unique_classes(task["config"]) for task in tasks
            ]
            classes = classes_by_task[0]
            if not classes or any(
                item != classes for item in classes_by_task[1:]
            ):
                raise RuntimeError("六个任务去重后的类别或类别顺序不一致")
            samples = get_done_samples(cursor, task_ids)

            class_to_id = {name: index for index, name in enumerate(classes)}
            task_by_id = {task["id"]: task["name"] for task in tasks}
            per_task = {task_id: Counter() for task_id in task_ids}
            seen_label_paths: set[PurePosixPath] = set()
            manifest: list[dict[str, Any]] = []
            skipped: list[dict[str, Any]] = []
            exported_at = datetime.now().astimezone().isoformat()

            try:
                with ZipFile(
                    zip_path, "x", ZIP_DEFLATED, compresslevel=9
                ) as archive:
                    for sample in samples:
                        sample_id = sample["sample_id"]
                        try:
                            outer_data = json.loads(sample["data"])
                            result = json.loads(
                                outer_data.get("result") or "{}"
                            )
                            lines, box_count, width, height, rotate = (
                                yolo_lines(sample_id, result, class_to_id)
                            )
                            source_path = safe_source_path(
                                sample_id, sample["path"]
                            )
                            label_path = (
                                PurePosixPath("labels")
                                .joinpath(source_path)
                                .with_suffix(".txt")
                            )
                            if label_path in seen_label_paths:
                                raise ValueError(
                                    f"标签目标路径重复：{label_path}"
                                )
                        except (KeyError, TypeError, ValueError) as exc:
                            skipped.append(
                                {
                                    "task_id": sample["task_id"],
                                    "task_name": task_by_id[sample["task_id"]],
                                    "sample_id": sample_id,
                                    "inner_id": sample["inner_id"],
                                    "reason": str(exc),
                                }
                            )
                            per_task[sample["task_id"]]["skipped_samples"] += 1
                            continue
                        seen_label_paths.add(label_path)

                        content = "\n".join(lines) + ("\n" if lines else "")
                        archive.writestr(
                            f"{ARCHIVE_ROOT}/{label_path}", content
                        )

                        stats = per_task[sample["task_id"]]
                        stats["samples"] += 1
                        stats["boxes"] += box_count
                        stats["empty_labels"] += box_count == 0
                        stats["rotated_samples"] += bool(rotate)
                        manifest.append(
                            {
                                "task_id": sample["task_id"],
                                "task_name": task_by_id[sample["task_id"]],
                                "sample_id": sample_id,
                                "inner_id": sample["inner_id"],
                                "source_image_path": str(source_path),
                                "label_path": str(label_path),
                                "image_width": width,
                                "image_height": height,
                                "rotate": rotate,
                                "box_count": box_count,
                                "sample_updated_at": str(sample["updated_at"]),
                            }
                        )

                    summary = {
                        "exported_at": exported_at,
                        "database": f"{args.host}:{args.port}/{args.database}",
                        "scope": "版面检测1-版面检测6（仅有效任务、仅 DONE 样本）",
                        "task_ids": task_ids,
                        "class_count": len(classes),
                        "classes": classes,
                        "total_samples": len(manifest),
                        "source_done_samples": len(samples),
                        "skipped_samples": len(skipped),
                        "total_boxes": sum(
                            c["boxes"] for c in per_task.values()
                        ),
                        "empty_label_samples": sum(
                            c["empty_labels"] for c in per_task.values()
                        ),
                        "tasks": {
                            task_by_id[task_id]: {
                                "task_id": task_id,
                                "samples": per_task[task_id]["samples"],
                                "skipped_samples": per_task[task_id][
                                    "skipped_samples"
                                ],
                                "boxes": per_task[task_id]["boxes"],
                                "empty_labels": per_task[task_id][
                                    "empty_labels"
                                ],
                                "rotated_samples": per_task[task_id][
                                    "rotated_samples"
                                ],
                            }
                            for task_id in task_ids
                        },
                        "contains_images": False,
                    }
                    dataset_yaml = "# YOLO class mapping\nnames:\n" + "".join(
                        f"  {index}: {json.dumps(name, ensure_ascii=False)}\n"
                        for index, name in enumerate(classes)
                    )
                    readme = f"""Kabel YOLO 标签导出

导出时间：{exported_at}
范围：版面检测1 至版面检测6 的有效任务，仅导出状态为 DONE 的样本。
内容：classes.txt、dataset.yaml、manifest.csv、skipped_samples.csv、
export_summary.json，以及 labels/ 下的 YOLO 标签。
目录：标签按数据库中的原图相对路径保存，并将扩展名替换为 .txt，避免同名图片互相覆盖。
空标注：已完成但没有检测框的样本保留为空 .txt，可作为负样本。
图片：压缩包不包含原图；manifest.csv 的 source_image_path 记录原图在 Kabel 数据源中的相对路径。
格式：每行是 class_id x_center y_center width height，坐标均已归一化。
异常：无法转换的 DONE 样本不会生成标签，样本 ID 和原因记录在 skipped_samples.csv。
"""
                    archive.writestr(
                        f"{ARCHIVE_ROOT}/classes.txt",
                        "\n".join(classes) + "\n",
                    )
                    archive.writestr(
                        f"{ARCHIVE_ROOT}/dataset.yaml", dataset_yaml
                    )
                    archive.writestr(
                        f"{ARCHIVE_ROOT}/manifest.csv",
                        write_csv(manifest, MANIFEST_FIELDS),
                    )
                    archive.writestr(
                        f"{ARCHIVE_ROOT}/skipped_samples.csv",
                        write_csv(skipped, SKIPPED_FIELDS),
                    )
                    archive.writestr(
                        f"{ARCHIVE_ROOT}/export_summary.json",
                        json.dumps(summary, ensure_ascii=False, indent=2)
                        + "\n",
                    )
                    archive.writestr(f"{ARCHIVE_ROOT}/README.txt", readme)
            except Exception:
                zip_path.unlink(missing_ok=True)
                raise
            finally:
                connection.rollback()
    finally:
        connection.close()
    return zip_path, summary


def validate_zip(zip_path: Path, summary: dict[str, Any]) -> None:
    with ZipFile(zip_path) as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise RuntimeError(f"压缩包校验失败：{bad_file}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("压缩包中存在重名文件")
        label_files = [
            name
            for name in names
            if f"{ARCHIVE_ROOT}/labels/" in name and name.endswith(".txt")
        ]
        label_lines = sum(
            len(archive.read(name).decode("utf-8").splitlines())
            for name in label_files
        )
        if len(label_files) != summary["total_samples"]:
            raise RuntimeError("标签文件数量与导出摘要不一致")
        if label_lines != summary["total_boxes"]:
            raise RuntimeError("检测框数量与导出摘要不一致")


def main() -> int:
    args = parse_args()
    password = args.password
    if password is None:
        password = getpass.getpass("数据库密码：")
    try:
        zip_path, summary = export(args, password)
        validate_zip(zip_path, summary)
    except Exception as exc:
        print(f"导出失败：{exc}", file=sys.stderr)
        return 1

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    empty_count = summary["empty_label_samples"]
    skipped_count = summary["skipped_samples"]
    print(f"导出完成：{zip_path}")
    print(
        f"样本 {summary['total_samples']}，检测框 {summary['total_boxes']}，"
        f"空标注 {empty_count}，跳过 {skipped_count}，"
        f"类别 {summary['class_count']}"
    )
    print(f"SHA-256：{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
