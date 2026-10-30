"""Modelos de datos del sistema de diagnóstico."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum, auto
from typing import Any


class EventStage(StrEnum):
    @staticmethod
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[Any]) -> str:
        return name

    # ── Entrada ──────────────────────────────────────────────
    REQUEST_RECEIVED = auto()

    # ── Contexto ─────────────────────────────────────────────
    AUTH_CONTEXT = auto()
    USER_CONTEXT = auto()
    TENANT_CONTEXT = auto()
    CONVERSATION_CONTEXT = auto()

    # ── Procesamiento de la consulta ──────────────────────────
    QUERY_NORMALIZATION = auto()
    QUERY_REWRITE = auto()
    QUERY_EXPANSION = auto()

    # ── Routing ───────────────────────────────────────────────
    DOMAIN_DETECTION = auto()
    INTENT_DETECTION = auto()
    ENTITY_EXTRACTION = auto()
    SEMANTIC_RESOLUTION = auto()
    AMBIGUITY_DETECTION = auto()

    # ── Plan de ejecución ─────────────────────────────────────
    QUERY_PLANNING = auto()
    PLAN_CREATED = auto()
    PLAN_STEP_START = auto()
    PLAN_STEP_COMPLETE = auto()

    # ── Capacidades ───────────────────────────────────────────
    CAPABILITY_LOOKUP = auto()
    CAPABILITY_SELECTED = auto()
    CAPABILITY_MISSING = auto()

    # ── Herramientas ──────────────────────────────────────────
    TOOL_SELECTION = auto()
    TOOL_CALL_START = auto()
    TOOL_CALL_COMPLETE = auto()
    TOOL_CALL_ERROR = auto()

    # ── Fuentes de datos ──────────────────────────────────────
    DATA_SOURCE_SELECTION = auto()
    SQL_QUERY_START = auto()
    SQL_QUERY_COMPLETE = auto()
    SQL_QUERY_ERROR = auto()
    SAP_CALL_START = auto()
    SAP_CALL_COMPLETE = auto()
    SAP_CALL_ERROR = auto()
    SHAREPOINT_CALL_START = auto()
    SHAREPOINT_CALL_COMPLETE = auto()
    SHAREPOINT_CALL_ERROR = auto()
    GRAPH_CALL_START = auto()
    GRAPH_CALL_COMPLETE = auto()
    GRAPH_CALL_ERROR = auto()
    API_CALL_START = auto()
    API_CALL_COMPLETE = auto()
    API_CALL_ERROR = auto()
    RAG_SEARCH_START = auto()
    RAG_SEARCH_COMPLETE = auto()
    RAG_SEARCH_ERROR = auto()
    DOCUMENT_SEARCH = auto()
    DOCUMENT_RETRIEVAL = auto()
    MAIL_SEARCH = auto()
    MAIL_RETRIEVAL = auto()

    # ── Procesamiento de datos ────────────────────────────────
    DATA_NORMALIZATION = auto()
    DATA_FILTERING = auto()
    DATA_AGGREGATION = auto()
    DATA_CALCULATION = auto()

    # ── Analítica ─────────────────────────────────────────────
    ANALYTICS_START = auto()
    ANALYTICS_COMPLETE = auto()
    ANOMALY_DETECTION = auto()
    COMPARISON = auto()
    FORECAST = auto()
    INSIGHT_GENERATION = auto()

    # ── LLM ───────────────────────────────────────────────────
    PROMPT_BUILD_START = auto()
    PROMPT_BUILD_COMPLETE = auto()
    LLM_REQUEST = auto()
    LLM_FIRST_TOKEN = auto()
    LLM_RESPONSE = auto()
    LLM_ERROR = auto()
    POSTPROCESSING = auto()

    # ── Privacy Gateway ────────────────────────────────────────
    PRIVACY_GATEWAY_INSPECT = auto()
    """Resumen de una llamada protegida: política aplicada y categorías detectadas (nunca los valores)."""
    PRIVACY_GATEWAY_BLOCKED = auto()
    """Fallo seguro: la llamada externa se bloqueó (Presidio no disponible, secreto irredactable, etc.)."""
    PRIVACY_GATEWAY_RESTORED = auto()
    """Restauración de tokens en la respuesta del LLM antes de mostrarla."""

    # ── Presentación ──────────────────────────────────────────
    PRESENTATION_INTENT_CLASSIFIED = auto()
    PRESENTATION_ROUTING = auto()
    PRESENTATION_SELECTED = auto()
    SUPPRESSED_COMPONENT = auto()
    CHART_GENERATION = auto()
    CARD_GENERATION = auto()
    TABLE_GENERATION = auto()
    REPORT_GENERATION = auto()
    VOICE_GENERATION = auto()

    # ── Adjuntos ──────────────────────────────────────────────
    ATTACHMENT_RECEIVED = auto()
    ATTACHMENT_VALIDATION_START = auto()
    ATTACHMENT_VALIDATION_COMPLETE = auto()
    ATTACHMENT_CLASSIFICATION = auto()
    ATTACHMENT_PROCESSING_START = auto()
    ATTACHMENT_PROCESSING_COMPLETE = auto()
    ATTACHMENT_PROCESSING_ERROR = auto()
    ATTACHMENT_CONTEXT_INJECTED = auto()
    ATTACHMENT_EXPIRED = auto()
    PDF_EXTRACTION = auto()
    DOCX_EXTRACTION = auto()
    EXCEL_EXTRACTION = auto()
    CSV_EXTRACTION = auto()
    VISION_ANALYSIS_START = auto()
    VISION_ANALYSIS_COMPLETE = auto()
    ATTACHMENT_DATASET_QUERY = auto()
    ATTACHMENT_RETRIEVAL = auto()
    CROSS_SOURCE_ANALYSIS_START = auto()
    CROSS_SOURCE_ANALYSIS_COMPLETE = auto()
    IDENTITY_RESOLUTION = auto()

    # ── Respuesta ─────────────────────────────────────────────
    RESPONSE_BUILD = auto()
    RESPONSE_SENT = auto()

    # ── Control ───────────────────────────────────────────────
    WARNING = auto()
    ERROR = auto()
    EXCEPTION = auto()
    TRACE_COMPLETE = auto()


class EventStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"
    INFO = "info"


class TraceStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class DiagnosticIssueType(StrEnum):
    DATA_MISSING = "DATA_MISSING"
    DATA_SOURCE_ERROR = "DATA_SOURCE_ERROR"
    CAPABILITY_MISSING = "CAPABILITY_MISSING"
    TOOL_NOT_SELECTED = "TOOL_NOT_SELECTED"
    TOOL_ERROR = "TOOL_ERROR"
    INTENT_ERROR = "INTENT_ERROR"
    ENTITY_ERROR = "ENTITY_ERROR"
    SEMANTIC_ERROR = "SEMANTIC_ERROR"
    AMBIGUITY = "AMBIGUITY"
    RAG_LOW_CONFIDENCE = "RAG_LOW_CONFIDENCE"
    RAG_NO_RESULTS = "RAG_NO_RESULTS"
    FILTER_ERROR = "FILTER_ERROR"
    ANALYTICS_ERROR = "ANALYTICS_ERROR"
    PROMPT_ERROR = "PROMPT_ERROR"
    LLM_ERROR = "LLM_ERROR"
    LLM_HALLUCINATION_RISK = "LLM_HALLUCINATION_RISK"
    PRESENTATION_ERROR = "PRESENTATION_ERROR"
    PERFORMANCE_WARNING = "PERFORMANCE_WARNING"
    TEMPORAL_CONSTRAINT_DROPPED = "TEMPORAL_CONSTRAINT_DROPPED"
    HALLUCINATION_GUARD = "HALLUCINATION_GUARD"
    PRESENTATION_OVERLOAD = "PRESENTATION_OVERLOAD"
    REDUNDANT_FOLLOWUP_OFFER = "REDUNDANT_FOLLOWUP_OFFER"
    COUNT_PRESENTATION_MISMATCH = "COUNT_PRESENTATION_MISMATCH"
    TEMPORAL_SCOPE_MISMATCH = "TEMPORAL_SCOPE_MISMATCH"
    UNKNOWN = "UNKNOWN"


@dataclass
class DiagnosticEvent:
    trace_id: str
    timestamp: datetime
    stage: str
    status: str = EventStatus.INFO
    duration_ms: int | None = None
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp.isoformat(),
            "stage": self.stage,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "data": self.data,
            "metadata": self.metadata,
        }


@dataclass
class DiagnosticIssue:
    type: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "message": self.message, "details": self.details}


@dataclass
class TraceRecord:
    trace_id: str
    started_at: datetime
    query: str

    # Contexto
    request_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    user_name: str | None = None
    tenant_id: str | None = None

    # Estado
    status: str = TraceStatus.RUNNING
    completed_at: datetime | None = None
    elapsed_ms: int | None = None

    # Routing
    domain: str | None = None
    modules: list[str] = field(default_factory=list)
    intent: str | None = None

    # Ejecución
    tools_called: list[str] = field(default_factory=list)
    tool_errors: int = 0
    llm_rounds: int = 0
    llm_model: str | None = None

    # Uso de tokens
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_cached: int = 0

    # Resultado
    final_answer: str | None = None
    presentations: list[str] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0

    # Diagnóstico automático
    issues: list[DiagnosticIssue] = field(default_factory=list)

    # Hora local de la petición (timezone-aware ISO 8601, ej. "2026-10-07T21:55:23+02:00")
    now_local: str | None = None

    # Etiquetado manual (Golden Dataset)
    label: str | None = None  # "correct" | "incorrect" | "needs_review" | "regression"
    developer_notes: str | None = None

    # Grafo de ejecución (nodos planos con parent_id para reconstruir el árbol)
    call_graph: list[dict[str, Any]] = field(default_factory=list)

    # Eventos
    events: list[DiagnosticEvent] = field(default_factory=list)

    def elapsed_since_start(self) -> int:

        now = datetime.now(UTC)
        return int((now - self.started_at).total_seconds() * 1000)

    def to_summary(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "elapsed_ms": self.elapsed_ms,
            "query": self.query,
            "status": self.status,
            "domain": self.domain,
            "modules": self.modules,
            "intent": self.intent,
            "tools_called": self.tools_called,
            "tool_errors": self.tool_errors,
            "llm_rounds": self.llm_rounds,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "tokens_cached": self.tokens_cached,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "label": self.label,
        }

    def to_dict(self) -> dict[str, Any]:
        d = self.to_summary()
        d.update(
            {
                "user_name": self.user_name,
                "request_id": self.request_id,
                "tenant_id": self.tenant_id,
                "llm_model": self.llm_model,
                "final_answer": self.final_answer,
                "presentations": self.presentations,
                "issues": [i.to_dict() for i in self.issues],
                "now_local": self.now_local,
                "developer_notes": self.developer_notes,
                "call_graph": self.call_graph,
                "events": [e.to_dict() for e in self.events],
            }
        )
        return d
