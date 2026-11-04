
import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import SourceRegistry

COUNTRY_CODES = {
    "Brazil": "BR",
    "United States": "US",
    "Canada": "CA",
    "France": "FR",
    "Germany": "DE",
    "United Kingdom": "GB",
    "Japan": "JP",
    "China": "CN",
    "Spain": "ES",
    "Singapore": "SG",
    "Netherlands": "NL",
    "Saudi Arabia": "SA",
    "United Arab Emirates": "AE",
}


def clean_value(value: Any) -> Any:
    """Convert pandas and Excel values into JSON/database-safe values."""

    if value is None:
        return None

    if pd.isna(value):
        return None

    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if hasattr(value, "item"):
        value = value.item()

    if isinstance(value, str):
        value = value.strip()
        return value or None

    return value


def as_text(value: Any) -> str | None:
    """Convert a non-empty value to a trimmed string."""

    cleaned = clean_value(value)

    if cleaned is None:
        return None

    return str(cleaned).strip()


def parse_date(value: Any) -> date | None:
    """Parse an Excel date without guessing invalid date formats."""

    cleaned = clean_value(value)

    if cleaned is None:
        return None

    if isinstance(cleaned, date):
        return cleaned

    try:
        return date.fromisoformat(str(cleaned)[:10])
    except ValueError:
        return None


def slugify(value: str) -> str:
    """Create a stable, readable identifier component."""

    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def build_source_key(
    market: str,
    authority: str,
    source_name: str,
    source_url: str,
) -> str:
    """
    Build a deterministic key for the same source across workbook sheets.

    The URL is included so that different datasets from one authority
    remain separate registry entries.
    """

    identity = "|".join(
        [
            market.strip().lower(),
            authority.strip().lower(),
            source_name.strip().lower(),
            source_url.strip().rstrip("/").lower(),
        ]
    )

    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]

    readable = slugify(
        f"{market}-{authority}-{source_name}"
    )[:145]

    return f"{readable}-{digest}"


def classify_source(decision_layer: str | None) -> str:
    """Classify a catalog source into a broad platform data category."""

    value = (decision_layer or "").lower()

    if "regulatory" in value or "authorization" in value:
        return "regulatory"

    if "hta" in value or "reimbursement" in value or "coverage" in value:
        return "hta"

    if "price" in value:
        return "pricing"

    return "other"


def get_sheet_rows(
    workbook_path: Path,
    sheet_name: str,
    required_columns: set[str],
) -> pd.DataFrame:
    """Read a catalog sheet and validate its expected column names."""

    dataframe = pd.read_excel(
        workbook_path,
        sheet_name=sheet_name,
        header=2,
        engine="openpyxl",
    )

    dataframe.columns = [
        str(column).strip()
        for column in dataframe.columns
    ]

    missing = required_columns.difference(dataframe.columns)

    if missing:
        raise ValueError(
            f"Sheet '{sheet_name}' is missing columns: "
            f"{sorted(missing)}"
        )

    return dataframe


def upsert_source(
    db: Session,
    payload: dict[str, Any],
    catalog_section: str,
) -> tuple[SourceRegistry, bool]:
    """Insert a source or update the existing canonical source record."""

    source = db.scalar(
        select(SourceRegistry).where(
            SourceRegistry.source_key == payload["source_key"]
        )
    )

    created = source is None

    if created:
        source = SourceRegistry(
            source_key=payload["source_key"],
            source_name=payload["source_name"],
            authority=payload["authority"],
            market=payload["market"],
            source_url=payload["source_url"],
        )
        db.add(source)

    update_fields = [
        "source_name",
        "authority",
        "market",
        "country_code",
        "region",
        "decision_layer",
        "source_type",
        "access_type",
        "implementation_status",
        "http_method",
        "source_url",
        "companion_url",
        "data_format",
        "authentication",
        "retrieval_strategy",
        "decision_content",
        "update_frequency",
        "coverage_notes",
        "limitations",
        "documentation_url",
        "verification_notes",
        "verified_on",
    ]

    for field in update_fields:
        value = payload.get(field)

        if value is not None:
            setattr(source, field, value)

    sections = list(source.catalog_sections or [])

    if catalog_section not in sections:
        sections.append(catalog_section)

    source.catalog_sections = sections

    metadata = dict(source.source_metadata or {})
    metadata[catalog_section] = payload["source_metadata"]
    source.source_metadata = metadata

    if not source.freshness_status:
        source.freshness_status = "not_checked"

    db.flush()

    return source, created


def import_code_ready(
    db: Session,
    workbook_path: Path,
) -> dict[str, int]:
    """Import Part A: Code_Ready."""

    dataframe = get_sheet_rows(
        workbook_path,
        "Code_Ready",
        {
            "Region",
            "Market",
            "Decision Layer",
            "Authority",
            "Dataset / List",
            "Access Type",
            "Implementation Status",
            "HTTP Method",
            "Code URL",
        },
    )

    inserted = 0
    updated = 0
    skipped = 0

    for _, row in dataframe.iterrows():
        market = as_text(row.get("Market"))
        authority = as_text(row.get("Authority"))
        source_name = as_text(row.get("Dataset / List"))
        source_url = as_text(row.get("Code URL"))

        if not all([market, authority, source_name, source_url]):
            skipped += 1
            continue

        payload = {
            "source_key": build_source_key(
                market,
                authority,
                source_name,
                source_url,
            ),
            "source_name": source_name,
            "authority": authority,
            "market": market,
            "country_code": COUNTRY_CODES.get(market),
            "region": as_text(row.get("Region")),
            "decision_layer": as_text(row.get("Decision Layer")),
            "source_type": classify_source(
                as_text(row.get("Decision Layer"))
            ),
            "access_type": as_text(row.get("Access Type")),
            "implementation_status": as_text(
                row.get("Implementation Status")
            ),
            "http_method": as_text(row.get("HTTP Method")),
            "source_url": source_url,
            "companion_url": as_text(row.get("Example Request")),
            "data_format": as_text(row.get("Format")),
            "authentication": as_text(row.get("Authentication")),
            "retrieval_strategy": as_text(
                row.get("Retrieval / Pagination")
            ),
            "decision_content": as_text(row.get("Decision Content")),
            "update_frequency": as_text(row.get("Update Frequency")),
            "coverage_notes": as_text(row.get("Coverage Notes")),
            "limitations": None,
            "documentation_url": as_text(
                row.get("Official Documentation")
            ),
            "verification_notes": as_text(
                row.get("Verification Notes")
            ),
            "verified_on": parse_date(row.get("Verified On")),
            "source_metadata": {
                str(key): clean_value(value)
                for key, value in row.to_dict().items()
            },
        }

        _, created = upsert_source(
            db,
            payload,
            "Code_Ready",
        )

        if created:
            inserted += 1
        else:
            updated += 1

    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
    }


def import_hta_market_access(
    db: Session,
    workbook_path: Path,
) -> dict[str, int]:
    """Import Part B: HTA_Market_Access."""

    dataframe = get_sheet_rows(
        workbook_path,
        "HTA_Market_Access",
        {
            "Region",
            "Market",
            "HTA / Market-Access Body",
            "Role in Decision Pathway",
            "Decision List / Repository",
            "Access Type",
            "API / Automation Status",
            "Code / Source URL",
        },
    )

    inserted = 0
    updated = 0
    skipped = 0

    for _, row in dataframe.iterrows():
        market = as_text(row.get("Market"))
        authority = as_text(row.get("HTA / Market-Access Body"))
        source_name = as_text(row.get("Decision List / Repository"))
        source_url = as_text(row.get("Code / Source URL"))

        if not all([market, authority, source_name, source_url]):
            skipped += 1
            continue

        decision_layer = as_text(
            row.get("Role in Decision Pathway")
        )

        payload = {
            "source_key": build_source_key(
                market,
                authority,
                source_name,
                source_url,
            ),
            "source_name": source_name,
            "authority": authority,
            "market": market,
            "country_code": COUNTRY_CODES.get(market),
            "region": as_text(row.get("Region")),
            "decision_layer": decision_layer,
            "source_type": classify_source(decision_layer),
            "access_type": as_text(row.get("Access Type")),
            "implementation_status": as_text(
                row.get("API / Automation Status")
            ),
            "http_method": as_text(row.get("HTTP Method")),
            "source_url": source_url,
            "companion_url": as_text(
                row.get("Example or Companion URL")
            ),
            "data_format": as_text(row.get("Format")),
            "authentication": as_text(row.get("Authentication")),
            "retrieval_strategy": as_text(
                row.get("Recommended Retrieval Strategy")
            ),
            "decision_content": as_text(
                row.get("Key Fields / Content")
            ),
            "update_frequency": None,
            "coverage_notes": None,
            "limitations": as_text(
                row.get("Limitations / Market-Access Interpretation")
            ),
            "documentation_url": as_text(
                row.get("Official Documentation")
            ),
            "verification_notes": None,
            "verified_on": parse_date(row.get("Verified On")),
            "source_metadata": {
                str(key): clean_value(value)
                for key, value in row.to_dict().items()
            },
        }

        _, created = upsert_source(
            db,
            payload,
            "HTA_Market_Access",
        )

        if created:
            inserted += 1
        else:
            updated += 1

    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
    }


def seed_brazil_sources(db: Session) -> dict[str, str]:
    """
    Add Brazil sources that require explicit treatment outside
    the two original catalog sheets.
    """

    anvisa = {
        "source_key": "br-anvisa-registered-medicines-csv",
        "source_name": "Registered medicines in Brazil - open data",
        "authority": "ANVISA",
        "market": "Brazil",
        "country_code": "BR",
        "region": "Latin America",
        "decision_layer": "Regulatory authorization",
        "source_type": "regulatory",
        "access_type": "Bulk CSV",
        "implementation_status": "READY - dataset validated",
        "http_method": "GET",
        "source_url": settings.anvisa_source_url,
        "companion_url": None,
        "data_format": "CSV; Windows-1252; semicolon-delimited",
        "authentication": "No authentication required",
        "retrieval_strategy": (
            "Download the complete CSV, preserve the original file, "
            "validate the schema and normalize records."
        ),
        "decision_content": (
            "Product name, active ingredient, registration number, "
            "process number, holder, regulatory category, status, "
            "therapeutic class and registration dates."
        ),
        "update_frequency": "Monthly according to ANVISA documentation",
        "coverage_notes": (
            "Official ANVISA registered-medicines dataset. "
            "The supplied CSV was inspected; latest process "
            "finalization date observed was 2026-10-08."
        ),
        "limitations": (
            "The catalog workbook's Gated_and_Gaps sheet did not "
            "identify a verified stable product API. This entry "
            "uses the validated bulk CSV, not an API."
        ),
        "documentation_url": (
            "https://dados.anvisa.gov.br/dados/"
            "Documentacao_e_Dicionario_de_Dados_Registros_Validos_"
            "Medicamento_V1.pdf"
        ),
        "verification_notes": (
            "CSV structure, delimiter and encoding inspected. "
            "Exact duplicate rows must be handled during normalization."
        ),
        "verified_on": date(2026, 11, 3),
        "source_metadata": {
            "origin": "Brazil source addition",
            "catalog_gap": (
                "ANVISA appears in Gated_and_Gaps, not Code_Ready."
            ),
        },
    }

    upsert_source(db, anvisa, "Brazil_MVP_Additions")

    conitec_csv_url = settings.conitec_csv_source_url

    legacy = db.scalar(
        select(SourceRegistry).where(
            SourceRegistry.source_url == conitec_csv_url
        )
    )

    if legacy:
        legacy.data_as_of = date(2025, 6, 23)
        legacy.freshness_status = "stale"
        legacy.verification_notes = (
            "Historical baseline. Supplied CSV contains 1,128 records; "
            "latest decision date observed was 2025-06-23. Official "
            "dataset temporal coverage is through the first half of 2025. "
            "Do not represent this as current 2026 HTA data."
        )
        legacy.source_metadata = {
            **(legacy.source_metadata or {}),
            "Brazil_MVP_Additions": {
                "origin": "Supplied CONITEC CSV",
                "role": "Historical baseline",
                "latest_decision_date_observed": "2025-06-23",
                "official_resource_last_update": "2025-09-09",
            },
        }

    dashboard = {
        "source_key": "br-conitec-technologies-in-demand-xlsx-20261026",
        "source_name": "Technologies in demand - official dashboard Excel",
        "authority": "CONITEC / Ministry of Health",
        "market": "Brazil",
        "country_code": "BR",
        "region": "Latin America",
        "decision_layer": "HTA / SUS incorporation decision tracking",
        "source_type": "hta",
        "access_type": "Bulk Excel download",
        "implementation_status": "NEEDS_SCHEMA_VALIDATION",
        "http_method": "GET",
        "source_url": settings.conitec_dashboard_source_url,
        "companion_url": (
            "https://www.gov.br/conitec/pt-br/assuntos/"
            "avaliacao-de-tecnologias-em-saude/tecnologias-demandadas"
        ),
        "data_format": "XLSX",
        "authentication": "No authentication required",
        "retrieval_strategy": (
            "Download the official workbook, inspect sheets and columns, "
            "validate dates and identifiers, then implement a dedicated "
            "Excel adapter. Do not merge it with the older CSV schema."
        ),
        "decision_content": (
            "Technologies demanded for evaluation, process status and "
            "SUS incorporation decision information; exact fields pending "
            "workbook inspection."
        ),
        "update_frequency": (
            "Official dashboard publication; actual resource cadence "
            "must be verified."
        ),
        "coverage_notes": (
            "Official Technologies in demand page modified 2026-10-26. "
            "The linked workbook has not yet been schema-validated."
        ),
        "limitations": (
            "Do not ingest or claim record-level coverage until the "
            "downloaded workbook's structure and dates are verified."
        ),
        "documentation_url": (
            "https://www.gov.br/conitec/pt-br/assuntos/"
            "avaliacao-de-tecnologias-em-saude/tecnologias-demandadas"
        ),
        "verification_notes": (
            "Official page and download link identified from the supplied "
            "source. Excel content and schema remain unverified."
        ),
        "verified_on": date(2026, 11, 3),
        "source_metadata": {
            "origin": "Brazil source addition",
            "publication_page_modified": "2026-10-26",
            "schema_validation": "pending",
        },
    }

    upsert_source(
        db,
        dashboard,
        "Brazil_MVP_Additions",
    )

    return {
        "anvisa": "br-anvisa-registered-medicines-csv",
        "conitec_legacy": (
            "legacy CSV found and marked stale"
            if legacy
            else "legacy CSV not found in catalog; verify workbook URL"
        ),
        "conitec_dashboard": (
            "br-conitec-technologies-in-demand-xlsx-20261026"
        ),
    }


def import_source_catalog(
    db: Session,
    workbook_path: Path,
) -> dict[str, Any]:
    """Import both client catalog sections and seed Brazil sources."""

    if not workbook_path.exists():
        raise FileNotFoundError(
            f"Source catalog workbook not found: {workbook_path}"
        )

    code_ready_stats = import_code_ready(db, workbook_path)

    hta_stats = import_hta_market_access(db, workbook_path)

    brazil_sources = seed_brazil_sources(db)

    db.flush()

    return {
        "Code_Ready": code_ready_stats,
        "HTA_Market_Access": hta_stats,
        "Brazil_sources": brazil_sources,
    }
