import csv
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

EXPECTED_COLUMNS = {
    "TIPO_PRODUTO",
    "NOME_PRODUTO",
    "DATA_FINALIZACAO_PROCESSO",
    "CATEGORIA_REGULATORIA",
    "NUMERO_REGISTRO_PRODUTO",
    "DATA_VENCIMENTO_REGISTRO",
    "NUMERO_PROCESSO",
    "CLASSE_TERAPEUTICA",
    "EMPRESA_DETENTORA_REGISTRO",
    "SITUACAO_REGISTRO",
    "PRINCIPIO_ATIVO",
}


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_date(value: str | None) -> date | None:
    value = clean_text(value)
    if not value:
        return None

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    return None


def parse_month_year(value: str | None) -> date | None:
    """
    ANVISA registration expiry is MMYYYY, e.g. 122030.
    Represent it as the first day of the month and retain the
    original source value in the payload.
    """
    value = clean_text(value)
    if not value:
        return None

    if len(value) == 6 and value.isdigit():
        month = int(value[:2])
        year = int(value[2:])
        if 1 <= month <= 12 and 1900 <= year <= 2200:
            return date(year, month, 1)

    return None


def iter_anvisa_records(path: Path) -> Iterator[dict]:
    with path.open(
        "r",
        encoding="cp1252",
        newline="",
    ) as file:
        reader = csv.DictReader(file, delimiter=";")

        actual = set(reader.fieldnames or [])
        missing = EXPECTED_COLUMNS - actual
        if missing:
            raise ValueError(
                "ANVISA CSV schema mismatch. Missing columns: "
                + ", ".join(sorted(missing))
            )

        for row in reader:
            payload = {
                column: clean_text(row.get(column))
                for column in EXPECTED_COLUMNS
            }

            if not any(payload.values()):
                continue

            yield {
                "record_date": parse_date(
                    payload["DATA_FINALIZACAO_PROCESSO"]
                ),
                "status": payload["SITUACAO_REGISTRO"],
                "payload": {
                    **payload,
                    "data_finalizacao_process_date": (
                        parse_date(payload["DATA_FINALIZACAO_PROCESSO"])
                    ),
                    "data_vencimento_registro_month": (
                        parse_month_year(payload["DATA_VENCIMENTO_REGISTRO"])
                    ),
                    "is_active_registration": (
                        (payload["SITUACAO_REGISTRO"] or "").casefold()
                        in {"ativo", "active"}
                    ),
                },
            }