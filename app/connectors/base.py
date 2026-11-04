
import hashlib
import json
import shutil
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import SourceArtifact, SourceRecord, SourceRegistry, SourceSyncRun

ProgressCallback = Callable[[dict[str, Any]], None]


def emit_progress(
    callback: ProgressCallback | None,
    stage: str,
    message: str,
    fraction: float | None = None,
    **details: Any,
) -> None:
    if callback is None:
        return

    event = {
        "stage": stage,
        "message": message,
        "fraction": (
            max(0.0, min(1.0, fraction))
            if fraction is not None
            else None
        ),
        **details,
    }
    callback(event)


def json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if value is None:
        return None
    if hasattr(value, "item"):
        return json_safe(value.item())
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_record_key(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        json_safe(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def archive_path(source_key: str, filename: str) -> Path:
    now = datetime.now(UTC)
    target_dir = (
        settings.raw_data_dir
        / source_key
        / now.strftime("%Y")
        / now.strftime("%m")
        / now.strftime("%d")
    )
    target_dir.mkdir(parents=True, exist_ok=True)

    return target_dir / f"{now.strftime('%H%M%S_%f')}_{filename}"


def download_source(
    url: str,
    source_key: str,
    filename: str,
    local_path: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[Path, dict[str, Any]]:
    target = archive_path(source_key, filename)

    if local_path:
        if not local_path.is_file():
            raise FileNotFoundError(
                f"Local source file not found: {local_path}"
            )

        total_bytes = local_path.stat().st_size
        emit_progress(
            progress_callback,
            "download",
            "Copying the selected source file into raw archive storage.",
            0.15,
            bytes_received=0,
            total_bytes=total_bytes,
        )

        shutil.copy2(local_path, target)

        emit_progress(
            progress_callback,
            "download",
            "Source file copied into raw archive storage.",
            0.30,
            bytes_received=total_bytes,
            total_bytes=total_bytes,
        )

        return target, {
            "source_url": url,
            "content_type": None,
            "etag": None,
            "last_modified": None,
            "size_bytes": target.stat().st_size,
        }

    emit_progress(
        progress_callback,
        "download",
        "Connecting to the official source and starting download.",
        0.03,
    )

    metadata: dict[str, Any] = {}

    try:
        with httpx.Client(
            timeout=settings.connector_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "DreamBigHealth-MarketAccess/1.0"},
        ) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()

                total_header = response.headers.get("content-length")
                total_bytes = int(total_header) if total_header else None

                metadata = {
                    "source_url": str(response.url),
                    "content_type": response.headers.get("content-type"),
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                }

                bytes_received = 0
                last_reported = 0

                with target.open("wb") as file:
                    for chunk in response.iter_bytes(
                        chunk_size=1024 * 1024
                    ):
                        if not chunk:
                            continue

                        file.write(chunk)
                        bytes_received += len(chunk)

                        if bytes_received - last_reported >= 5 * 1024 * 1024:
                            last_reported = bytes_received

                            if total_bytes:
                                fraction = 0.03 + (
                                    0.27 * bytes_received / total_bytes
                                )
                            else:
                                fraction = None

                            emit_progress(
                                progress_callback,
                                "download",
                                f"Downloaded {bytes_received:,} bytes.",
                                fraction,
                                bytes_received=bytes_received,
                                total_bytes=total_bytes,
                            )

        metadata["size_bytes"] = target.stat().st_size

        emit_progress(
            progress_callback,
            "download",
            "Official source download completed.",
            0.30,
            bytes_received=metadata["size_bytes"],
            total_bytes=metadata["size_bytes"],
        )

        return target, metadata

    except Exception:
        target.unlink(missing_ok=True)
        raise


def register_artifact(
    db: Session,
    source_key: str,
    path: Path,
    metadata: dict[str, Any],
) -> SourceArtifact:
    checksum = sha256_file(path)

    existing = db.scalar(
        select(SourceArtifact).where(
            SourceArtifact.source_key == source_key,
            SourceArtifact.sha256 == checksum,
        )
    )

    if existing:
        return existing

    artifact = SourceArtifact(
        source_key=source_key,
        filename=path.name,
        storage_path=str(path),
        source_url=metadata["source_url"],
        content_type=metadata.get("content_type"),
        size_bytes=metadata["size_bytes"],
        sha256=checksum,
        etag=metadata.get("etag"),
        last_modified=metadata.get("last_modified"),
    )
    db.add(artifact)
    db.flush()
    return artifact


def create_sync_run(
    db: Session,
    source_key: str,
    dataset_key: str,
) -> SourceSyncRun:
    source = db.scalar(
        select(SourceRegistry).where(
            SourceRegistry.source_key == source_key,
            SourceRegistry.is_enabled.is_(True),
        )
    )

    if not source:
        raise ValueError(
            f"Enabled source registry entry not found: {source_key}"
        )

    run = SourceSyncRun(
        source_key=source_key,
        dataset_key=dataset_key,
        status="running",
    )
    db.add(run)
    db.flush()
    return run


def upsert_records(
    db: Session,
    run: SourceSyncRun,
    source_key: str,
    dataset_key: str,
    records: Iterable[dict[str, Any]],
    progress_callback: ProgressCallback | None = None,
    expected_rows: int | None = None,
) -> dict[str, int]:
    """
    Insert new versioned records and refresh previously seen records.

    Identical payloads share a stable record key. Changed payloads
    receive a new record key and are retained as a new version.
    """

    batch: list[dict[str, Any]] = []
    seen: set[str] = set()

    stats = {
        "rows_read": 0,
        "rows_valid": 0,
        "rows_inserted": 0,
        "rows_updated": 0,
        "rows_skipped": 0,
    }

    def report_processing() -> None:
        if expected_rows:
            fraction = 0.32 + (
                0.58 * min(stats["rows_read"] / expected_rows, 1.0)
            )
        else:
            fraction = None

        emit_progress(
            progress_callback,
            "normalization",
            "Validating records and writing normalized data to PostgreSQL.",
            fraction,
            **stats,
        )

    def flush_batch(items: list[dict[str, Any]]) -> None:
        if not items:
            return

        now = datetime.now(UTC)
        insert_statement = insert(SourceRecord).values(items)

        statement = (
            insert_statement
            .on_conflict_do_update(
                constraint="uq_source_records_dataset_record",
                set_={
                    "record_date": insert_statement.excluded.record_date,
                    "status": insert_statement.excluded.status,
                    "last_seen_at": now,
                    "last_sync_run_id": run.id,
                },
            )
            .returning(
                SourceRecord.record_key,
                literal_column("xmax = 0").label("was_inserted"),
            )
        )

        result = db.execute(statement)

        for _, was_inserted in result.all():
            if was_inserted:
                stats["rows_inserted"] += 1
            else:
                stats["rows_updated"] += 1

    emit_progress(
        progress_callback,
        "validation",
        "Checking source schema and beginning record normalization.",
        0.32,
    )

    for record in records:
        stats["rows_read"] += 1

        payload = json_safe(record.get("payload", {}))

        if not isinstance(payload, dict) or not payload:
            stats["rows_skipped"] += 1
            continue

        record_key = stable_record_key(payload)

        if record_key in seen:
            stats["rows_skipped"] += 1
            continue

        seen.add(record_key)
        stats["rows_valid"] += 1

        now = datetime.now(UTC)

        batch.append(
            {
                "source_key": source_key,
                "dataset_key": dataset_key,
                "record_key": record_key,
                "record_date": record.get("record_date"),
                "status": record.get("status"),
                "payload": payload,
                "first_seen_at": now,
                "last_seen_at": now,
                "last_sync_run_id": run.id,
            }
        )

        if len(batch) >= settings.connector_batch_size:
            flush_batch(batch)
            batch.clear()
            db.flush()
            report_processing()

    flush_batch(batch)
    db.flush()
    report_processing()

    emit_progress(
        progress_callback,
        "storage",
        "Normalized records have been written to PostgreSQL.",
        0.92,
        **stats,
    )

    return stats


def finish_sync(
    db: Session,
    run: SourceSyncRun,
    artifact: SourceArtifact,
    stats: dict[str, int],
    metadata: dict[str, Any] | None = None,
    freshness_status: str = "current",
) -> None:
    run.status = "success"
    run.finished_at = datetime.now(UTC)
    run.artifact_id = artifact.id
    run.rows_read = stats.get("rows_read", 0)
    run.rows_valid = stats.get("rows_valid", 0)
    run.rows_inserted = stats.get("rows_inserted", 0)
    run.rows_updated = stats.get("rows_updated", 0)
    run.rows_skipped = stats.get("rows_skipped", 0)
    run.run_metadata = metadata or {}

    source = db.scalar(
        select(SourceRegistry).where(
            SourceRegistry.source_key == run.source_key
        )
    )

    if source:
        source.last_checked_at = run.finished_at
        source.last_successful_sync_at = run.finished_at
        source.freshness_status = freshness_status

    db.flush()


def fail_sync(
    db: Session,
    run: SourceSyncRun,
    error: Exception,
) -> None:
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    run.error_message = f"{type(error).__name__}: {str(error)[:4000]}"

    source = db.scalar(
        select(SourceRegistry).where(
            SourceRegistry.source_key == run.source_key
        )
    )

    if source:
        source.last_checked_at = run.finished_at

    db.flush()
