
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "DreamBigHealth Market Access Intelligence"
    app_env: str = "development"
    debug: bool = True

    database_url: str = (
        "postgresql+psycopg://market_access:local_dev_password"
        "@localhost:5433/dreambighealth"
    )

    raw_data_dir: Path = PROJECT_ROOT / "data" / "raw"
    processed_data_dir: Path = PROJECT_ROOT / "data" / "processed"
    export_dir: Path = PROJECT_ROOT / "data" / "exports"

    log_level: str = "INFO"

    anvisa_source_url: str = (
        "https://dados.anvisa.gov.br/dados/DADOS_ABERTOS_MEDICAMENTOS.csv"
    )

    conitec_csv_source_url: str = (
        "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/"
        "CONITEC/csv/Controle_de_Demandas_da_Conitec.csv.zip"
    )

    conitec_dashboard_source_url: str = (
        "https://www.gov.br/conitec/pt-br/midias/dados-em-excel/"
        "painel_demandas_conitec_20261026.xlsx/@@download/file"
    )
    
    connector_timeout_seconds: int = 120
    connector_batch_size: int = 1000


settings = Settings()
