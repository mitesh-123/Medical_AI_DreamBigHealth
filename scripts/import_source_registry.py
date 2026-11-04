
import argparse
import json
from pathlib import Path

from app.db.session import SessionLocal
from app.services.source_registry_importer import import_source_catalog


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import the DreamBigHealth global source catalog."
    )

    parser.add_argument(
        "--file",
        type=Path,
        default=(
            Path("data/raw/inbox")
            / "Global_Authorization_HTA_Market_Access_APIs Doc3 supp.xlsx"
        ),
        help="Path to the client's source catalog workbook.",
    )

    args = parser.parse_args()

    with SessionLocal.begin() as db:
        result = import_source_catalog(
            db=db,
            workbook_path=args.file,
        )

    print(
        json.dumps(
            result,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
