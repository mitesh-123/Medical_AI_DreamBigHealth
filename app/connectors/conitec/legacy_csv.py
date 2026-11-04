
import csv
import io
import zipfile
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

EXPECTED_COLUMNS = (
    "origem",
    "data_protocolo",
    "tipo_tecnologia",
    "tema_saude",
    "demandante",
    "nome_tecnologia",
    "status",
    "indicacao",
    "motivo_solicitacao",
    "data_decisao",
)

DATE_FORMATS = (
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d/%m/%y",
    # Actual CONITEC legacy CSV formats:
    "%Y/%m/%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S.%f",
)


def parse_date(value: str | date | datetime | None) -> date | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    value = str(value).strip()
    if not value:
        return None

    # Handle ISO timestamps, including timezone offsets.
    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).date()
    except ValueError:
        pass

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    return None


def iter_legacy_conitec_records(path: Path) -> Iterator[dict]:
    with zipfile.ZipFile(path) as archive:
        candidates = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".csv")
            and not name.startswith("__MACOSX/")
        ]

        if len(candidates) != 1:
            raise ValueError(
                "Expected exactly one CSV inside the CONITEC ZIP; "
                f"found {len(candidates)}."
            )

        with archive.open(candidates[0]) as raw:
            text = io.TextIOWrapper(
                raw,
                encoding="utf-8-sig",
                newline="",
            )
            reader = csv.DictReader(text, delimiter=";")

            actual_columns = {
                (column or "").strip()
                for column in (reader.fieldnames or [])
            }
            missing = set(EXPECTED_COLUMNS) - actual_columns

            if missing:
                raise ValueError(
                    "Legacy CONITEC CSV schema mismatch. Missing: "
                    + ", ".join(sorted(missing))
                )

            for row in reader:
                payload = {
                    column: (row.get(column) or "").strip() or None
                    for column in EXPECTED_COLUMNS
                }

                if not any(payload.values()):
                    continue

                yield {
                    "record_date": parse_date(
                        payload["data_protocolo"]
                    ),
                    "status": payload["status"],
                    "payload": payload,
                }
