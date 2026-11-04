import argparse
import json
from pathlib import Path

from app.connectors.service import (
    sync_anvisa,
    sync_conitec_dashboard,
    sync_conitec_legacy,
)
from app.db.session import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync DreamBigHealth Brazil regulatory and HTA sources."
    )
    parser.add_argument(
        "source",
        choices=["anvisa", "conitec-dashboard", "conitec-legacy", "all"],
    )
    parser.add_argument(
        "--anvisa-file",
        type=Path,
        default=None,
        help="Optional local ANVISA CSV. Otherwise downloads the official CSV.",
    )
    parser.add_argument(
        "--dashboard-file",
        type=Path,
        default=Path(
            "data/raw/inbox/Painel_Demandas_Conitec_20261026.xlsx"
        ),
        help="Local CONITEC dashboard Excel. Pass an empty path only if downloading.",
    )
    parser.add_argument(
        "--legacy-file",
        type=Path,
        default=Path(
            "data/raw/inbox/Controle_de_Demandas_da_Conitec.csv.zip"
        ),
        help="Local historical CONITEC ZIP. Pass an empty path only if downloading.",
    )
    parser.add_argument(
        "--download-dashboard",
        action="store_true",
        help="Download dashboard from the official URL instead of local file.",
    )
    parser.add_argument(
        "--download-legacy",
        action="store_true",
        help="Download historical CONITEC ZIP instead of local file.",
    )

    args = parser.parse_args()

    dashboard_file = None if args.download_dashboard else args.dashboard_file
    legacy_file = None if args.download_legacy else args.legacy_file

    results = []

    with SessionLocal() as db:
        if args.source in {"anvisa", "all"}:
            results.append(sync_anvisa(db, args.anvisa_file))

        if args.source in {"conitec-dashboard", "all"}:
            results.append(
                sync_conitec_dashboard(db, dashboard_file)
            )

        if args.source in {"conitec-legacy", "all"}:
            results.append(
                sync_conitec_legacy(db, legacy_file)
            )

    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()