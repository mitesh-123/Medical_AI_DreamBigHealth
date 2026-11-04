
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import SourceRegistry
from app.services.source_registry_importer import (
    as_text,
    build_source_key,
    get_sheet_rows,
)

EXPECTED_COUNTS = {
    "Code_Ready": 30,
    "HTA_Market_Access": 24,
}

REQUIRED_FIELDS = (
    "source_key",
    "source_name",
    "authority",
    "market",
    "source_url",
    "source_type",
)

EXPECTED_TOTAL = 55


def expected_sources(workbook_path: Path) -> dict[str, dict]:
    """Build expected canonical source identities from both workbook sheets."""

    definitions = {
        "Code_Ready": {
            "required": {
                "Market",
                "Authority",
                "Dataset / List",
                "Code URL",
            },
            "market": "Market",
            "authority": "Authority",
            "name": "Dataset / List",
            "url": "Code URL",
        },
        "HTA_Market_Access": {
            "required": {
                "Market",
                "HTA / Market-Access Body",
                "Decision List / Repository",
                "Code / Source URL",
            },
            "market": "Market",
            "authority": "HTA / Market-Access Body",
            "name": "Decision List / Repository",
            "url": "Code / Source URL",
        },
    }

    expected: dict[str, dict] = {}

    for sheet_name, definition in definitions.items():
        dataframe = get_sheet_rows(
            workbook_path,
            sheet_name,
            definition["required"],
        )

        valid_rows = 0

        for _, row in dataframe.iterrows():
            market = as_text(row.get(definition["market"]))
            authority = as_text(row.get(definition["authority"]))
            source_name = as_text(row.get(definition["name"]))
            source_url = as_text(row.get(definition["url"]))

            if not all([market, authority, source_name, source_url]):
                continue

            valid_rows += 1

            key = build_source_key(
                market,
                authority,
                source_name,
                source_url,
            )

            if key not in expected:
                expected[key] = {
                    "source_key": key,
                    "source_name": source_name,
                    "authority": authority,
                    "market": market,
                    "source_url": source_url,
                    "catalog_sections": set(),
                }

            expected[key]["catalog_sections"].add(sheet_name)

        expected[sheet_name] = {
            "valid_rows": valid_rows,
        }

    return expected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit the imported DreamBigHealth source registry."
    )

    parser.add_argument(
        "--file",
        type=Path,
        default=(
            Path("data/raw/inbox")
            / "Global_Authorization_HTA_Market_Access_APIs Doc3 supp.xlsx"
        ),
    )

    args = parser.parse_args()

    if not args.file.exists():
        print(f"ERROR: Workbook not found: {args.file}")
        return 1

    expected = expected_sources(args.file)

    workbook_expected = {
        key: value
        for key, value in expected.items()
        if isinstance(value, dict) and "source_key" in value
    }

    sheet_counts = {
        sheet: expected[sheet]["valid_rows"]
        for sheet in EXPECTED_COUNTS
    }

    errors: list[str] = []
    warnings: list[str] = []

    for sheet, expected_count in EXPECTED_COUNTS.items():
        actual_count = sheet_counts[sheet]

        if actual_count != expected_count:
            errors.append(
                f"{sheet}: expected {expected_count} valid rows, "
                f"found {actual_count}."
            )

    with SessionLocal() as db:
        records = db.scalars(
            select(SourceRegistry).order_by(
                SourceRegistry.market,
                SourceRegistry.authority,
                SourceRegistry.source_name,
            )
        ).all()

        by_key = {
            record.source_key: record
            for record in records
        }

        if len(by_key) != len(records):
            errors.append("Duplicate source_key values found.")

        missing_keys = sorted(
            set(workbook_expected) - set(by_key)
        )

        unexpected_workbook_keys = sorted(
            set(by_key) & set(workbook_expected)
        )

        for key in missing_keys:
            errors.append(
                f"Workbook source missing from database: {key}"
            )

        field_mismatches = []

        for key in unexpected_workbook_keys:
            expected_record = workbook_expected[key]
            actual_record = by_key[key]

            for field in (
                "source_name",
                "authority",
                "market",
                "source_url",
            ):
                expected_value = expected_record[field]
                actual_value = getattr(actual_record, field)

                if expected_value != actual_value:
                    field_mismatches.append(
                        {
                            "source_key": key,
                            "field": field,
                            "expected": expected_value,
                            "actual": actual_value,
                        }
                    )

            expected_sections = expected_record["catalog_sections"]
            actual_sections = set(actual_record.catalog_sections or [])

            if not expected_sections.issubset(actual_sections):
                errors.append(
                    f"Catalog section mismatch for {key}: "
                    f"expected {sorted(expected_sections)}, "
                    f"found {sorted(actual_sections)}."
                )

        for mismatch in field_mismatches:
            errors.append(
                "Field mismatch: "
                + json.dumps(mismatch, ensure_ascii=False)
            )

        missing_fields = []

        for record in records:
            for field in REQUIRED_FIELDS:
                value = getattr(record, field)

                if value is None or (
                    isinstance(value, str) and not value.strip()
                ):
                    missing_fields.append(
                        {
                            "source_key": record.source_key,
                            "field": field,
                        }
                    )

            parsed_url = urlparse(record.source_url or "")

            if parsed_url.scheme not in {"http", "https"}:
                errors.append(
                    f"Invalid source URL for {record.source_key}: "
                    f"{record.source_url}"
                )

            if not record.update_frequency:
                warnings.append(
                    f"Update frequency not specified: "
                    f"{record.authority} / {record.source_name}"
                )

        for item in missing_fields:
            errors.append(
                f"Missing required field: {item['field']} "
                f"for {item['source_key']}"
            )

        part_a_count = sum(
            "Code_Ready" in (record.catalog_sections or [])
            for record in records
        )

        part_b_count = sum(
            "HTA_Market_Access" in (record.catalog_sections or [])
            for record in records
        )

        brazil_anvisa = db.scalar(
            select(SourceRegistry).where(
                SourceRegistry.source_key
                == "br-anvisa-registered-medicines-csv"
            )
        )

        brazil_dashboard = db.scalar(
            select(SourceRegistry).where(
                SourceRegistry.source_key
                == "br-conitec-technologies-in-demand-xlsx-20261026"
            )
        )

        conitec_legacy = db.scalar(
            select(SourceRegistry).where(
                SourceRegistry.source_url
                == settings.conitec_csv_source_url
            )
        )

        if len(records) != EXPECTED_TOTAL:
            errors.append(
                f"Expected {EXPECTED_TOTAL} total records, "
                f"found {len(records)}."
            )

        if part_a_count != EXPECTED_COUNTS["Code_Ready"]:
            errors.append(
                f"Part A membership expected 30, found {part_a_count}."
            )

        if part_b_count != EXPECTED_COUNTS["HTA_Market_Access"]:
            errors.append(
                f"Part B membership expected 24, found {part_b_count}."
            )

        if not brazil_anvisa:
            errors.append("Brazil ANVISA source is missing.")

        if not brazil_dashboard:
            errors.append("New CONITEC dashboard source is missing.")

        if not conitec_legacy:
            errors.append("Historical CONITEC CSV source is missing.")
        elif conitec_legacy.freshness_status != "stale":
            errors.append(
                "Historical CONITEC CSV must be marked stale."
            )

        if brazil_dashboard and (
            brazil_dashboard.implementation_status
            != "NEEDS_SCHEMA_VALIDATION"
        ):
            errors.append(
                "New CONITEC dashboard must remain marked "
                "NEEDS_SCHEMA_VALIDATION until its workbook is validated."
            )

        report = {
            "result": "PASS" if not errors else "FAIL",
            "total_database_records": len(records),
            "workbook": {
                "Code_Ready_rows": sheet_counts["Code_Ready"],
                "HTA_Market_Access_rows": sheet_counts[
                    "HTA_Market_Access"
                ],
                "unique_workbook_sources": len(workbook_expected),
                "merged_workbook_definitions": (
                    sum(
                        len(value["catalog_sections"]) > 1
                        for value in workbook_expected.values()
                    )
                ),
            },
            "database": {
                "part_a_membership": part_a_count,
                "part_b_membership": part_b_count,
                "brazil_anvisa_present": brazil_anvisa is not None,
                "conitec_legacy_present": conitec_legacy is not None,
                "conitec_legacy_freshness": (
                    conitec_legacy.freshness_status
                    if conitec_legacy
                    else None
                ),
                "conitec_dashboard_present": (
                    brazil_dashboard is not None
                ),
                "conitec_dashboard_status": (
                    brazil_dashboard.implementation_status
                    if brazil_dashboard
                    else None
                ),
            },
            "errors": errors,
            "warnings": warnings,
        }

    print(json.dumps(report, indent=2, ensure_ascii=False))

    if errors:
        return 1

    print("\nSOURCE REGISTRY AUDIT PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
