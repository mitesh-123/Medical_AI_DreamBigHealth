
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import pandas as pd

EXPECTED_COLUMNS = {
    "Origem",
    "Data protocolo",
    "Tipo de Tecnologia",
    "Tema da Saúde",
    "Demandante",
    "Nome da tecnologia",
    "Status",
    "Indicação",
    "Motivo da solicitação",
    "Data decisão",
}

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y",
    "%d/%m/%Y %H:%M:%S",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S.%f",
)


def clean_value(value):
    if pd.isna(value):
        return None

    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    value = str(value).strip()
    return value or None


def parse_date(value) -> date | None:
    if value is None:
        return None

    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date()

    if isinstance(value, date):
        return value

    if pd.isna(value):
        return None

    value = str(value).strip()
    if not value:
        return None

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


def iter_dashboard_records(path: Path) -> Iterator[dict]:
    workbook = pd.ExcelFile(path, engine="openpyxl")

    if "Planilha1" not in workbook.sheet_names:
        raise ValueError(
            "CONITEC dashboard schema mismatch: expected sheet 'Planilha1'; "
            f"found {workbook.sheet_names}."
        )

    dataframe = pd.read_excel(
        path,
        sheet_name="Planilha1",
        engine="openpyxl",
        dtype=object,
    )

    actual = set(dataframe.columns)
    missing = EXPECTED_COLUMNS - actual

    if missing:
        raise ValueError(
            "CONITEC dashboard schema mismatch. Missing columns: "
            + ", ".join(sorted(missing))
        )

    for _, row in dataframe.iterrows():
        protocol_date = parse_date(row["Data protocolo"])
        decision_date = parse_date(row["Data decisão"])

        payload = {
            column: clean_value(row[column])
            for column in EXPECTED_COLUMNS
        }

        if not any(payload.values()):
            continue

        yield {
            "record_date": protocol_date,
            "status": payload["Status"],
            "payload": {
                **payload,
                "data_protocolo_iso": protocol_date,
                "data_decisao_iso": decision_date,
            },
        }
