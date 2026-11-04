import json
from pathlib import Path

from app.db.session import SessionLocal
from app.models import SourceRegistry

OUTPUT_FILE = Path("data/exports/source_registry_seed.json")


def main() -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        records = db.query(SourceRegistry).order_by(
            SourceRegistry.source_key
        ).all()

        exported = []

        for record in records:
            item = {
                column.name: getattr(record, column.name)
                for column in SourceRegistry.__table__.columns
                if column.name != "id"
            }
            exported.append(item)

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            exported,
            file,
            ensure_ascii=False,
            indent=2,
            default=lambda value: value.isoformat(),
        )

    print(f"Exported records: {len(exported)}")
    print(f"Output file: {OUTPUT_FILE.resolve()}")

    if len(exported) != 55:
        print(
            "WARNING: Expected 55 source records. "
            "Check the local database before importing."
        )


if __name__ == "__main__":
    main()