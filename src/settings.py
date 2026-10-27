"""Configuración tipada de mIA.

Todas las variables usan el prefijo ``MIA_`` y ``__`` para anidar grupos, por
ejemplo ``MIA_LLM__MODEL`` o ``MIA_VOICE__API_KEY``. En Azure los secretos
llegan como variables de entorno referenciadas desde Key Vault; en local se
leen de ``.env``.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    DEV = "dev"
    PRODUCTION = "production"


class AuthMode(StrEnum):
    DEV = "dev"
    """Identidad fija configurable. Solo para local, test y dev."""
    EASYAUTH = "easyauth"
    """Identidad inyectada por la autenticación integrada de Azure (Easy Auth)."""


class LLMProviderName(StrEnum):
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    FAKE = "fake"


class VoiceProviderName(StrEnum):
    ELEVENLABS = "elevenlabs"
    NONE = "none"


class LLMSettings(BaseModel):
    provider: LLMProviderName = LLMProviderName.OPENAI
    api_key: SecretStr = SecretStr("")
    model: str = "gpt-4.1-mini"
    base_url: str = "https://api.openai.com/v1"
    """En Azure OpenAI: ``https://<recurso>.openai.azure.com/openai/v1``."""
    timeout_seconds: float = 45.0
    max_output_tokens: int = 1200
    max_tool_rounds: int = 4


class VoiceSettings(BaseModel):
    provider: VoiceProviderName = VoiceProviderName.NONE
    api_key: SecretStr = SecretStr("")
    voice_id: str = ""
    model_id: str = "eleven_flash_v2_5"
    output_format: str = "mp3_44100_128"
    base_url: str = "https://api.elevenlabs.io/v1"
    timeout_seconds: float = 20.0
    max_chars: int = 600
    cache_entries: int = 256


class AuthSettings(BaseModel):
    mode: AuthMode = AuthMode.DEV
    dev_user_id: str = "dev-user"
    dev_display_name: str = "Usuario de desarrollo"
    dev_email: str = "dev@localhost"
    dev_roles: list[str] = Field(default_factory=lambda: ["mia.admin"])


class SharePointSettings(BaseModel):
    """Acceso de aplicación (certificado) al sitio de RRHH."""

    tenant_id: str = ""
    client_id: str = ""
    cert_thumbprint: str = ""
    cert_pfx_path: Path | None = None
    cert_pfx_base64: SecretStr | None = None
    """Alternativa a la ruta: el PFX en base64 (así llega desde Key Vault en Azure)."""
    cert_pfx_password: SecretStr = SecretStr("")
    cert_pem_path: Path | None = None
    host: str = ""
    rrhh_site_url: str = ""
    timeout_seconds: float = 30.0
    page_size: int = 2000
    max_retries: int = 5
    concurrency: int = 4

    @property
    def configured(self) -> bool:
        has_cert = bool(self.cert_pfx_path or self.cert_pfx_base64 or self.cert_pem_path)
        return bool(self.tenant_id and self.client_id and self.cert_thumbprint and self.rrhh_site_url and has_cert)


class DataSettings(BaseModel):
    pseudonym_key: SecretStr = SecretStr("solo-para-desarrollo-local")
    """Clave HMAC para seudonimizar identificadores personales (DNI/NIE). En Azure, desde Key Vault."""
    full_sync_hour: int = 3
    """Hora local de la sincronización completa diaria (detecta borrados y corrige derivas)."""


class FrontendSettings(BaseModel):
    """El frontend actual se sirve desde su ubicación, sin copiarlo."""

    legacy_html: Path | None = None
    assets_dir: Path | None = None


class ObservabilitySettings(BaseModel):
    log_level: str = "INFO"
    log_json: bool = True
    applicationinsights_connection_string: SecretStr | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MIA_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Environment.LOCAL
    host: str = "127.0.0.1"
    port: int = 5001
    compat_port: int | None = None
    """Puerto adicional (5002) para el frontend actual en local, que espera el gateway ahí."""
    timezone: str = "Europe/Madrid"
    database_url: str = "postgresql+asyncpg://mia:mia@localhost:5432/mia"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"])
    history_turns: int = 12

    llm: LLMSettings = Field(default_factory=LLMSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    frontend: FrontendSettings = Field(default_factory=FrontendSettings)
    sharepoint: SharePointSettings = Field(default_factory=SharePointSettings)
    data: DataSettings = Field(default_factory=DataSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

    @model_validator(mode="after")
    def _fail_closed_in_production(self) -> Settings:
        if self.environment is Environment.PRODUCTION and self.auth.mode is AuthMode.DEV:
            raise ValueError(
                "MIA_AUTH__MODE=dev no está permitido en producción: usa 'easyauth' hasta que se implemente Entra ID."
            )
        if (
            self.environment is Environment.PRODUCTION
            and self.data.pseudonym_key.get_secret_value() == "solo-para-desarrollo-local"
        ):
            raise ValueError("En producción MIA_DATA__PSEUDONYM_KEY debe venir de Key Vault.")
        if self.environment is Environment.PRODUCTION and self.llm.provider is LLMProviderName.FAKE:
            raise ValueError("El proveedor LLM 'fake' no está permitido en producción.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
