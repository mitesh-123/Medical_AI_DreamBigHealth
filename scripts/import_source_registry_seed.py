import argparse
import json
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.db.session import SessionLocal
from app.models import SourceRegistry

DEFAULT_FILE = Path("data/exports/source_registry_seed.json")


def convert_value(column, value):
    if value is None:
        return None

    if isinstance(column.type, datetime.__class__):
        return value

    if column.name in {"verified_on", "data_as_of"}:
        return date.fromisoformat(value) if isinstance(value, str) else value

    if column.name in {
        "last_checked_at",
        "last_successful_sync_at",
        "created_at",
        "updated_at",
    }:
        return datetime.fromisoformat(value) if isinstance(value, str) else value

    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import Source Registry records into the configured database."
    )
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    args = parser.parse_args()

    if not args.file.exists():
        raise FileNotFoundError(f"Seed file not found: {args.file}")

    with args.file.open("r", encoding="utf-8") as file:
        records = json.load(file)

    if not isinstance(records, list) or not records:
        raise ValueError("Seed file must contain a non-empty JSON list.")

    keys = [item.get("source_key") for item in records]

    if any(not key for key in keys):
        raise ValueError("Every record must have a source_key.")

    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate source_key values found in seed file.")

    table = SourceRegistry.__table__
    valid_columns = {column.name: column for column in table.columns}

    prepared = []
    for item in records:
        unknown = set(item) - set(valid_columns)
        if unknown:
            raise ValueError(f"Unexpected columns in seed file: {sorted(unknown)}")

        row = {
            name: convert_value(valid_columns[name], value)
            for name, value in item.items()
        }

        required = {
            "source_key",
            "source_name",
            "authority",
            "market",
            "source_type",
            "source_url",
            "freshness_status",
            "source_status",
            "is_enabled",
            "catalog_sections",
            "source_metadata",
        }

        missing = [
            name for name in required
            if row.get(name) is None
        ]

        if missing:
            raise ValueError(
                f"{row.get('source_key')}: missing required values {missing}"
            )

        prepared.append(row)

    with SessionLocal.begin() as db:
        statement = insert(table).values(prepared)

        update_values = {
            column.name: getattr(statement.excluded, column.name)
            for column in table.columns
            if column.name not in {"id", "source_key", "created_at"}
        }

        statement = statement.on_conflict_do_update(
            index_elements=[table.c.source_key],
            set_=update_values,
        )

        result = db.execute(statement)

        db.execute(
            text_sequence_sync()
        )

        total = db.scalar(
            select(func.count()).select_from(SourceRegistry)
        )

    print(f"Seed records processed: {len(prepared)}")
    print(f"Database source registry count: {total}")
    print(f"Database affected rows: {result.rowcount}")


def text_sequence_sync():
    from sqlalchemy import text

    return text(
        """
        SELECT setval(
            pg_get_serial_sequence('source_registry', 'id'),
            COALESCE((SELECT MAX(id) FROM source_registry), 1),
            EXISTS (SELECT 1 FROM source_registry)
        )
        """
    )


if __name__ == "__main__":
    main()