
from __future__ import annotations

import json  # noqa: F401
import os
from datetime import date, datetime
from pathlib import Path  # noqa: F401
from typing import Any

import pandas as pd
import streamlit as st

try:
    database_url = st.secrets.get("DATABASE_URL")
    if database_url:
        os.environ["DATABASE_URL"] = str(database_url)
except Exception:
    # Local development can continue using the project's .env file.
    pass

from sqlalchemy import Text, cast, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.connectors.service import (
    sync_anvisa,
    sync_conitec_dashboard,
    sync_conitec_legacy,
)
from app.db.session import SessionLocal
from app.models import (
    SourceArtifact,
    SourceRecord,
    SourceRegistry,
    SourceSyncRun,
)

st.set_page_config(
    page_title="DreamBigHealth | Market Access Intelligence",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)


DATASETS = {
    "ANVISA — Registered Medicines": {
        "dataset_key": "br_anvisa_medicines",
        "source_key": "br-anvisa-registered-medicines-csv",
        "description": (
            "Official ANVISA open dataset of registered medicines in Brazil."
        ),
        "function": sync_anvisa,
    },
    "CONITEC — Current Demand Dashboard": {
        "dataset_key": "br_conitec_dashboard_20261026",
        "source_key": "br-conitec-technologies-in-demand-xlsx-20261026",
        "description": (
            "Official CONITEC dashboard workbook covering technology demands."
        ),
        "function": sync_conitec_dashboard,
    },
    "CONITEC — Historical Demand Dataset": {
        "dataset_key": "br_conitec_legacy_csv",
        "source_key": None,
        "description": (
            "Historical CONITEC demand dataset. Retained separately and "
            "labelled stale because its published coverage is older."
        ),
        "function": sync_conitec_legacy,
    },
}


def format_datetime(value: datetime | date | None) -> str:
    if value is None:
        return "—"

    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %H:%M")

    return value.strftime("%d %b %Y")


def get_database_snapshot() -> dict[str, Any]:
    with SessionLocal() as db:
        sources = db.scalars(
            select(SourceRegistry).order_by(
                SourceRegistry.market,
                SourceRegistry.authority,
                SourceRegistry.source_name,
            )
        ).all()

        runs = db.scalars(
            select(SourceSyncRun)
            .order_by(SourceSyncRun.started_at.desc())
            .limit(100)
        ).all()

        artifacts = db.scalars(
            select(SourceArtifact)
            .order_by(SourceArtifact.created_at.desc())
            .limit(100)
        ).all()

        dataset_stats = db.execute(
            select(
                SourceRecord.dataset_key,
                func.count(SourceRecord.id).label("record_count"),
                func.max(SourceRecord.record_date).label("latest_record_date"),
                func.max(SourceRecord.last_seen_at).label("last_seen_at"),
            )
            .group_by(SourceRecord.dataset_key)
            .order_by(SourceRecord.dataset_key)
        ).all()

        total_records = db.scalar(
            select(func.count()).select_from(SourceRecord)
        ) or 0

        successful_runs = db.scalar(
            select(func.count())
            .select_from(SourceSyncRun)
            .where(SourceSyncRun.status == "success")
        ) or 0

        failed_runs = db.scalar(
            select(func.count())
            .select_from(SourceSyncRun)
            .where(SourceSyncRun.status == "failed")
        ) or 0

        return {
            "sources": sources,
            "runs": runs,
            "artifacts": artifacts,
            "dataset_stats": dataset_stats,
            "total_records": total_records,
            "successful_runs": successful_runs,
            "failed_runs": failed_runs,
        }


def get_dataset_records(
    dataset_key: str,
    search_term: str = "",
    limit: int = 100,
) -> list[SourceRecord]:
    with SessionLocal() as db:
        statement = select(SourceRecord).where(
            SourceRecord.dataset_key == dataset_key
        )

        if search_term.strip():
            statement = statement.where(
                cast(SourceRecord.payload, Text).ilike(
                    f"%{search_term.strip()}%"
                )
            )

        statement = (
            statement
            .order_by(
                SourceRecord.record_date.desc().nullslast(),
                SourceRecord.last_seen_at.desc(),
            )
            .limit(limit)
        )

        return db.scalars(statement).all()


def source_dataframe(sources: list[SourceRegistry]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Source": source.source_name,
                "Authority": source.authority,
                "Market": source.market,
                "Country": source.country_code,
                "Type": source.source_type,
                "Implementation": source.implementation_status,
                "Enabled": source.is_enabled,
                "Freshness": source.freshness_status,
                "Last Successful Sync": format_datetime(
                    source.last_successful_sync_at
                ),
                "Source URL": source.source_url,
            }
            for source in sources
        ]
    )


def run_dataframe(runs: list[SourceSyncRun]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Run ID": run.id,
                "Source Key": run.source_key,
                "Dataset": run.dataset_key,
                "Status": run.status,
                "Started": format_datetime(run.started_at),
                "Finished": format_datetime(run.finished_at),
                "Rows Read": run.rows_read,
                "Rows Valid": run.rows_valid,
                "Inserted": run.rows_inserted,
                "Updated": run.rows_updated,
                "Skipped": run.rows_skipped,
                "Error": run.error_message,
            }
            for run in runs
        ]
    )


def get_artifact_for_run(
    run_id: int,
) -> SourceArtifact | None:
    with SessionLocal() as db:
        run = db.get(SourceSyncRun, run_id)
        if not run or not run.artifact_id:
            return None
        return db.get(SourceArtifact, run.artifact_id)


st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.1rem;
        font-weight: 750;
        margin-bottom: 0;
    }
    .sub-header {
        color: #9aa4b2;
        font-size: 0.95rem;
        margin-top: 0.3rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="main-header">DreamBigHealth</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="sub-header">'
    "Market Access Intelligence | Brazil Phase 1"
    "</div>",
    unsafe_allow_html=True,
)

st.sidebar.title("Navigation")

page = st.sidebar.radio(
    "Select view",
    [
        "Executive Overview",
        "Pipeline Control",
        "Source Registry",
        "Connector Runs",
        "Data Explorer",
    ],
)

st.sidebar.divider()
st.sidebar.caption("Platform")
st.sidebar.write("Brazil — Phase 1")
st.sidebar.write("PostgreSQL connected")
st.sidebar.write(
    f"Last page refresh: {datetime.now():%d %b %Y %H:%M:%S}"
)

if st.sidebar.button("Refresh dashboard", use_container_width=True):
    st.rerun()

try:
    snapshot = get_database_snapshot()
except SQLAlchemyError as exc:
    st.error(
        "Unable to connect to the DreamBigHealth database. "
        "Check PostgreSQL availability and DATABASE_URL."
    )
    with st.expander("Technical details"):
        st.exception(exc)
    st.stop()

sources = snapshot["sources"]
runs = snapshot["runs"]
artifacts = snapshot["artifacts"]
dataset_stats = snapshot["dataset_stats"]


# ---------------------------------------------------------------------
# Executive overview
# ---------------------------------------------------------------------

if page == "Executive Overview":
    st.subheader("Executive Overview")
    st.caption(
        "Live operational view of the source registry and Brazil data ingestion."
    )

    enabled_sources = sum(
        1 for source in sources if source.is_enabled
    )
    synced_sources = sum(
        1
        for source in sources
        if source.last_successful_sync_at is not None
    )

    columns = st.columns(4)
    columns[0].metric("Registered Sources", len(sources))
    columns[1].metric("Enabled Sources", enabled_sources)
    columns[2].metric(
        "Imported Records",
        f"{snapshot['total_records']:,}",
    )
    columns[3].metric(
        "Successful Sync Runs",
        snapshot["successful_runs"],
    )

    columns = st.columns(3)
    columns[0].metric("Sources Synced", synced_sources)
    columns[1].metric("Failed Runs", snapshot["failed_runs"])
    columns[2].metric("Archived Artifacts", len(artifacts))

    st.divider()
    st.subheader("Brazil Data Connectors")

    brazil_sources = [
        source
        for source in sources
        if (source.country_code or "").upper() == "BR"
        or "brazil" in (source.market or "").casefold()
        or "brasil" in (source.market or "").casefold()
    ]

    if brazil_sources:
        st.table(
            source_dataframe(brazil_sources).drop(
                columns=["Source URL"]
            ),
        )
    else:
        st.info("No Brazil-specific sources were found.")

    st.subheader("Imported Dataset Summary")

    if dataset_stats:
        dataset_df = pd.DataFrame(
            [
                {
                    "Dataset": row.dataset_key,
                    "Records": row.record_count,
                    "Latest Record Date": format_datetime(
                        row.latest_record_date
                    ),
                    "Last Seen": format_datetime(row.last_seen_at),
                }
                for row in dataset_stats
            ]
        )
        st.table(
            dataset_df,
        )

    st.subheader("Recent Connector Activity")
    if runs:
        st.table(
            run_dataframe(runs[:10]),
        )
    else:
        st.info("No connector runs recorded yet.")


# ---------------------------------------------------------------------
# Live pipeline control
# ---------------------------------------------------------------------

elif page == "Pipeline Control":
    st.subheader("Live Data Pipeline")
    st.caption(
        "Run an official Brazil source connector and observe acquisition, "
        "archiving, validation, normalization and database storage."
    )

    selected_label = st.selectbox(
        "Select an official data source",
        list(DATASETS.keys()),
    )
    selected = DATASETS[selected_label]

    st.info(selected["description"])

    st.write(f"**Dataset key:** `{selected['dataset_key']}`")

    if selected["source_key"]:
        matching_source = next(
            (
                source
                for source in sources
                if source.source_key == selected["source_key"]
            ),
            None,
        )
    else:
        matching_source = next(
            (
                source
                for source in sources
                if source.source_url
                == __import__(
                    "app.core.config",
                    fromlist=["settings"],
                ).settings.conitec_csv_source_url
            ),
            None,
        )

    if matching_source:
        st.write(f"**Authority:** {matching_source.authority}")
        st.write(f"**Official source URL:** {matching_source.source_url}")
        if not matching_source.is_enabled:
            st.error("This source is disabled in the source registry.")
            st.stop()
    else:
        st.error("The selected source was not found in the source registry.")
        st.stop()

    st.warning(
        "Starting a pipeline run downloads or copies a source file and "
        "writes normalized records to the database. Use this control only "
        "when you intend to execute a real sync."
    )

    confirm_run = st.checkbox(
        "I understand this will execute a real source synchronization."
    )

    if st.button(
        "Start pipeline",
        type="primary",
        disabled=not confirm_run,
        
    ):
        progress_bar = st.progress(0.0)
        stage_placeholder = st.empty()
        detail_placeholder = st.empty()
        metrics_placeholder = st.empty()
        log_placeholder = st.empty()

        event_log: list[str] = []

        def on_progress(event: dict[str, Any]) -> None:
            fraction = event.get("fraction")
            if fraction is not None:
                progress_bar.progress(float(fraction))

            stage_placeholder.markdown(
                f"### {event.get('stage', 'processing').replace('_', ' ').title()}"
            )
            detail_placeholder.write(event.get("message", ""))

            if "run_id" in event:
                st.session_state["last_pipeline_run_id"] = event["run_id"]

            if "rows_read" in event:
                stats_columns = metrics_placeholder.columns(4)
                stats_columns[0].metric(
                    "Rows Read", f"{event.get('rows_read', 0):,}"
                )
                stats_columns[1].metric(
                    "Valid", f"{event.get('rows_valid', 0):,}"
                )
                stats_columns[2].metric(
                    "Inserted", f"{event.get('rows_inserted', 0):,}"
                )
                stats_columns[3].metric(
                    "Updated", f"{event.get('rows_updated', 0):,}"
                )

            if "bytes_received" in event:
                received = event.get("bytes_received") or 0
                total = event.get("total_bytes")
                if total:
                    detail_placeholder.caption(
                        f"Downloaded {received:,} of {total:,} bytes"
                    )
                else:
                    detail_placeholder.caption(
                        f"Downloaded {received:,} bytes"
                    )

            event_log.append(
                f"{datetime.now():%H:%M:%S} | "
                f"{event.get('stage')} | {event.get('message')}"
            )
            log_placeholder.code("\n".join(event_log[-12:]))

        try:
            with st.spinner("Executing the selected connector..."):
                with SessionLocal() as db:
                    result = selected["function"](
                        db,
                        progress_callback=on_progress,
                    )

            st.session_state["last_pipeline_result"] = result
            st.session_state["last_pipeline_run_id"] = result["sync_run_id"]

            progress_bar.progress(1.0)
            st.success(
                f"Pipeline completed successfully. "
                f"Run ID: #{result['sync_run_id']}"
            )

            result_columns = st.columns(4)
            result_columns[0].metric(
                "Rows Read", f"{result['rows_read']:,}"
            )
            result_columns[1].metric(
                "Valid", f"{result['rows_valid']:,}"
            )
            result_columns[2].metric(
                "Inserted", f"{result['rows_inserted']:,}"
            )
            result_columns[3].metric(
                "Updated", f"{result['rows_updated']:,}"
            )

            st.metric("Skipped duplicates / invalid", result["rows_skipped"])

            st.write("**Archived file:**")
            st.text(result["artifact_path"])

            st.write("**SHA-256:**")
            st.text(result["sha256"])

        except Exception as exc:
            st.error(f"Pipeline failed: {exc}")
            st.exception(exc)

        st.info(
            "Refresh the dashboard or open Connector Runs and Data Explorer "
            "to inspect the committed database results."
        )

    last_result = st.session_state.get("last_pipeline_result")
    if last_result:
        st.divider()
        st.subheader("Last Pipeline Result")
        st.text(json.dumps(last_result, indent=2, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------

elif page == "Source Registry":
    st.subheader("Structured Source Registry")
    st.caption(
        "Canonical inventory of regulatory, HTA and market-access sources."
    )

    markets = sorted(
        {source.market for source in sources if source.market}
    )
    authorities = sorted(
        {source.authority for source in sources if source.authority}
    )

    col1, col2, col3 = st.columns(3)

    selected_market = col1.selectbox("Market", ["All"] + markets)
    selected_authority = col2.selectbox(
        "Authority",
        ["All"] + authorities,
    )
    selected_status = col3.selectbox(
        "Enabled status",
        ["All", "Enabled", "Disabled"],
    )

    filtered = sources

    if selected_market != "All":
        filtered = [
            source for source in filtered
            if source.market == selected_market
        ]

    if selected_authority != "All":
        filtered = [
            source for source in filtered
            if source.authority == selected_authority
        ]

    if selected_status == "Enabled":
        filtered = [source for source in filtered if source.is_enabled]
    elif selected_status == "Disabled":
        filtered = [source for source in filtered if not source.is_enabled]

    st.write(f"Showing **{len(filtered)}** source records.")

    if filtered:
        st.table(
            source_dataframe(filtered).drop(columns=["Source URL"]),
        )

        with st.expander("Inspect source details"):
            source_names = {
                source.source_name: source for source in filtered
            }
            selected_name = st.selectbox(
                "Select source",
                list(source_names.keys()),
            )
            source = source_names[selected_name]

            st.write(f"**Authority:** {source.authority}")
            st.write(f"**Market:** {source.market}")
            st.write(f"**Source key:** `{source.source_key}`")
            st.write(f"**Source type:** {source.source_type}")
            st.write(
                f"**Implementation:** "
                f"{source.implementation_status or 'Not specified'}"
            )
            st.write(f"**Freshness:** {source.freshness_status}")
            st.write(
                f"**Update frequency:** "
                f"{source.update_frequency or 'Not specified'}"
            )
            st.write(f"**Coverage:** {source.coverage_notes or 'Not specified'}")
            st.write(f"**Limitations:** {source.limitations or 'Not specified'}")
            st.write(f"**Source URL:** {source.source_url}")

            if source.documentation_url:
                st.write(f"**Documentation:** {source.documentation_url}")


# ---------------------------------------------------------------------
# Connector runs
# ---------------------------------------------------------------------

elif page == "Connector Runs":
    st.subheader("Connector Execution History")
    st.caption(
        "Run-level ingestion counts, execution status and artifact traceability."
    )

    if runs:
        run_df = run_dataframe(runs)
        statuses = ["All"] + sorted(
            run_df["Status"].dropna().unique().tolist()
        )

        selected_status = st.selectbox("Status filter", statuses)
        if selected_status != "All":
            run_df = run_df[run_df["Status"] == selected_status]

        st.table(
            run_df,
        )

        run_ids = [run.id for run in runs]
        selected_run_id = st.selectbox("Inspect run", run_ids)
        selected_run = next(
            run for run in runs if run.id == selected_run_id
        )

        columns = st.columns(4)
        columns[0].metric("Rows Read", selected_run.rows_read or 0)
        columns[1].metric("Valid", selected_run.rows_valid or 0)
        columns[2].metric("Inserted", selected_run.rows_inserted or 0)
        columns[3].metric("Updated", selected_run.rows_updated or 0)

        st.write(f"**Dataset:** {selected_run.dataset_key}")
        st.write(f"**Source key:** `{selected_run.source_key}`")
        st.write(f"**Status:** {selected_run.status}")
        st.write(f"**Skipped:** {selected_run.rows_skipped or 0}")

        if selected_run.error_message:
            st.error(selected_run.error_message)

        st.text(json.dumps(selected_run.run_metadata or {}, indent=2, ensure_ascii=False, default=str))

        if selected_run.artifact_id:
            artifact = next(
                (
                    item for item in artifacts
                    if item.id == selected_run.artifact_id
                ),
                None,
            )

            if artifact:
                st.subheader("Archived Source Artifact")
                st.write(f"**Filename:** {artifact.filename}")
                st.write(f"**SHA-256:** `{artifact.sha256}`")
                st.write(f"**Size:** {artifact.size_bytes:,} bytes")
                st.write(f"**Path:** `{artifact.storage_path}`")
                st.write(f"**Source URL:** {artifact.source_url}")
    else:
        st.info("No connector executions recorded.")


# ---------------------------------------------------------------------
# Data explorer
# ---------------------------------------------------------------------

elif page == "Data Explorer":
    st.subheader("Normalized Data Explorer")
    st.caption(
        "Search and inspect actual normalized records stored in PostgreSQL."
    )

    dataset_keys = sorted({row.dataset_key for row in dataset_stats})

    if not dataset_keys:
        st.info("No imported datasets are available.")
        st.stop()

    selected_dataset = st.selectbox("Dataset", dataset_keys)
    search_term = st.text_input(
        "Search records",
        placeholder="Search technology, medicine, indication or status...",
    )
    record_limit = st.select_slider(
        "Maximum records",
        options=[25, 50, 100, 250, 500],
        value=100,
    )

    try:
        records = get_dataset_records(
            selected_dataset,
            search_term,
            record_limit,
        )
    except SQLAlchemyError as exc:
        st.error("Unable to retrieve records.")
        st.exception(exc)
        st.stop()

    st.write(f"Displaying **{len(records)}** matching records.")

    if records:
        rows = []

        for record in records:
            rows.append(
                {
                    "Record Key": record.record_key,
                    "Record Date": format_datetime(record.record_date),
                    "Status": record.status,
                    "Last Seen": format_datetime(record.last_seen_at),
                    "Source Key": record.source_key,
                }
            )

        st.table(
            pd.DataFrame(rows),
        )

        with st.expander("Inspect full source record"):
            options = {
                f"{record.id} — {record.record_key[:12]}": record
                for record in records
            }
            selected_record_label = st.selectbox(
                "Select record",
                list(options.keys()),
            )
            record = options[selected_record_label]

            st.write(f"**Dataset:** {record.dataset_key}")
            st.write(f"**Record key:** `{record.record_key}`")
            st.write(f"**Record date:** {format_datetime(record.record_date)}")
            st.write(f"**Status:** {record.status}")
            st.write(f"**Last seen:** {format_datetime(record.last_seen_at)}")
            st.text(json.dumps(record.payload or {}, indent=2, ensure_ascii=False, default=str))
    else:
        st.info("No matching records found.")


st.divider()
st.caption(
    "DreamBigHealth | Market Access Intelligence | Brazil Phase 1 | "
    "Connected PostgreSQL data"
)
