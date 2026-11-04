
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.anvisa.adapter import iter_anvisa_records
from app.connectors.base import (
    ProgressCallback,
    create_sync_run,
    download_source,
    emit_progress,
    fail_sync,
    finish_sync,
    register_artifact,
    upsert_records,
)
from app.connectors.conitec.dashboard_xlsx import iter_dashboard_records
from app.connectors.conitec.legacy_csv import iter_legacy_conitec_records
from app.core.config import settings
from app.models import SourceRegistry, SourceSyncRun

ANVISA_SOURCE_KEY = "br-anvisa-registered-medicines-csv"
CONITEC_DASHBOARD_SOURCE_KEY = (
    "br-conitec-technologies-in-demand-xlsx-20261026"
)

EXPECTED_SOURCE_ROWS = {
    "br_anvisa_medicines": 228869,
    "br_conitec_dashboard_20261026": 1261,
    "br_conitec_legacy_csv": 1128,
}


def find_legacy_source_key(db: Session) -> str:
    source = db.scalar(
        select(SourceRegistry).where(
            SourceRegistry.source_url == settings.conitec_csv_source_url
        )
    )

    if not source:
        raise ValueError(
            "Legacy CONITEC source URL was not found in source_registry. "
            "Run the accepted source registry import first."
        )

    return source.source_key


def run_connector(
    db: Session,
    source_key: str,
    dataset_key: str,
    url: str,
    filename: str,
    adapter: Callable[[Path], Iterator[dict]],
    local_path: Path | None = None,
    freshness_status: str = "current",
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    run = create_sync_run(db, source_key, dataset_key)
    run_id = run.id
    db.commit()

    try:
        emit_progress(
            progress_callback,
            "starting",
            f"Created connector execution #{run_id}.",
            0.01,
            run_id=run_id,
            source_key=source_key,
            dataset_key=dataset_key,
        )

        raw_path, download_metadata = download_source(
            url=url,
            source_key=source_key,
            filename=filename,
            local_path=local_path,
            progress_callback=progress_callback,
        )

        emit_progress(
            progress_callback,
            "archive",
            "Calculating SHA-256 and registering the raw source artifact.",
            0.34,
            artifact_path=str(raw_path),
        )

        artifact = register_artifact(
            db,
            source_key,
            raw_path,
            download_metadata,
        )
        db.flush()

        emit_progress(
            progress_callback,
            "validation",
            "Starting source adapter and schema validation.",
            0.40,
            artifact_path=str(raw_path),
            sha256=artifact.sha256,
        )

        stats = upsert_records(
            db=db,
            run=run,
            source_key=source_key,
            dataset_key=dataset_key,
            records=adapter(raw_path),
            progress_callback=progress_callback,
            expected_rows=EXPECTED_SOURCE_ROWS.get(dataset_key),
        )

        finish_sync(
            db=db,
            run=run,
            artifact=artifact,
            stats=stats,
            metadata={
                "raw_file": str(raw_path),
                "sha256": artifact.sha256,
                "source_url": download_metadata["source_url"],
                "content_type": download_metadata.get("content_type"),
                "size_bytes": download_metadata["size_bytes"],
            },
            freshness_status=freshness_status,
        )

        db.commit()

        result = {
            "source_key": source_key,
            "dataset_key": dataset_key,
            "sync_run_id": run_id,
            "status": "success",
            **stats,
            "artifact_path": str(raw_path),
            "sha256": artifact.sha256,
        }

        emit_progress(
            progress_callback,
            "complete",
            f"Connector execution #{run_id} completed successfully.",
            1.0,
            **result,
        )

        return result

    except Exception as exc:
        db.rollback()

        failed_run = db.get(SourceSyncRun, run_id)
        if failed_run:
            fail_sync(db, failed_run, exc)
            db.commit()

        emit_progress(
            progress_callback,
            "failed",
            f"Connector execution #{run_id} failed: {exc}",
            1.0,
            run_id=run_id,
            error=str(exc),
        )
        raise


def sync_anvisa(
    db: Session,
    local_file: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    return run_connector(
        db=db,
        source_key=ANVISA_SOURCE_KEY,
        dataset_key="br_anvisa_medicines",
        url=settings.anvisa_source_url,
        filename="DADOS_ABERTOS_MEDICAMENTOS.csv",
        adapter=iter_anvisa_records,
        local_path=local_file,
        progress_callback=progress_callback,
    )


def sync_conitec_dashboard(
    db: Session,
    local_file: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    return run_connector(
        db=db,
        source_key=CONITEC_DASHBOARD_SOURCE_KEY,
        dataset_key="br_conitec_dashboard_20261026",
        url=settings.conitec_dashboard_source_url,
        filename="Painel_Demandas_Conitec.xlsx",
        adapter=iter_dashboard_records,
        local_path=local_file,
        progress_callback=progress_callback,
    )


def sync_conitec_legacy(
    db: Session,
    local_file: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    source_key = find_legacy_source_key(db)

    return run_connector(
        db=db,
        source_key=source_key,
        dataset_key="br_conitec_legacy_csv",
        url=settings.conitec_csv_source_url,
        filename="Controle_de_Demandas_da_Conitec.csv.zip",
        adapter=iter_legacy_conitec_records,
        local_path=local_file,
        freshness_status="stale",
        progress_callback=progress_callback,
    )
