"""Modelos de datos del sistema de diagnóstico."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class EventStage(StrEnum):
    # ── Entrada ──────────────────────────────────────────────
    REQUEST_RECEIVED = "REQUEST_RECEIVED"

    # ── Contexto ─────────────────────────────────────────────
    AUTH_CONTEXT = "AUTH_CONTEXT"
    USER_CONTEXT = "USER_CONTEXT"
    TENANT_CONTEXT = "TENANT_CONTEXT"
    CONVERSATION_CONTEXT = "CONVERSATION_CONTEXT"

    # ── Procesamiento de la consulta ──────────────────────────
    QUERY_NORMALIZATION = "QUERY_NORMALIZATION"
    QUERY_REWRITE = "QUERY_REWRITE"
    QUERY_EXPANSION = "QUERY_EXPANSION"

    # ── Routing ───────────────────────────────────────────────
    DOMAIN_DETECTION = "DOMAIN_DETECTION"
    INTENT_DETECTION = "INTENT_DETECTION"
    ENTITY_EXTRACTION = "ENTITY_EXTRACTION"
    SEMANTIC_RESOLUTION = "SEMANTIC_RESOLUTION"
    AMBIGUITY_DETECTION = "AMBIGUITY_DETECTION"

    # ── Plan de ejecución ─────────────────────────────────────
    QUERY_PLANNING = "QUERY_PLANNING"
    PLAN_CREATED = "PLAN_CREATED"
    PLAN_STEP_START = "PLAN_STEP_START"
    PLAN_STEP_COMPLETE = "PLAN_STEP_COMPLETE"

    # ── Capacidades ───────────────────────────────────────────
    CAPABILITY_LOOKUP = "CAPABILITY_LOOKUP"
    CAPABILITY_SELECTED = "CAPABILITY_SELECTED"
    CAPABILITY_MISSING = "CAPABILITY_MISSING"

    # ── Herramientas ──────────────────────────────────────────
    TOOL_SELECTION = "TOOL_SELECTION"
    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_COMPLETE = "TOOL_CALL_COMPLETE"
    TOOL_CALL_ERROR = "TOOL_CALL_ERROR"

    # ── Fuentes de datos ──────────────────────────────────────
    DATA_SOURCE_SELECTION = "DATA_SOURCE_SELECTION"
    SQL_QUERY_START = "SQL_QUERY_START"
    SQL_QUERY_COMPLETE = "SQL_QUERY_COMPLETE"
    SQL_QUERY_ERROR = "SQL_QUERY_ERROR"
    SAP_CALL_START = "SAP_CALL_START"
    SAP_CALL_COMPLETE = "SAP_CALL_COMPLETE"
    SAP_CALL_ERROR = "SAP_CALL_ERROR"
    SHAREPOINT_CALL_START = "SHAREPOINT_CALL_START"
    SHAREPOINT_CALL_COMPLETE = "SHAREPOINT_CALL_COMPLETE"
    SHAREPOINT_CALL_ERROR = "SHAREPOINT_CALL_ERROR"
    GRAPH_CALL_START = "GRAPH_CALL_START"
    GRAPH_CALL_COMPLETE = "GRAPH_CALL_COMPLETE"
    GRAPH_CALL_ERROR = "GRAPH_CALL_ERROR"
    API_CALL_START = "API_CALL_START"
    API_CALL_COMPLETE = "API_CALL_COMPLETE"
    API_CALL_ERROR = "API_CALL_ERROR"
    RAG_SEARCH_START = "RAG_SEARCH_START"
    RAG_SEARCH_COMPLETE = "RAG_SEARCH_COMPLETE"
    RAG_SEARCH_ERROR = "RAG_SEARCH_ERROR"
    DOCUMENT_SEARCH = "DOCUMENT_SEARCH"
    DOCUMENT_RETRIEVAL = "DOCUMENT_RETRIEVAL"
    MAIL_SEARCH = "MAIL_SEARCH"
    MAIL_RETRIEVAL = "MAIL_RETRIEVAL"

    # ── Procesamiento de datos ────────────────────────────────
    DATA_NORMALIZATION = "DATA_NORMALIZATION"
    DATA_FILTERING = "DATA_FILTERING"
    DATA_AGGREGATION = "DATA_AGGREGATION"
    DATA_CALCULATION = "DATA_CALCULATION"

    # ── Analítica ─────────────────────────────────────────────
    ANALYTICS_START = "ANALYTICS_START"
    ANALYTICS_COMPLETE = "ANALYTICS_COMPLETE"
    ANOMALY_DETECTION = "ANOMALY_DETECTION"
    COMPARISON = "COMPARISON"
    FORECAST = "FORECAST"
    INSIGHT_GENERATION = "INSIGHT_GENERATION"

    # ── LLM ───────────────────────────────────────────────────
    PROMPT_BUILD_START = "PROMPT_BUILD_START"
    PROMPT_BUILD_COMPLETE = "PROMPT_BUILD_COMPLETE"
    LLM_REQUEST = "LLM_REQUEST"
    LLM_FIRST_TOKEN = "LLM_FIRST_TOKEN"
    LLM_RESPONSE = "LLM_RESPONSE"
    LLM_ERROR = "LLM_ERROR"
    POSTPROCESSING = "POSTPROCESSING"

    # ── Privacy Gateway ────────────────────────────────────────
    PRIVACY_GATEWAY_INSPECT = "PRIVACY_GATEWAY_INSPECT"
    """Resumen de una llamada protegida: política aplicada y categorías detectadas (nunca los valores)."""
    PRIVACY_GATEWAY_BLOCKED = "PRIVACY_GATEWAY_BLOCKED"
    """Fallo seguro: la llamada externa se bloqueó (Presidio no disponible, secreto irredactable, etc.)."""
    PRIVACY_GATEWAY_RESTORED = "PRIVACY_GATEWAY_RESTORED"
    """Restauración de tokens en la respuesta del LLM antes de mostrarla."""

    # ── Presentación ──────────────────────────────────────────
    PRESENTATION_INTENT_CLASSIFIED = "PRESENTATION_INTENT_CLASSIFIED"
    PRESENTATION_ROUTING = "PRESENTATION_ROUTING"
    PRESENTATION_SELECTED = "PRESENTATION_SELECTED"
    SUPPRESSED_COMPONENT = "SUPPRESSED_COMPONENT"
    CHART_GENERATION = "CHART_GENERATION"
    CARD_GENERATION = "CARD_GENERATION"
    TABLE_GENERATION = "TABLE_GENERATION"
    REPORT_GENERATION = "REPORT_GENERATION"
    VOICE_GENERATION = "VOICE_GENERATION"

    # ── Adjuntos ──────────────────────────────────────────────
    ATTACHMENT_RECEIVED = "ATTACHMENT_RECEIVED"
    ATTACHMENT_VALIDATION_START = "ATTACHMENT_VALIDATION_START"
    ATTACHMENT_VALIDATION_COMPLETE = "ATTACHMENT_VALIDATION_COMPLETE"
    ATTACHMENT_CLASSIFICATION = "ATTACHMENT_CLASSIFICATION"
    ATTACHMENT_PROCESSING_START = "ATTACHMENT_PROCESSING_START"
    ATTACHMENT_PROCESSING_COMPLETE = "ATTACHMENT_PROCESSING_COMPLETE"
    ATTACHMENT_PROCESSING_ERROR = "ATTACHMENT_PROCESSING_ERROR"
    ATTACHMENT_CONTEXT_INJECTED = "ATTACHMENT_CONTEXT_INJECTED"
    ATTACHMENT_EXPIRED = "ATTACHMENT_EXPIRED"
    PDF_EXTRACTION = "PDF_EXTRACTION"
    DOCX_EXTRACTION = "DOCX_EXTRACTION"
    EXCEL_EXTRACTION = "EXCEL_EXTRACTION"
    CSV_EXTRACTION = "CSV_EXTRACTION"
    VISION_ANALYSIS_START = "VISION_ANALYSIS_START"
    VISION_ANALYSIS_COMPLETE = "VISION_ANALYSIS_COMPLETE"
    ATTACHMENT_DATASET_QUERY = "ATTACHMENT_DATASET_QUERY"
    ATTACHMENT_RETRIEVAL = "ATTACHMENT_RETRIEVAL"
    CROSS_SOURCE_ANALYSIS_START = "CROSS_SOURCE_ANALYSIS_START"
    CROSS_SOURCE_ANALYSIS_COMPLETE = "CROSS_SOURCE_ANALYSIS_COMPLETE"
    IDENTITY_RESOLUTION = "IDENTITY_RESOLUTION"

    # ── Respuesta ─────────────────────────────────────────────
    RESPONSE_BUILD = "RESPONSE_BUILD"
    RESPONSE_SENT = "RESPONSE_SENT"

    # ── Control ───────────────────────────────────────────────
    WARNING = "WARNING"
    ERROR = "ERROR"
    EXCEPTION = "EXCEPTION"
    TRACE_COMPLETE = "TRACE_COMPLETE"


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
        from datetime import UTC

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
