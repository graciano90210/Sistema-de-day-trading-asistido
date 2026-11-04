"""Configuración: secretos desde .env, parámetros desde config/*.yaml, guard paper-only."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"

# Única URL de trading permitida en todo el proyecto (regla 1).
PAPER_TRADING_URL = "https://paper-api.alpaca.markets"


class LiveTradingForbidden(RuntimeError):
    """Se lanza ante cualquier intento de usar un endpoint que no sea paper."""


def assert_paper_url(url: str) -> str:
    """Devuelve la URL si es exactamente la de paper trading; si no, aborta."""
    if url.rstrip("/") != PAPER_TRADING_URL:
        raise LiveTradingForbidden(
            f"URL de trading no permitida: {url!r}. Este proyecto solo opera en {PAPER_TRADING_URL}."
        )
    return PAPER_TRADING_URL


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    alpaca_api_key: SecretStr | None = None
    alpaca_secret_key: SecretStr | None = None
    sec_user_agent: str | None = None

    def require_sec_user_agent(self) -> str:
        if not self.sec_user_agent or "@" not in self.sec_user_agent:
            raise RuntimeError('Falta SEC_USER_AGENT en .env (formato: "NombreApp tu@email.com").')
        return self.sec_user_agent

    def require_alpaca(self) -> tuple[str, str]:
        if not self.alpaca_api_key or not self.alpaca_secret_key:
            raise RuntimeError(
                "Faltan ALPACA_API_KEY / ALPACA_SECRET_KEY. Copia .env.example a .env y rellénalo "
                "con las keys de tu cuenta PAPER."
            )
        return self.alpaca_api_key.get_secret_value(), self.alpaca_secret_key.get_secret_value()


class DataConfig(BaseModel):
    feed: str = "sip"
    adjustment: str = "raw"
    history_start: date = date(2024, 11, 1)
    history_end: date | None = None
    max_requests_per_minute: int = 180
    max_retries: int = 5


class AppConfig(BaseModel):
    database_path: Path = Path("data/market.duckdb")
    reports_dir: Path = Path("reports")
    duckdb_memory_limit: str = "1GB"
    data: DataConfig = DataConfig()

    @property
    def db_path(self) -> Path:
        p = self.database_path
        return p if p.is_absolute() else ROOT / p

    @property
    def reports_path(self) -> Path:
        p = self.reports_dir
        return p if p.is_absolute() else ROOT / p


def load_config(path: Path | None = None) -> AppConfig:
    path = path or CONFIG_DIR / "settings.yaml"
    raw = yaml.safe_load(path.read_text()) or {}
    return AppConfig.model_validate(raw)


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text()) or {}


def load_universe(path: Path | None = None) -> list[str]:
    """Lista de símbolos única y ordenada según aparece en universe.yaml."""
    path = path or CONFIG_DIR / "universe.yaml"
    raw = yaml.safe_load(path.read_text()) or {}
    symbols: list[str] = []
    for group in raw.values():
        for s in group or []:
            s = str(s).strip().upper()
            if s and s not in symbols:
                symbols.append(s)
    return symbols
