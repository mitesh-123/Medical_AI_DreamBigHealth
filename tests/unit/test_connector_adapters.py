import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.connectors.anvisa.adapter import (
    iter_anvisa_records,
    parse_month_year,
)
from app.connectors.conitec.dashboard_xlsx import (
    EXPECTED_COLUMNS as DASHBOARD_COLUMNS,
)
from app.connectors.conitec.dashboard_xlsx import (
    iter_dashboard_records,
)
from app.connectors.conitec.legacy_csv import (
    iter_legacy_conitec_records,
    parse_date,
)


def test_anvisa_month_year_expiry() -> None:
    assert parse_month_year("122030").isoformat() == "2030-12-01"
    assert parse_month_year("132030") is None
    assert parse_month_year(None) is None


def test_anvisa_schema_validation(tmp_path: Path) -> None:
    file_path = tmp_path / "invalid.csv"
    file_path.write_text("WRONG;COLUMNS\nA;B\n", encoding="cp1252")

    with pytest.raises(ValueError, match="schema mismatch"):
        list(iter_anvisa_records(file_path))


def test_conitec_dashboard_schema_and_null_dates(tmp_path: Path) -> None:
    file_path = tmp_path / "dashboard.xlsx"

    row = {column: None for column in DASHBOARD_COLUMNS}
    row.update(
        {
            "Origem": "Demanda externa",
            "Data protocolo": "2026-10-14",
            "Tipo de Tecnologia": "Medicamento",
            "Tema da Saúde": "Oncologia",
            "Demandante": "Demandante de teste",
            "Nome da tecnologia": "Tecnologia de teste",
            "Status": "Em análise",
            "Indicação": "Indicação de teste",
            "Motivo da solicitação": "Motivo de teste",
            "Data decisão": None,
        }
    )

    pd.DataFrame([row]).to_excel(
        file_path,
        sheet_name="Planilha1",
        index=False,
    )

    records = list(iter_dashboard_records(file_path))

    assert len(records) == 1
    assert records[0]["status"] == "Em análise"
    assert records[0]["record_date"].isoformat() == "2026-10-14"
    assert records[0]["payload"]["Data decisão"] is None
    assert records[0]["payload"]["data_decisao_iso"] is None


def test_legacy_conitec_zip_adapter(tmp_path: Path) -> None:
    file_path = tmp_path / "legacy.zip"
    csv_content = (
        "origem;data_protocolo;tipo_tecnologia;tema_saude;demandante;"
        "nome_tecnologia;status;indicacao;motivo_solicitacao;data_decisao\n"
        "Externa;01/02/2025;Medicamento;Oncologia;Teste;"
        "Tecnologia X;Concluída;Indicação X;Motivo X;23/06/2025\n"
    )

    with zipfile.ZipFile(file_path, "w") as archive:
        archive.writestr("demandas.csv", csv_content.encode("utf-8"))

    records = list(iter_legacy_conitec_records(file_path))

    assert len(records) == 1
    assert records[0]["payload"]["nome_tecnologia"] == "Tecnologia X"
    assert records[0]["record_date"].isoformat() == "2025-02-01"
    
def test_legacy_conitec_parses_date_and_timestamp_formats():
    assert parse_date("11/06/2025") == date(2025, 6, 11)
    assert parse_date("2025-06-11") == date(2025, 6, 11)
    assert parse_date("11/06/2025 00:00:00") == date(2025, 6, 11)
    assert parse_date("2025-06-11T00:00:00") == date(2025, 6, 11)
    assert parse_date("") is None
    assert parse_date(None) is None

def test_legacy_conitec_parses_actual_source_timestamp():
    assert parse_date("2014/05/05 00:00:00.000") == date(2014, 5, 5)
    assert parse_date("2014/07/01 00:00:00.000") == date(2014, 7, 1)
    assert parse_date("2024/11/13 00:00:00.000") == date(2024, 11, 13)