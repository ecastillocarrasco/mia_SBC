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
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
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
    ENTRA = "entra"
    """Valida el access token (JWT) de Microsoft Entra ID en cada petición: firma, emisor,
    audiencia y expiración contra las claves públicas del tenant (JWKS), y lee los app roles
    del token. Página de login real: el front-end hace el flujo con MSAL.js; mIA solo valida."""


class LLMProviderName(StrEnum):
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    FAKE = "fake"


class ModelTier(StrEnum):
    """Niveles de modelo configurables (Bloque II, Fase F). BALANCED usa ``LLMSettings.model`` —el
    mismo modelo que ya usa toda la conversación general, GPT-4.1 mini por defecto— así que no pasar
    ningún nivel explícito preserva exactamente el comportamiento anterior a esta fase."""

    FAST = "fast"
    BALANCED = "balanced"
    ADVANCED = "advanced"


class VoiceProviderName(StrEnum):
    ELEVENLABS = "elevenlabs"
    NONE = "none"


class LLMSettings(BaseModel):
    provider: LLMProviderName = LLMProviderName.OPENAI
    api_key: SecretStr = SecretStr("")
    model: str = "gpt-4.1-mini"
    """Nivel BALANCED (predeterminado) — ver ``ModelTier``."""
    model_fast: str = "gpt-4.1-nano"
    """Nivel FAST: tareas ligeras/baratas donde no hace falta el modelo por defecto."""
    model_advanced: str = "gpt-4.1"
    """Nivel ADVANCED: análisis o narrativa compleja que justifique el coste mayor."""
    base_url: str = "https://api.openai.com/v1"
    """En Azure OpenAI: ``https://<recurso>.openai.azure.com/openai/v1``."""
    timeout_seconds: float = 45.0
    max_output_tokens: int = 1200
    max_tool_rounds: int = 8
    turn_budget_seconds: float = 120.0
    """Tiempo máximo de un turno antes de dejar de llamar a herramientas y contestar con lo que haya (evita los
    «timed out» de las consultas encadenadas)."""
    web_search: bool = True
    """Búsqueda web del proveedor para consultas generales (tiempo, actualidad). Si el proveedor no la
    admite, se desactiva sola."""


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
    entra_tenant_id: str = ""
    """El tenant de Entra ID: fija el emisor esperado (issuer) del token."""
    entra_client_id: str = ""
    """Client ID de la API CV-SunsetBeachClub: audiencia del token recibido y cliente confidencial para OBO."""
    entra_web_client_id: str = ""
    """Client ID público de la app de login del frontend web (mia_Login)."""
    entra_desktop_client_id: str = ""
    """Client ID público de la app de login de Windows (mia_Login_Desktop)."""
    entra_role_claim: str = "roles"
    """El claim del token donde vienen los app roles (p. ej. «mia.rrhh»): por defecto, «roles»."""
    entra_scope: str = ""
    """Scope que los clientes web y escritorio piden a la API (api://<client-id>/access_as_user)."""


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
    portal_site_url: str = ""
    """Sitio del portal corporativo (maestro TipoDocumento). Vacío = esa fuente no se sincroniza."""
    timeout_seconds: float = 30.0
    page_size: int = 2000
    max_retries: int = 5
    concurrency: int = 4

    @property
    def app_credentials_configured(self) -> bool:
        has_cert = bool(self.cert_pfx_path or self.cert_pfx_base64 or self.cert_pem_path)
        return bool(self.tenant_id and self.client_id and self.cert_thumbprint and has_cert)

    @property
    def configured(self) -> bool:
        """SharePoint necesita, además de las credenciales, su sitio de RRHH."""
        return self.app_credentials_configured and bool(self.rrhh_site_url)


class DataSettings(BaseModel):
    pseudonym_key: SecretStr = SecretStr("solo-para-desarrollo-local")
    """Clave HMAC para seudonimizar identificadores personales (DNI/NIE). En Azure, desde Key Vault."""
    full_sync_hour: int = 3
    stale_after_minutes: int = 30
    exclude_name_patterns: list[str] = Field(default_factory=lambda: ["^test", "^tezt"])
    """Expresiones regulares (sobre el nombre, sin tildes ni mayúsculas) de cuentas que NO son personas reales, p. ej.
    las de prueba: no se sincronizan y no cuentan en ningún total. Para más: MIA_DATA__EXCLUDE_NAME_PATTERNS."""
    content_enabled: bool = True
    """Lectura en el momento del contenido de nóminas y documentos (con permiso propio y auditoría)."""
    """A partir de cuántos minutos sin sincronizar avisa mIA de que los datos pueden no estar al día."""
    """Hora local de la sincronización completa diaria (detecta borrados y corrige derivas)."""
    index_sensitive_content: bool = False
    """Activa la indexación persistente (texto + fragmentos + embeddings, igual que los CVs) del
    contenido de nóminas y de documentos firmados (``MIA_DATA__INDEX_SENSITIVE_CONTENT=true``). Por
    defecto ``False``. Decisión explícita y ya tomada: con esto activo, ``Permission.NOMINAS_IMPORTES``
    y la regla FIR-001 dejan de significar "nunca se guarda" — el contenido pasa a extraerse,
    fragmentarse y persistirse para búsqueda semántica, igual que ya ocurre con los CVs. La lectura en
    el momento (``leer_documento``, importes de nómina) sigue existiendo sin cambios; esto es una vía
    ADICIONAL, no una sustitución."""


ALL_DOMAINS = (
    "empleados",
    "turnos",
    "fichajes",
    "vacaciones",
    "curriculums",
    "correo",
    "nominas",
    "documentos",
    "trabajo_temporal",
    "analitica",
    "informes",
    "newsletter",
)
"""Dominios de RRHH y de otros módulos que también sincronizan listas de SharePoint (p. ej.
Community/Newsletter): un único interruptor de sincronización, reutilizado — ver
``mia.ingestion.definitions.all_sources``."""


class DomainSettings(BaseModel):
    enabled: list[str] = Field(default_factory=lambda: list(ALL_DOMAINS))
    """Interruptor por dominio: si uno falla con datos reales se desactiva sin afectar al resto."""


class NoticiasSettings(BaseModel):
    """Noticias corporativas y de grupo (Sunset Beach Club / Grupo FBD): fuentes públicas externas,
    sin datos de empleados. Interruptor independiente del resto de dominios (``DomainSettings``
    es específico de RRHH) porque consulta sitios de terceros fuera del control de mIA."""

    enabled: bool = True


class MailSettings(BaseModel):
    """Acceso a Correo con buzón por usuario en producción."""

    mailbox: str = ""
    mailbox_source: Literal["configured", "user"] = "configured"
    """«configured»: el buzón de MIA_MAIL__MAILBOX (desarrollo). «user»: el de la cuenta con la que inicia sesión
    cada usuario (MSAL/Entra ID)."""
    max_messages: int = 50
    drafts_enabled: bool = True
    send_enabled: bool = False
    """Enviar exige además confirmación explícita del usuario en la conversación."""


class CurriculumSettings(BaseModel):
    embedding_model: str = "text-embedding-3-small"
    index_batch: int = 200
    """CVs nuevos o modificados que se indexan por ejecución de la sincronización."""
    max_file_mb: int = 15


class PrivacyGatewaySettings(BaseModel):
    enabled: bool = False
    """Activa la protección real (análisis Presidio + seudonimización) en el punto único de salida al LLM
    (``MIA_PRIVACY_GATEWAY__ENABLED=true``). Con False, el gateway sigue envolviendo arquitectónicamente
    a cualquier LLMProvider (no hay bypass posible), pero actúa como paso directo sin coste: así el
    despliegue inicial no cambia el comportamiento de ninguna ruta existente hasta validarlo por etapas."""
    default_policy: str = "standard"
    """Perfil de política por defecto cuando el dominio/herramienta no especifica uno: strict | standard |
    aggregated | public."""
    vault_key: SecretStr = SecretStr("")
    """Clave para cifrar el Token Vault (Fernet). En Azure, desde Key Vault. Vacía solo en local/test."""
    vault_ttl_seconds: int = 900
    """Caducidad de cada entrada del Token Vault: una vez pasado, el token ya no se puede restaurar."""
    spacy_model: str = "es_core_news_lg"
    fail_open: bool = False
    """Si el motor Presidio falla (modelo no cargado, excepción interna), True dejaría pasar la llamada sin
    protección. SIEMPRE debe ser False salvo en depuración local explícita: es la política de fallo seguro."""


class AttachmentSettings(BaseModel):
    enabled: bool = False
    """Activa la funcionalidad de adjuntos (``MIA_ATTACHMENTS__ENABLED=true``)."""
    max_files: int = 10
    max_file_mb: int = 25
    retention_hours: int = 24
    temp_path: Path = Path("data/attachments")
    vision_enabled: bool = True
    """Permite usar Vision del LLM para imágenes y PDFs escaneados."""
    temp_rag_enabled: bool = False
    """Chunking + recuperación semántica para documentos grandes (futuro)."""


class ReportSettings(BaseModel):
    directory: Path = Path("informes")
    backend: Literal["local", "azure_blob"] = "local"
    azure_account_url: str | None = None
    azure_container: str = "informes"
    logo_path: Path | None = None
    """Logo corporativo para la plantilla de informes (antes MIA_SBC_LOGO_PATH)."""
    ttl_hours: int = 24
    max_rows: int = 5000


class FrontendSettings(BaseModel):
    """El frontend actual se sirve desde su ubicación, sin copiarlo."""

    legacy_html: Path | None = None
    assets_dir: Path | None = None


class ObservabilitySettings(BaseModel):
    log_level: str = "INFO"
    log_json: bool = True
    applicationinsights_connection_string: SecretStr | None = None


class JobsSettings(BaseModel):
    enabled: bool = False
    """Activa el worker en segundo plano de informes masivos (``MIA_JOBS__ENABLED=true``)."""
    poll_interval_seconds: float = 5.0
    """Espera entre sondeos cuando no hay trabajos pendientes (``MIA_JOBS__POLL_INTERVAL_SECONDS``)."""
    lease_seconds: int = 300
    """Tiempo máximo que un worker retiene un trabajo antes de que otro pueda reclamarlo tras un
    bloqueo/caída (``MIA_JOBS__LEASE_SECONDS``)."""
    allow_sensitive_async: bool = False
    """Permite encolar y EJECUTAR trabajos en segundo plano que exigen un permiso sensible
    (``NOMINAS_IMPORTES``). Por defecto ``False``: no existe en este sistema ninguna fuente de
    autorización que se pueda consultar en vivo desde el worker (los tres proveedores de identidad
    — dev/EasyAuth/Entra ID — solo entregan roles dentro de una petición HTTP real; el trabajo en
    segundo plano no tiene ninguna), así que los permisos capturados al encolar podrían haber quedado
    obsoletos cuando el worker ejecuta. Mantener esto en ``False`` bloquea de forma segura esa ruta
    sensible hasta que exista un control verificable equivalente (``MIA_JOBS__ALLOW_SENSITIVE_ASYNC``)."""


class DiagnosticsSettings(BaseModel):
    enabled: bool = False
    """Activa captura de trazas, endpoints y panel (``MIA_DIAGNOSTICS__ENABLED=true``)."""
    retention_hours: int = 24
    """Horas que se conservan las trazas en memoria (``MIA_DIAGNOSTICS__RETENTION_HOURS``)."""
    max_traces: int = 5000
    """Máximo de trazas en memoria (``MIA_DIAGNOSTICS__MAX_TRACES``)."""
    mask_pii: bool = False
    """Enmascara nombres/IDs/correos en las trazas (``MIA_DIAGNOSTICS__MASK_PII``)."""
    admin_users: list[str] = Field(default_factory=list)
    """Emails autorizados a entrar al panel (``MIA_DIAGNOSTICS__ADMIN_USERS``). Se usan como
    "usuario" del Basic Auth del panel -- no son roles ni permisos de la app, es una lista
    cerrada aparte, deliberadamente independiente de ``Permission``/Entra ID: el panel sirve
    `Authorization: Bearer`, que un navegador nunca puede adjuntar en una navegación directa de
    página, así que necesita un esquema que el navegador sí sepa negociar solo (Basic Auth)."""
    admin_password: SecretStr = SecretStr("")
    """Contraseña compartida del Basic Auth del panel (``MIA_DIAGNOSTICS__ADMIN_PASSWORD``), igual
    para los usuarios de ``admin_users``. Vacía por defecto -- con diagnósticos activos, el panel
    debe quedar inaccesible hasta que se fije explícitamente."""


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

    @field_validator("compat_port", mode="before")
    @classmethod
    def _empty_compat_port(cls, value: object) -> object:
        """``MIA_COMPAT_PORT=`` (vacío) desactiva el segundo puerto, p. ej. para convivir con el sistema anterior."""
        return None if isinstance(value, str) and not value.strip() else value

    """Puerto adicional (5002) para el frontend actual en local, que espera el gateway ahí."""
    timezone: str = "Europe/Madrid"
    database_url: str = "postgresql+asyncpg://mia:mia@localhost:5432/mia"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"])
    history_turns: int = 8
    """Turnos (mensajes individuales, no pares) que se reenvían al LLM en cada petición. Antes 20:
    sin límite de tokens, solo de cantidad, cada turno podía sumar decenas de miles de tokens de
    historial por sí solo. La continuidad semántica real («y de esos cuántos...») no depende de
    esto: vive en ``session.state`` (foco de persona/departamento/periodo, última llamada), que no
    se ve afectado por este valor. Bajar esto reduce el coste/latencia de CADA turno de la
    conversación, no solo de los largos."""
    conversation_retention_days: int = Field(default=30, gt=0)
    """Días que se conservan sesiones y turnos conversacionales antes de eliminarlos."""
    audit_retention_days: int = Field(default=1095, gt=0)
    """Días que se conserva el registro de auditoría (``AuditEvent``) antes de eliminarlo.

    RGPD (art. 5.1.e) exige un plazo de conservación limitado y justificado, no indefinido. El valor
    por defecto (1095 días = 3 años) se alinea con el plazo de prescripción de las infracciones muy
    graves de la LOPDGDD (art. 76): es el tiempo durante el que mIA podría necesitar demostrar quién
    accedió a qué dato. Pasado ese plazo, el propio registro de auditoría deja de tener base para
    conservarse y debe eliminarse."""

    llm: LLMSettings = Field(default_factory=LLMSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    frontend: FrontendSettings = Field(default_factory=FrontendSettings)
    sharepoint: SharePointSettings = Field(default_factory=SharePointSettings)
    data: DataSettings = Field(default_factory=DataSettings)
    domains: DomainSettings = Field(default_factory=DomainSettings)
    mail: MailSettings = Field(default_factory=MailSettings)
    noticias: NoticiasSettings = Field(default_factory=NoticiasSettings)
    curriculums: CurriculumSettings = Field(default_factory=CurriculumSettings)
    reports: ReportSettings = Field(default_factory=ReportSettings)
    attachments: AttachmentSettings = Field(default_factory=AttachmentSettings)
    privacy_gateway: PrivacyGatewaySettings = Field(default_factory=PrivacyGatewaySettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    diagnostics: DiagnosticsSettings = Field(default_factory=DiagnosticsSettings)
    jobs: JobsSettings = Field(default_factory=JobsSettings)

    @model_validator(mode="after")
    def _fail_closed_in_production(self) -> Settings:
        if self.environment is Environment.PRODUCTION and self.auth.mode is AuthMode.DEV:
            raise ValueError("MIA_AUTH__MODE=dev no está permitido en producción: usa 'easyauth' o 'entra'.")
        if self.auth.mode is AuthMode.ENTRA and not all((
            self.auth.entra_tenant_id,
            self.auth.entra_client_id,
            self.auth.entra_web_client_id,
            self.auth.entra_desktop_client_id,
        )):
            raise ValueError(
                "MIA_AUTH__MODE=entra exige Tenant ID, Client ID de la API, Client ID web y Client ID desktop."
            )
        if (
            self.environment is Environment.PRODUCTION
            and self.data.pseudonym_key.get_secret_value() == "solo-para-desarrollo-local"
        ):
            raise ValueError("En producción MIA_DATA__PSEUDONYM_KEY debe venir de Key Vault.")
        if self.environment is Environment.PRODUCTION and self.llm.provider is LLMProviderName.FAKE:
            raise ValueError("El proveedor LLM 'fake' no está permitido en producción.")
        if self.environment is Environment.PRODUCTION and not self.privacy_gateway.enabled:
            raise ValueError("MIA_PRIVACY_GATEWAY__ENABLED=false no está permitido en producción.")
        if self.environment is Environment.PRODUCTION and self.privacy_gateway.fail_open:
            raise ValueError("MIA_PRIVACY_GATEWAY__FAIL_OPEN=true no está permitido en producción.")
        if self.environment is Environment.PRODUCTION and self.diagnostics.enabled and not self.diagnostics.mask_pii:
            raise ValueError("Con diagnósticos activos en producción, MIA_DIAGNOSTICS__MASK_PII=true es obligatorio.")
        if (
            self.diagnostics.enabled
            and (not self.diagnostics.admin_users or not self.diagnostics.admin_password.get_secret_value())
        ):
            raise ValueError(
                "Con MIA_DIAGNOSTICS__ENABLED=true hacen falta MIA_DIAGNOSTICS__ADMIN_USERS "
                "(lista de emails) y MIA_DIAGNOSTICS__ADMIN_PASSWORD -- sin ambos, el panel no "
                "tiene con qué autenticar a nadie y debe quedar deshabilitado, no abierto."
            )
        if (
            self.environment is Environment.PRODUCTION
            and self.privacy_gateway.enabled
            and not self.privacy_gateway.vault_key.get_secret_value()
        ):
            raise ValueError("En producción MIA_PRIVACY_GATEWAY__VAULT_KEY debe venir de Key Vault.")
        return self

    @model_validator(mode="after")
    def _validate_production_endpoints(self) -> Settings:
        if self.environment is not Environment.PRODUCTION:
            return self
        if self.mail.mailbox_source != "user":
            raise ValueError("En producción MIA_MAIL__MAILBOX_SOURCE debe ser 'user'.")
        if self.llm.provider is not LLMProviderName.AZURE_OPENAI:
            raise ValueError("En producción MIA_LLM__PROVIDER debe ser azure_openai.")
        endpoint = urlsplit(self.llm.base_url)
        azure_hosts = (".openai.azure.com", ".openai.azure.cn", ".openai.azure.us")
        if (
            endpoint.scheme != "https"
            or not endpoint.hostname
            or not endpoint.hostname.endswith(azure_hosts)
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
        ):
            raise ValueError(
                "En producción MIA_LLM__BASE_URL debe ser un endpoint HTTPS de Azure OpenAI "
                "(dominio openai.azure.com/.cn/.us), sin credenciales ni parámetros."
            )
        if self.reports.backend != "azure_blob" or not self.reports.azure_account_url:
            raise ValueError(
                "En producción los informes requieren Blob privado y "
                "MIA_REPORTS__AZURE_ACCOUNT_URL (MIA_REPORTS__BACKEND=azure_blob)."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
