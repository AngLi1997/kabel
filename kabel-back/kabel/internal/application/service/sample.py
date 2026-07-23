import json
import uuid
import asyncio
from datetime import datetime
from typing import List, Tuple, Union

from pathlib import Path
from loguru import logger
from fastapi import status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from kabel.internal.common.db import begin_transaction
from kabel.internal.common.config import settings
from kabel.internal.common.converter import converter
from kabel.internal.common.error_code import ErrorCode
from kabel.internal.common.error_code import KabelException
from kabel.internal.common.storage import (
    build_thumbnail_key,
    get_storage_backend,
)
from kabel.internal.application.service.access import assert_task_access, assert_owner
from kabel.internal.adapter.persistence import (
    crud_attachment,
    crud_pre_annotation,
    crud_task,
)
from kabel.internal.adapter.persistence import crud_sample
from kabel.internal.adapter.persistence import crud_export_job
from kabel.internal.adapter.persistence import crud_datasource
from kabel.internal.domain.models.user import User
from kabel.internal.domain.models.task import Task
from kabel.internal.domain.models.task import TaskStatus
from kabel.internal.domain.models.sample import TaskSample
from kabel.internal.domain.models.sample import SampleState
from kabel.internal.domain.models.export_job import ExportStatus
from kabel.internal.application.command.sample import ExportType
from kabel.internal.application.command.sample import PatchSampleCommand
from kabel.internal.application.command.sample import CreateSampleCommand
from kabel.internal.application.command.datasource import ImportS3SamplesCommand
from kabel.internal.application.response.base import UserResp
from kabel.internal.application.response.base import CommonDataResp
from kabel.internal.application.response.sample import CreateSampleResponse
from kabel.internal.application.response.sample import SampleResponse
from kabel.internal.application.service.attachment import build_attachment_response
from kabel.internal.clients.ws import sampleConnectionManager
from kabel.internal.common.websocket import Message, MessageType
from kabel.internal.adapter.ws.sample import TaskSampleWsPayload


def is_sample_pre_annotated(
    db: Session, task_id: int, sample_name: str | None = None
) -> bool:
    if sample_name is None:
        return False

    variants = {sample_name, sample_name[9:]}
    existing_names = crud_pre_annotation.existing_sample_names(
        db=db, task_id=task_id, sample_names=variants
    )
    return bool(variants & existing_names)


def get_pre_annotated_sample_names(
    db: Session, task_id: int, sample_names: list[str]
) -> set[str]:
    """Resolve pre-annotation flags for a sample page in one query."""
    variants_by_name = {
        sample_name: {sample_name, sample_name[9:]} for sample_name in sample_names
    }
    candidates = {
        variant for variants in variants_by_name.values() for variant in variants
    }
    existing_names = crud_pre_annotation.existing_sample_names(
        db=db, task_id=task_id, sample_names=candidates
    )
    return {
        sample_name
        for sample_name, variants in variants_by_name.items()
        if variants & existing_names
    }


async def create(
    db: Session, task_id: int, cmd: List[CreateSampleCommand], current_user: User
) -> CreateSampleResponse:
    obj_in = {}
    with begin_transaction(db):
        # check task exist
        task = crud_task.get(db=db, task_id=task_id, lock=True)
        if not task:
            logger.error("cannot find task:{}", task_id)
            raise KabelException(
                code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
                status_code=status.HTTP_404_NOT_FOUND,
            )

        assert_task_access(task, current_user)

        samples = [
            TaskSample(
                inner_id=task.last_sample_inner_id + i + 1,
                task_id=task_id,
                file_id=sample.file_id,
                created_by=current_user.id,
                updated_by=current_user.id,
                data=json.dumps(sample.data, ensure_ascii=False),
            )
            for i, sample in enumerate(cmd)
        ]
        obj_in[Task.last_sample_inner_id.key] = task.last_sample_inner_id + len(cmd)
        if task.status == TaskStatus.DRAFT.value:
            obj_in[Task.status.key] = TaskStatus.IMPORTED
        crud_task.update(db=db, db_obj=task, obj_in=obj_in)
        new_samples = crud_sample.batch(db=db, samples=samples)

    # response
    ids = [s.id for s in new_samples]
    return CreateSampleResponse(ids=ids)


MAX_IMPORT_KEYS = 10000


def _collect_s3_keys(ds, prefix: str, extension: str | None) -> list[str]:
    """List all matching S3 object keys under *prefix*, paginating internally."""
    from kabel.internal.application.service.datasource import _build_s3_client

    client = _build_s3_client(ds)
    full_prefix = prefix if prefix else (ds.prefix or "")

    allowed_exts = None
    if extension:
        allowed_exts = {
            ("." + e.strip().lower().lstrip("."))
            for e in extension.split(",")
            if e.strip()
        }

    keys: list[str] = []
    continuation_token = None

    while True:
        kwargs = {"Bucket": ds.bucket, "Prefix": full_prefix, "MaxKeys": 1000}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token

        try:
            resp = client.list_objects_v2(**kwargs)
        except Exception as exc:
            logger.opt(exception=exc).error(
                "S3 list_objects_v2 failed for datasource {}", ds.id
            )
            raise KabelException(
                code=ErrorCode.CODE_62002_S3_REQUEST_FAILED,
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        for obj in resp.get("Contents", []):
            key: str = obj["Key"]
            if key.endswith("/"):
                continue
            if allowed_exts:
                ext = ("." + key.rsplit(".", 1)[-1].lower()) if "." in key else ""
                if ext not in allowed_exts:
                    continue
            keys.append(key)
            if len(keys) > MAX_IMPORT_KEYS:
                raise KabelException(
                    code=ErrorCode.CODE_62000_S3_IMPORT_TOO_MANY,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        if not resp.get("IsTruncated"):
            break
        continuation_token = resp.get("NextContinuationToken")

    return keys


async def import_from_s3(
    db: Session,
    task_id: int,
    cmd: ImportS3SamplesCommand,
    current_user: User,
) -> CreateSampleResponse:
    """Import S3 objects as task samples (no file copy — stores reference only)."""
    from kabel.internal.domain.models.attachment import TaskAttachment

    with begin_transaction(db):
        task = crud_task.get(db=db, task_id=task_id, lock=True)
        if not task:
            raise KabelException(
                code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
                status_code=status.HTTP_404_NOT_FOUND,
            )

        assert_task_access(task, current_user)

        ds = crud_datasource.get(db=db, ds_id=cmd.data_source_id)
        if not ds:
            raise KabelException(
                code=ErrorCode.CODE_61000_NO_DATA,
                status_code=status.HTTP_404_NOT_FOUND,
            )
        assert_owner(ds, current_user)

        # Resolve object keys: either from explicit list or by listing S3 prefix
        object_keys = cmd.object_keys
        if not object_keys and cmd.prefix is not None:
            object_keys = _collect_s3_keys(ds, cmd.prefix, cmd.extension)

        if not object_keys:
            raise KabelException(
                code=ErrorCode.CODE_62001_S3_IMPORT_NO_MATCH,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        attachments = []
        for key in object_keys:
            filename = key.rsplit("/", 1)[-1] if "/" in key else key
            att = TaskAttachment(
                path=key,
                url="",
                filename=filename,
                task_id=task_id,
                data_source_id=ds.id,
                created_by=current_user.id,
                updated_by=current_user.id,
            )
            db.add(att)
            attachments.append(att)
        db.flush()

        samples = [
            TaskSample(
                inner_id=task.last_sample_inner_id + i + 1,
                task_id=task_id,
                file_id=att.id,
                created_by=current_user.id,
                updated_by=current_user.id,
                data=json.dumps({}),
            )
            for i, att in enumerate(attachments)
        ]
        obj_in = {
            Task.last_sample_inner_id.key: task.last_sample_inner_id + len(samples)
        }
        if task.status == TaskStatus.DRAFT.value:
            obj_in[Task.status.key] = TaskStatus.IMPORTED
        crud_task.update(db=db, db_obj=task, obj_in=obj_in)
        new_samples = crud_sample.batch(db=db, samples=samples)

    return CreateSampleResponse(ids=[s.id for s in new_samples])


def list_by(
    db: Session,
    task_id: Union[int, None],
    after: Union[int, None],
    before: Union[int, None],
    page: Union[int, None],
    size: int,
    sorting: Union[str, None],
    current_user: User,
) -> Tuple[List[SampleResponse], int]:
    if task_id is not None:
        task = crud_task.get(db=db, task_id=task_id)
        if task is not None:
            assert_task_access(task, current_user)
    samples = crud_sample.list_by(
        db=db,
        task_id=task_id,
        after=after,
        before=before,
        page=page,
        size=size,
        sorting=sorting,
    )

    total = crud_sample.count(db=db, task_id=task_id)
    sample_names = [
        sample.file.filename
        for sample in samples
        if sample.file and sample.file.filename
    ]
    pre_annotated_sample_names = get_pre_annotated_sample_names(
        db=db, task_id=task_id, sample_names=sample_names
    )

    # response
    return [
        SampleResponse(
            id=sample.id,
            inner_id=sample.inner_id,
            state=sample.state,
            data=json.loads(sample.data),
            annotated_count=sample.annotated_count,
            is_pre_annotated=(
                sample.file.filename in pre_annotated_sample_names
                if sample.file
                else False
            ),
            file=build_attachment_response(sample.file),
            created_at=sample.created_at,
            created_by=UserResp(
                id=sample.owner.id,
                username=sample.owner.username,
            ),
            updated_at=sample.updated_at,
            updaters=[
                UserResp(
                    id=updater.id,
                    username=updater.username,
                )
                for updater in sample.updaters
            ],
        )
        for sample in samples
    ], total


def get(
    db: Session, task_id: int, sample_id: int, current_user: User
) -> SampleResponse:
    sample = crud_sample.get(
        db=db,
        sample_id=sample_id,
    )

    if not sample or sample.task_id != task_id:
        logger.error("cannot find sample:{}", sample_id)
        raise KabelException(
            code=ErrorCode.CODE_55001_SAMPLE_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    task = crud_task.get(db=db, task_id=sample.task_id)
    if task is not None:
        assert_task_access(task, current_user)

    # response
    return SampleResponse(
        id=sample.id,
        inner_id=sample.inner_id,
        state=sample.state,
        data=json.loads(sample.data),
        is_pre_annotated=is_sample_pre_annotated(
            db=db,
            task_id=task_id,
            sample_name=sample.file.filename if sample.file else None,
        ),
        file=build_attachment_response(sample.file),
        annotated_count=sample.annotated_count,
        created_at=sample.created_at,
        created_by=UserResp(
            id=sample.owner.id,
            username=sample.owner.username,
        ),
        updated_at=sample.updated_at,
        updaters=[
            UserResp(
                id=updater.id,
                username=updater.username,
            )
            for updater in sample.updaters
        ],
    )


def _patch(
    db: Session,
    task_id: int,
    sample_id: int,
    cmd: PatchSampleCommand,
    current_user: User,
) -> SampleResponse:

    # check task exist
    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        logger.error("cannot find task:{}", task_id)
        raise KabelException(
            code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    assert_task_access(task, current_user)

    # get sample
    sample = crud_sample.get(db=db, sample_id=sample_id)
    if not sample or sample.task_id != task_id:
        logger.error("cannot find sample:{}", sample_id)
        raise KabelException(
            code=ErrorCode.CODE_55001_SAMPLE_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # update
    sample_obj_in = {}
    if cmd.state == SampleState.SKIPPED.value:
        sample_obj_in[TaskSample.state.key] = SampleState.SKIPPED.value
    elif cmd.state == SampleState.NEW.value:
        sample_obj_in[TaskSample.data.key] = json.dumps(cmd.data, ensure_ascii=False)
        sample_obj_in[TaskSample.annotated_count.key] = cmd.annotated_count
        sample_obj_in[TaskSample.state.key] = SampleState.NEW.value
    else:  # can be None, or DONE
        sample_obj_in[TaskSample.data.key] = json.dumps(cmd.data, ensure_ascii=False)
        sample_obj_in[TaskSample.annotated_count.key] = cmd.annotated_count
        sample_obj_in[TaskSample.state.key] = SampleState.DONE.value

    with begin_transaction(db):
        # updaters
        if current_user not in sample.updaters:
            sample.updaters.append(current_user)
        # update task sample result
        updated_sample = crud_sample.update(db=db, db_obj=sample, obj_in=sample_obj_in)

        # Determine completion with an indexed existence check after the
        # current sample state has been flushed.
        if task.status != TaskStatus.FINISHED.value:
            has_new_samples = crud_sample.has_state(
                db=db, task_id=task_id, state=SampleState.NEW.value
            )
            next_task_status = (
                TaskStatus.INPROGRESS.value
                if has_new_samples
                else TaskStatus.FINISHED.value
            )
            if task.status != next_task_status:
                crud_task.update(
                    db=db,
                    db_obj=task,
                    obj_in={Task.status.key: next_task_status},
                )

    # response
    return SampleResponse(
        id=updated_sample.id,
        inner_id=updated_sample.inner_id,
        state=updated_sample.state,
        data=json.loads(updated_sample.data),
        is_pre_annotated=is_sample_pre_annotated(
            db=db,
            task_id=task_id,
            sample_name=sample.file.filename if sample.file else None,
        ),
        file=build_attachment_response(updated_sample.file),
        annotated_count=updated_sample.annotated_count,
        created_at=updated_sample.created_at,
        created_by=UserResp(
            id=updated_sample.owner.id,
            username=updated_sample.owner.username,
        ),
        updated_at=updated_sample.updated_at,
        updaters=[
            UserResp(
                id=updater.id,
                username=updater.username,
            )
            for updater in updated_sample.updaters
        ],
    )


async def patch(
    db: Session,
    task_id: int,
    sample_id: int,
    cmd: PatchSampleCommand,
    current_user: User,
) -> SampleResponse:
    data = await run_in_threadpool(
        _patch,
        db=db,
        task_id=task_id,
        sample_id=sample_id,
        cmd=cmd,
        current_user=current_user,
    )

    asyncio.create_task(
        sampleConnectionManager.send_message(
            client_id=f"task_{task_id}",
            message=Message(
                type=MessageType.UPDATE,
                data=TaskSampleWsPayload(
                    task_id=task_id,
                    user_id=current_user.id,
                    username=current_user.username,
                    sample_id=sample_id,
                ),
            ),
            predicate=lambda connection: connection.data.sample_id == sample_id,
        )
    )
    return data


async def delete(
    db: Session, sample_ids: List[int], current_user: User
) -> CommonDataResp:
    storage = get_storage_backend()

    with begin_transaction(db):
        # delete media
        samples = crud_sample.get_by_ids(db=db, sample_ids=sample_ids)
        # authorize: caller must have access to every sample's task
        for task_id in {sample.task_id for sample in samples}:
            task = crud_task.get(db=db, task_id=task_id)
            if task is not None:
                assert_task_access(task, current_user)
        attachment_ids = [sample.file_id for sample in samples if sample.file_id]
        attachments = crud_attachment.get_by_ids(db=db, attachment_ids=attachment_ids)

        attachments = crud_attachment.get_by_ids(db=db, attachment_ids=attachment_ids)
        for attachment in attachments:
            storage.delete(attachment.path)
            thumbnail_key = build_thumbnail_key(attachment.path)
            if storage.exists(thumbnail_key):
                storage.delete(thumbnail_key)

        crud_sample.delete(db=db, sample_ids=sample_ids)
    # response
    return CommonDataResp(ok=True)


async def create_export_job(
    db: Session,
    task_id: int,
    export_type: ExportType,
    sample_ids: List[int],
    current_user: User,
) -> int:
    """Create an export job and start background processing. Returns job_id immediately."""

    task = crud_task.get(db=db, task_id=task_id)
    if not task:
        raise KabelException(
            code=ErrorCode.CODE_50002_TASK_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    assert_task_access(task, current_user)

    with begin_transaction(db):
        job = crud_export_job.create(
            db=db,
            task_id=task_id,
            user_id=current_user.id,
            export_type=export_type.value,
            sample_ids=sample_ids,
        )
        job_id = job.id

    # Run blocking export work in a thread pool to avoid blocking the event loop
    asyncio.get_event_loop().run_in_executor(
        None, _run_export_sync, job_id, task_id, export_type, sample_ids
    )
    return job_id


def _run_export_sync(
    job_id: int, task_id: int, export_type: ExportType, sample_ids: List[int]
):
    """Run export in a thread. All operations here are synchronous and blocking."""
    from kabel.internal.common.db import SessionLocal

    db = SessionLocal()
    try:
        job = crud_export_job.get(db=db, job_id=job_id)
        with begin_transaction(db):
            crud_export_job.update_status(db, job, ExportStatus.PROCESSING.value)

        task = crud_task.get(db=db, task_id=task_id)
        samples = crud_sample.get_by_ids(db=db, sample_ids=sample_ids)

        data = []
        for sample in samples:
            file_dict = {}
            if sample.file:
                file_dict = {
                    "id": sample.file.id,
                    "filename": sample.file.filename,
                    "url": sample.file.url,
                    "path": sample.file.path if hasattr(sample.file, "path") else "",
                }
            data.append(
                {
                    "id": sample.id,
                    "inner_id": sample.inner_id,
                    "state": sample.state,
                    "data": sample.data,
                    "annotated_count": sample.annotated_count,
                    "file": file_dict,
                }
            )

        out_data_dir = Path(settings.MEDIA_ROOT).joinpath(
            settings.EXPORT_DIR,
            f"task-{task_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[0:8]}",
        )

        file_full_path = converter.convert(
            config=json.loads(task.config),
            input_data=data,
            out_data_dir=out_data_dir,
            out_data_file_name_prefix=task_id,
            format=export_type.value,
        )

        storage = get_storage_backend()
        if storage.is_remote:
            local_export_path = Path(file_full_path)
            export_key = f"{settings.EXPORT_DIR}/{local_export_path.name}"
            storage.save_file(local_export_path, export_key)
            local_export_path.unlink(missing_ok=True)
            stored_path = export_key
        else:
            stored_path = str(file_full_path)

        with begin_transaction(db):
            crud_export_job.update_status(
                db,
                job,
                ExportStatus.COMPLETED.value,
                file_path=stored_path,
                processed_count=len(data),
            )
    except Exception as e:
        logger.error("Export job {} failed: {}", job_id, str(e))
        try:
            job = crud_export_job.get(db=db, job_id=job_id)
            with begin_transaction(db):
                crud_export_job.update_status(
                    db,
                    job,
                    ExportStatus.FAILED.value,
                    error_message=str(e),
                )
        except Exception:
            logger.error("Failed to update export job status for job {}", job_id)
    finally:
        db.close()


async def export(
    db: Session,
    task_id: int,
    export_type: ExportType,
    sample_ids: List[int],
    current_user: User,
) -> str:
    """Legacy synchronous export. Kept for backward compatibility."""

    task = crud_task.get(db=db, task_id=task_id)
    samples = crud_sample.get_by_ids(db=db, sample_ids=sample_ids)
    data = []
    for sample in samples:
        file_dict = {}
        if sample.file:
            file_dict = {
                "id": sample.file.id,
                "filename": sample.file.filename,
                "url": sample.file.url,
                "path": sample.file.path if hasattr(sample.file, "path") else "",
            }
        data.append(
            {
                "id": sample.id,
                "inner_id": sample.inner_id,
                "state": sample.state,
                "data": sample.data,
                "annotated_count": sample.annotated_count,
                "file": file_dict,
            }
        )

    # output data path
    out_data_dir = Path(settings.MEDIA_ROOT).joinpath(
        settings.EXPORT_DIR,
        f"task-{task_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[0:8]}",
    )

    # converter to export_type
    file_full_path = converter.convert(
        config=json.loads(task.config),
        input_data=data,
        out_data_dir=out_data_dir,
        out_data_file_name_prefix=task_id,
        format=export_type.value,
    )

    # response
    return file_full_path
