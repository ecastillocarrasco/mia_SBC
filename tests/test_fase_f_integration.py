"""Fase F del Bloque II (Advanced Reporting Engine):

1. Conexión GENERAL del `ReportPlanner` (ya existente, sin construir otro) al pipeline conversacional —
   una pista no vinculante en el contexto del turno, calculada para CUALQUIER dominio del catálogo
   semántico (nóminas, turnos, vacaciones, plantilla…), no solo el guard puntual ya resuelto para
   nóminas dentro de `generar_informe_ejecutivo`.
2. Selección configurable de modelo (niveles FAST/BALANCED/ADVANCED), con GPT-4.1 mini como nivel
   BALANCED por defecto — el mismo modelo que ya usaba toda la conversación antes de esta fase.
3. Validación de narrativa mediante Privacy Gateway: el texto GENERADO por el LLM para un informe se
   inspecciona explícitamente en busca de datos personales antes de publicarse (no solo implícitamente,
   por venir de un proveedor ya envuelto) — si aparece uno, se bloquea esa afirmación.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from mia.auth import UserContext
from mia.conversation.engine import _REPORT_DOMAIN_HINTS, _report_hint
from mia.llm.base import LLMCompleted, LLMEvent, LLMRequest, Message, TextDelta
from mia.llm.fake import FakeLLMProvider, tool_call
from mia.llm.tiers import model_for_tier
from mia.privacy_gateway.context_manager import set_operation_context
from mia.privacy_gateway.gateway import PrivacyGateway
from mia.privacy_gateway.presidio_engine import DetectedEntity
from mia.reporting.narrative_generation import generate_narrative_block
from mia.reporting.narrative_guard import enforce_narrative_privacy
from mia.settings import LLMSettings, ModelTier, PrivacyGatewaySettings
from tests.hr_seed import seed
from tests.test_analisis_economico import Q3_NOW, q3_registry  # noqa: F401 — fixture reutilizada

ADMIN = UserContext("u", "Enrique", roles=frozenset({"mia.admin"}))
TODAY = date(2026, 10, 12)


# ───────────────────────────────────────────────────── 2. selección configurable de modelo


def test_model_for_tier_resolves_each_level() -> None:
    settings = LLMSettings(model="gpt-4.1-mini", model_fast="gpt-4.1-nano", model_advanced="gpt-4.1")
    assert model_for_tier(settings, ModelTier.FAST) == "gpt-4.1-nano"
    assert model_for_tier(settings, ModelTier.BALANCED) == "gpt-4.1-mini"
    assert model_for_tier(settings, ModelTier.ADVANCED) == "gpt-4.1"


def _narrative_script(req: LLMRequest) -> list[LLMEvent]:
    import json  # noqa: PLC0415

    payload = json.dumps({"statements": [{"kind": "interpretation", "text": "El gasto se mantiene estable."}]})
    return [TextDelta(payload), LLMCompleted()]


async def test_generate_narrative_block_without_settings_keeps_the_previous_default_model() -> None:
    """No pasar `llm_settings`/`tier` (como hacía todo el código anterior a esta fase) debe seguir sin
    forzar ningún modelo concreto en la petición — comportamiento idéntico al de antes de la Fase F."""
    llm = FakeLLMProvider(_narrative_script)
    block = await generate_narrative_block(llm, title="Informe", backend_summary={"total": 100.0})
    assert block is not None
    assert llm.requests[-1].model is None


async def test_generate_narrative_block_with_advanced_tier_requests_the_advanced_model() -> None:
    llm = FakeLLMProvider(_narrative_script)
    settings = LLMSettings(model="gpt-4.1-mini", model_advanced="gpt-4.1-super")
    block = await generate_narrative_block(
        llm, title="Informe", backend_summary={"total": 100.0}, llm_settings=settings, tier=ModelTier.ADVANCED
    )
    assert block is not None
    assert llm.requests[-1].model == "gpt-4.1-super"


# ─────────────────────────────────────────────────── 2bis. coherencia temporal (evidencia estructurada)


async def test_generate_narrative_block_blocks_a_structurally_wrong_period_end_to_end() -> None:
    """Extremo a extremo: el LLM declara, en el campo ESTRUCTURADO `period` de su propia evidencia
    (nunca analizado por expresiones regulares sobre la prosa), un periodo distinto del real del
    informe (`expected_period`) — la afirmación se bloquea, con el valor numérico siendo correcto."""

    def script(req: LLMRequest) -> list[LLMEvent]:
        import json  # noqa: PLC0415

        payload = json.dumps(
            {
                "statements": [
                    {
                        "kind": "fact",
                        "text": "En julio el gasto fue de 100 €.",
                        "metric": "total",
                        "value": 100.0,
                        "period": "Julio 2026",
                    }
                ]
            }
        )
        return [TextDelta(payload), LLMCompleted()]

    llm = FakeLLMProvider(script)
    block = await generate_narrative_block(
        llm, title="Informe", backend_summary={"total": 100.0}, expected_period="Agosto 2026"
    )
    assert block is not None
    texts = [s["text"] for s in block.data["statements"]]
    assert any("periodo incoherente" in t.lower() for t in texts)
    assert any("Julio 2026" in t and "Agosto 2026" in t for t in texts)


async def test_generate_narrative_block_accepts_a_matching_structured_period() -> None:
    def script(req: LLMRequest) -> list[LLMEvent]:
        import json  # noqa: PLC0415

        payload = json.dumps(
            {
                "statements": [
                    {
                        "kind": "fact",
                        "text": "En agosto el gasto fue de 100 €.",
                        "metric": "total",
                        "value": 100.0,
                        "period": "Agosto 2026",
                    }
                ]
            }
        )
        return [TextDelta(payload), LLMCompleted()]

    llm = FakeLLMProvider(script)
    block = await generate_narrative_block(
        llm, title="Informe", backend_summary={"total": 100.0}, expected_period="Agosto 2026"
    )
    assert block is not None
    texts = [s["text"] for s in block.data["statements"]]
    assert texts == ["En agosto el gasto fue de 100 €."]


# ───────────────────────────────────────────────────── 3. validación de narrativa vía Privacy Gateway


def test_enforce_narrative_privacy_passes_through_when_no_scanner_available() -> None:
    """Un LLM simulado sin `scan_text_for_pii` (todas las pruebas con FakeLLMProvider anteriores a esta
    fase) no debe verse afectado: comportamiento idéntico al de antes."""
    statements = [{"kind": "interpretation", "text": "Cualquier texto, incluso con un nombre: Ana López."}]
    assert enforce_narrative_privacy(statements, pii_scan=None) == statements


def test_enforce_narrative_privacy_blocks_a_statement_with_detected_pii() -> None:
    def fake_scan(text: str) -> list[DetectedEntity]:
        if "Ana López" in text:
            return [DetectedEntity("PERSON", text.index("Ana"), text.index("Ana") + 8, 0.9, "Ana López")]
        return []

    statements = [
        {"kind": "interpretation", "text": "El coste de Ana López subió un 5%."},
        {"kind": "interpretation", "text": "El gasto total se mantiene estable."},
    ]
    out = enforce_narrative_privacy(statements, pii_scan=fake_scan)
    assert "CONCLUSIÓN BLOQUEADA" in out[0]["text"]
    assert "Ana López" not in out[0]["text"]  # el dato detectado nunca se repite en el aviso
    assert out[0]["evidence"]["privacy_blocked"] is True
    assert out[0]["evidence"]["entity_types"] == ["PERSON"]
    assert out[1]["text"] == "El gasto total se mantiene estable."  # la afirmación limpia no se toca


async def test_generate_narrative_block_blocks_statements_with_pii_end_to_end() -> None:
    def script(req: LLMRequest) -> list[LLMEvent]:
        import json  # noqa: PLC0415

        payload = json.dumps(
            {"statements": [{"kind": "interpretation", "text": "Destaca el caso de Ana López este mes."}]}
        )
        return [TextDelta(payload), LLMCompleted()]

    class _LLMWithPiiScan(FakeLLMProvider):
        def scan_text_for_pii(self, text: str) -> list[DetectedEntity]:
            if "Ana López" in text:
                return [DetectedEntity("PERSON", 0, 1, 0.95, "Ana López")]
            return []

    llm = _LLMWithPiiScan(script)
    block = await generate_narrative_block(llm, title="Informe", backend_summary={"total": 100.0})
    assert block is not None
    texts = [item["text"] for item in block.data["statements"]]
    assert any("CONCLUSIÓN BLOQUEADA" in t for t in texts)
    assert not any("Ana López" in t for t in texts)


async def test_privacy_gateway_scan_text_for_pii_detects_a_real_name_with_the_real_engine() -> None:
    """Prueba de extremo a extremo con el motor Presidio REAL (no simulado) ya usado en el resto del
    Privacy Gateway — confirma que `scan_text_for_pii` es una pieza real, no una promesa sin código."""
    set_operation_context(user_id="u", operation_id="op-1")
    settings = PrivacyGatewaySettings(enabled=True, vault_key="clave-de-prueba-no-real", vault_ttl_seconds=60)
    gateway = PrivacyGateway(FakeLLMProvider(), settings, provider_name="test", model="test-model")
    entities = gateway.scan_text_for_pii("El empleado Carlos Fernández presentó su baja el lunes.")
    assert any(e.entity_type == "PERSON" for e in entities)
    assert gateway.scan_text_for_pii("El gasto total del departamento fue correcto.") == [] or all(
        e.entity_type != "PERSON" for e in gateway.scan_text_for_pii("El gasto total del departamento fue correcto.")
    )


def test_privacy_gateway_scan_text_for_pii_returns_nothing_when_disabled() -> None:
    gateway = PrivacyGateway(
        FakeLLMProvider(), PrivacyGatewaySettings(enabled=False), provider_name="test", model="test-model"
    )
    assert gateway.scan_text_for_pii("Carlos Fernández cualquier texto") == []


# ───────────────────────────────────────────────────── 1. conexión general del ReportPlanner


@pytest.mark.parametrize(
    ("message", "expected_domain"),
    [
        ("comparativa de costes en nóminas por departamento en agosto de 2026", "payroll"),
        ("resumen de absentismo por turnos este trimestre", "shift"),
        ("saldo de vacaciones del equipo", "vacation"),
        ("plantilla por departamento", "employee"),
    ],
)
def test_report_hint_covers_every_domain_not_only_payroll(message: str, expected_domain: str) -> None:
    hint = _report_hint(message, ADMIN, TODAY)
    assert hint != ""
    assert "## Pista de datos detectados" in hint
    assert _REPORT_DOMAIN_HINTS[expected_domain] in hint


def test_report_hint_is_empty_for_a_message_with_no_recognizable_field() -> None:
    assert _report_hint("Hola, ¿qué tiempo hace hoy?", ADMIN, TODAY) == ""


async def test_report_hint_reaches_the_llm_context_through_the_real_chat_pipeline(
    client: Any, services: Any, script: list
) -> None:
    """Confirma que la pista llega de verdad al contexto que recibe el LLM a través del mismo punto de
    entrada que usa el chat — con un dominio DISTINTO al del guard puntual de nóminas (vacaciones), para
    probar que la conexión es general y no solo el caso ya resuelto."""
    captured: list[LLMRequest] = []

    def scripted(req: LLMRequest) -> list[LLMEvent]:
        captured.append(req)
        from mia.llm.fake import final_answer  # noqa: PLC0415

        return final_answer("Ok.", "Ok.")

    script[0] = scripted
    await client.post("/api/chat", json={"message": "¿Cuál es el saldo de vacaciones del equipo?"})
    assert captured, "el LLM nunca llegó a recibir la petición"
    last_user_content = captured[-1].messages[-1].content
    assert "## Pista de datos detectados" in last_user_content
    assert _REPORT_DOMAIN_HINTS["vacation"] in last_user_content


# ───────────────────────────────────────────────────── punto 1 (validación tras el hint): generar_informe


async def test_generar_informe_rejects_a_payroll_request_exported_from_an_unrelated_tool(
    q3_registry,
) -> None:
    """El plan no es solo una sugerencia para el LLM: si la tabla que se va a exportar NO viene de
    `analisis_economico_nominas` (``__source_tool__``, puesto por ``remember_table`` junto a ESA tabla
    concreta) pero la petición original pide coste salarial, `generar_informe` debe rechazar la
    exportación — nunca exportar una tabla que no coincide con lo pedido."""
    from mia.conversation.tools import remember_table
    from mia.conversation import ToolContext, ToolStatus as TS
    from mia.llm import ToolCall as TC
    import json as _json

    ctx = ToolContext(
        user=ADMIN, request_id=None, now=Q3_NOW, session_state={},
        user_message="comparativa de costes en nóminas por departamento en agosto de 2026",
    )
    unrelated_presentation = {"type": "table", "title": "Plantilla", "columns": ["Nombre"], "rows": [["Ana"]]}
    remember_table(ctx.session_state, unrelated_presentation, 5000, {}, source_tool="plantilla")
    execution = await q3_registry.execute(TC("c", "generar_informe", _json.dumps({"formato": "pdf"})), ctx)
    assert execution.result.status is TS.INVALID_ARGUMENTS
    assert "analisis_economico_nominas" in execution.result.summary["mensaje"]


async def test_generar_informe_rejects_bare_gastos_phrasing_exported_from_ficha_empleado(q3_registry) -> None:
    """Incidencia real: "Genera importe de gastos por departamento en 2026" (sin "costes"/"nóminas") no
    reconocía ningún campo económico en el ReportPlanner — su vocabulario solo tenía "gasto de
    personal"/"gasto en nóminas", nunca "gasto"/"gastos" a secas. Este guard (el mismo de arriba) nunca
    se activaba, así que `generar_informe` exportaba en silencio la ficha de un empleado que seguía
    siendo la última tabla de la sesión (de una consulta anterior, no relacionada), con un título nuevo
    que sonaba a lo pedido pero un contenido que no tenía nada que ver. Corregido ampliando los
    sinónimos de `coste_empresa` en mia.query.fields."""
    from mia.conversation.tools import remember_table
    from mia.conversation import ToolContext, ToolStatus as TS
    from mia.llm import ToolCall as TC
    import json as _json

    ctx = ToolContext(
        user=ADMIN, request_id=None, now=Q3_NOW, session_state={},
        user_message="Genera importe de gastos por departamento en 2026",
    )
    ficha_presentation = {
        "type": "profile", "title": "Ficha laboral",
        "columns": ["Campo", "Valor"],
        "rows": [["Departamento", "RRHH"], ["Saldo vacaciones", "9"]],
    }
    remember_table(ctx.session_state, ficha_presentation, 5000, {}, source_tool="ficha_empleado")
    execution = await q3_registry.execute(TC("c", "generar_informe", _json.dumps({"formato": "pdf"})), ctx)
    assert execution.result.status is TS.INVALID_ARGUMENTS
    assert "analisis_economico_nominas" in execution.result.summary["mensaje"]


async def test_generar_informe_still_exports_normally_when_the_source_tool_matches_the_request(
    q3_registry,
) -> None:
    """Control negativo: si la tabla SÍ viene de `analisis_economico_nominas` y su periodo coincide,
    la exportación debe seguir funcionando exactamente igual que antes de esta validación."""
    from mia.conversation.tools import remember_table
    from mia.conversation import ToolContext, ToolStatus as TS
    from mia.llm import ToolCall as TC
    import json as _json

    ctx = ToolContext(
        user=ADMIN, request_id=None, now=Q3_NOW, session_state={},
        user_message="comparativa de costes en nóminas por departamento en agosto de 2026",
    )
    presentation = {"type": "table", "title": "Gasto salarial", "columns": ["Departamento"], "rows": [["Cocina"]]}
    summary = {"periodo_interpretado": "Agosto 2026"}
    remember_table(ctx.session_state, presentation, 5000, summary, source_tool="analisis_economico_nominas")
    execution = await q3_registry.execute(TC("c", "generar_informe", _json.dumps({"formato": "pdf"})), ctx)
    assert execution.result.status is TS.OK


async def test_generar_informe_rejects_a_source_tool_result_from_a_different_period(q3_registry) -> None:
    """Punto 3 (revisado), "evitando aceptar resultados de... otro periodo": la tabla viene de
    `analisis_economico_nominas` (herramienta correcta), pero para un periodo DISTINTO del pedido ahora
    —p. ej. una tabla de julio que seguía siendo la última de la sesión cuando llega una petición nueva
    sobre agosto— debe rechazarse igual, nunca exportarse como si fuera la respuesta a la nueva petición."""
    from mia.conversation.tools import remember_table
    from mia.conversation import ToolContext, ToolStatus as TS
    from mia.llm import ToolCall as TC
    import json as _json

    ctx = ToolContext(
        user=ADMIN, request_id=None, now=Q3_NOW, session_state={},
        user_message="comparativa de costes en nóminas por departamento en agosto de 2026",
    )
    presentation = {"type": "table", "title": "Gasto salarial", "columns": ["Departamento"], "rows": [["Cocina"]]}
    stale_summary = {"periodo_interpretado": "Julio 2026"}  # la petición actual pide agosto, no julio
    remember_table(ctx.session_state, presentation, 5000, stale_summary, source_tool="analisis_economico_nominas")
    execution = await q3_registry.execute(TC("c", "generar_informe", _json.dumps({"formato": "pdf"})), ctx)
    assert execution.result.status is TS.INVALID_ARGUMENTS
    assert "periodo" in execution.result.summary["mensaje"].lower()


async def test_generar_informe_is_not_fooled_by_an_auxiliary_tool_called_afterward(q3_registry) -> None:
    """Punto 3 (revisado): "no debe rechazarse un informe legítimo simplemente porque se haya ejecutado
    posteriormente una herramienta auxiliar". Simula exactamente ese orden: `analisis_economico_nominas`
    (correcto, produce la tabla) y DESPUÉS una herramienta auxiliar que NO devuelve presentación (p. ej.
    una consulta de capacidades) — la tabla de la economía sigue siendo ``LAST_TABLE`` con su
    ``__source_tool__`` intacto, así que la exportación debe seguir permitida."""
    from mia.conversation.tools import remember_table
    from mia.conversation import ToolContext, ToolStatus as TS
    from mia.llm import ToolCall as TC
    import json as _json

    ctx = ToolContext(
        user=ADMIN, request_id=None, now=Q3_NOW, session_state={},
        user_message="comparativa de costes en nóminas por departamento en agosto de 2026",
    )
    presentation = {"type": "table", "title": "Gasto salarial", "columns": ["Departamento"], "rows": [["Cocina"]]}
    summary = {"periodo_interpretado": "Agosto 2026"}
    remember_table(ctx.session_state, presentation, 5000, summary, source_tool="analisis_economico_nominas")
    # Herramienta auxiliar posterior SIN presentación propia (p. ej. type=None/"download"): remember_table
    # la ignora por diseño — LAST_TABLE no cambia, a diferencia de lo que haría LAST_CALL.
    remember_table(ctx.session_state, {"type": "download", "url": "/api/reports/otro"}, 5000, None, source_tool="otra_herramienta_auxiliar")
    execution = await q3_registry.execute(TC("c", "generar_informe", _json.dumps({"formato": "pdf"})), ctx)
    assert execution.result.status is TS.OK


# ───────────────────────────────────────────────────── punto 2: los niveles nunca saltan el Privacy Gateway


async def test_every_model_tier_still_goes_through_privacy_gateway_sanitization() -> None:
    """Ningún nivel (FAST/BALANCED/ADVANCED) puede saltarse la sanitización/auditoría del Privacy
    Gateway: el campo `model` es solo un dato más de la petición que `_sanitize_request` reconstruye
    con `dataclasses.replace`, nunca una rama alternativa que evite el envoltorio."""
    set_operation_context(user_id="u", operation_id="op-tier")
    settings = PrivacyGatewaySettings(enabled=True, vault_key="clave-de-prueba-no-real", vault_ttl_seconds=60)

    captured: list[LLMRequest] = []

    class _Inner(FakeLLMProvider):
        async def stream(self, request: LLMRequest):  # noqa: ANN201
            captured.append(request)
            async for event in super().stream(request):
                yield event

    inner = _Inner(lambda req: [TextDelta("ok"), LLMCompleted()])
    llm_settings = LLMSettings(model="gpt-4.1-mini", model_fast="gpt-4.1-nano", model_advanced="gpt-4.1")

    for tier in (ModelTier.FAST, ModelTier.BALANCED, ModelTier.ADVANCED):
        model = model_for_tier(llm_settings, tier)
        gateway = PrivacyGateway(inner, settings, provider_name="test", model="unused-default")
        request = LLMRequest(
            system="sys",
            messages=[Message(role="user", content="mi contraseña es password=supersecreta123")],
            model=model,
        )
        async for _ in gateway.stream(request):
            pass
        # Lo que de verdad llegó al proveedor interno: el secreto redactado (prueba de que
        # _sanitize_request se ejecutó) Y el modelo del nivel pedido (prueba de que no se perdió).
        received = captured[-1]
        assert "supersecreta123" not in received.messages[-1].content
        assert received.model == model


# ───────────────────────────────────────────────────── punto 4: autorización vs. protección de salida


async def test_enforce_narrative_privacy_does_not_block_a_legitimate_individual_report() -> None:
    """No debe inutilizar informes individuales legítimos: si el nombre citado por el LLM YA estaba en
    el resumen que el backend le entregó (p. ej. una ficha 360 de una persona que el usuario SÍ está
    autorizado a ver), no es una fuga — la protección distingue dato ya autorizado de dato introducido
    de la nada por el modelo."""

    def fake_scan(text: str) -> list[DetectedEntity]:
        if "Ana López" in text:
            idx = text.index("Ana")
            return [DetectedEntity("PERSON", idx, idx + 9, 0.9, "Ana López")]
        return []

    statements = [{"kind": "interpretation", "text": "El absentismo de Ana López ha bajado este mes."}]
    out = enforce_narrative_privacy(
        statements, pii_scan=fake_scan, authorized_subjects=frozenset({"ana lópez"})
    )
    assert out[0]["text"] == statements[0]["text"]  # no se bloquea: el nombre ya era autorizado
    assert "privacy_blocked" not in (out[0].get("evidence") or {})


async def test_enforce_narrative_privacy_still_blocks_a_name_absent_from_the_backend_summary() -> None:
    """Control: un nombre que el LLM menciona pero que NO estaba en ningún valor del resumen del
    backend sí debe bloquearse — es información introducida de la nada, no una cita legítima."""

    def fake_scan(text: str) -> list[DetectedEntity]:
        if "Pedro Ruiz" in text:
            idx = text.index("Pedro")
            return [DetectedEntity("PERSON", idx, idx + 10, 0.9, "Pedro Ruiz")]
        return []

    statements = [{"kind": "interpretation", "text": "Destaca especialmente Pedro Ruiz este mes."}]
    out = enforce_narrative_privacy(
        statements, pii_scan=fake_scan, authorized_subjects=frozenset({"ana lópez"})
    )
    assert "CONCLUSIÓN BLOQUEADA" in out[0]["text"]
    assert out[0]["evidence"]["privacy_blocked"] is True


async def test_generate_narrative_block_does_not_block_the_subject_of_an_individual_report() -> None:
    """Extremo a extremo: si quien llama declara EXPLÍCITAMENTE (``authorized_subjects``) que esta
    narrativa es sobre una persona concreta —porque ya comprobó el permiso para ella exactamente, como
    hace ``ficha_empleado``— y el LLM cita ese MISMO nombre, el bloque debe publicarse sin bloquear. El
    mero hecho de que el nombre esté en ``backend_summary`` ya NO basta por sí solo (ver revisión de
    privacidad contextual): la autorización debe declararse, nunca inferirse del resumen."""

    def script(req: LLMRequest) -> list[LLMEvent]:
        import json  # noqa: PLC0415

        payload = json.dumps(
            {"statements": [{"kind": "interpretation", "text": "El rendimiento de Ana López ha mejorado."}]}
        )
        return [TextDelta(payload), LLMCompleted()]

    class _LLMWithPiiScan(FakeLLMProvider):
        def scan_text_for_pii(self, text: str) -> list[DetectedEntity]:
            if "Ana López" in text:
                idx = text.index("Ana")
                return [DetectedEntity("PERSON", idx, idx + 9, 0.9, "Ana López")]
            return []

    llm = _LLMWithPiiScan(script)
    block = await generate_narrative_block(
        llm,
        title="Ficha 360",
        backend_summary={"nombre": "Ana López", "departamento": "Pisos"},
        authorized_subjects=frozenset({"ana lópez"}),
    )
    assert block is not None
    texts = [s["text"] for s in block.data["statements"]]
    assert "CONCLUSIÓN BLOQUEADA" not in " ".join(texts)
    assert any("Ana López" in t for t in texts)


async def test_generate_narrative_block_blocks_a_name_in_the_summary_without_explicit_authorization() -> None:
    """Revisión de privacidad contextual: que un nombre esté en ``backend_summary`` ya NO basta por sí
    solo. Sin ``authorized_subjects`` explícito (su valor por defecto es vacío, fail-closed), el mismo
    escenario del test anterior debe BLOQUEARSE — "el backend lo calculó" nunca es, por sí mismo,
    "autorizado para el LLM/la narrativa"."""

    def script(req: LLMRequest) -> list[LLMEvent]:
        import json  # noqa: PLC0415

        payload = json.dumps(
            {"statements": [{"kind": "interpretation", "text": "El rendimiento de Ana López ha mejorado."}]}
        )
        return [TextDelta(payload), LLMCompleted()]

    class _LLMWithPiiScan(FakeLLMProvider):
        def scan_text_for_pii(self, text: str) -> list[DetectedEntity]:
            if "Ana López" in text:
                idx = text.index("Ana")
                return [DetectedEntity("PERSON", idx, idx + 9, 0.9, "Ana López")]
            return []

    llm = _LLMWithPiiScan(script)
    block = await generate_narrative_block(
        llm, title="Ficha 360", backend_summary={"nombre": "Ana López", "departamento": "Pisos"}
    )  # sin authorized_subjects
    assert block is not None
    texts = [s["text"] for s in block.data["statements"]]
    assert any("CONCLUSIÓN BLOQUEADA" in t for t in texts)


async def test_generar_informe_authorizes_the_narrative_subject_of_an_individual_report(tmp_path) -> None:
    """Extremo a extremo con el camino real: ``generar_informe`` extrae el sujeto autorizado de
    ``__summary__['nombre']`` (el mismo patrón ya usado por herramientas de ficha individual, p. ej.
    ``ficha_empleado``) y lo propaga a ``generate_narrative_block`` — sin este cableado, cualquier
    informe individual con narrativa activada bloquearía la mención de su propio sujeto."""
    import json as _json
    from types import SimpleNamespace

    from mia.conversation import ToolContext, ToolStatus as TS
    from mia.conversation.tools import LAST_TABLE, remember_table
    from mia.modules.rrhh.common import Deps
    from mia.modules.rrhh.informes.tools import InformeParams, generar
    from tests.dbutil import fresh_database

    def script(req: LLMRequest) -> list[LLMEvent]:
        payload = _json.dumps(
            {"statements": [{"kind": "interpretation", "text": "Ana López mantiene buen rendimiento."}]}
        )
        return [TextDelta(payload), LLMCompleted()]

    class _NarrativeLLM(FakeLLMProvider):
        def scan_text_for_pii(self, text: str) -> list[DetectedEntity]:
            if "Ana López" in text:
                idx = text.index("Ana")
                return [DetectedEntity("PERSON", idx, idx + 9, 0.9, "Ana López")]
            return []

    db = await fresh_database(tmp_path, "narrative_subject.db")
    settings = SimpleNamespace(reports=SimpleNamespace(directory=str(tmp_path / "informes"), ttl_hours=24, logo_path=None))
    deps = Deps(db=db, llm=_NarrativeLLM(script), settings=settings)

    ctx = ToolContext(user=ADMIN, request_id=None, now=Q3_NOW, session_state={}, user_message="")
    presentation = {
        "type": "table",
        "title": "Ficha 360",
        "columns": ["Campo", "Valor"],
        "rows": [["Nombre", "Ana López"]],
    }
    summary = {"nombre": "Ana López", "departamento": "Pisos"}
    remember_table(ctx.session_state, presentation, 5000, summary)

    tool = generar(deps)
    result = await tool.handler(
        InformeParams(formato="html", incluir_detalle=True, incluir_grafico=True, incluir_narrativa=True), ctx
    )
    assert result.status is TS.OK
    report_id = result.summary["enlace"].rsplit("/", 1)[-1]
    from mia.data import Report
    from sqlalchemy import select

    async with db.session() as session:
        report = (await session.scalars(select(Report).where(Report.id == report_id))).one()
    html_text = Path(report.path).read_text(encoding="utf-8")
    assert "Ana López" in html_text
    assert "CONCLUSIÓN BLOQUEADA" not in html_text
    await db.dispose()


# ───────────────────────────────────────────────────── punto 5: extremo a extremo por dominio


async def test_shift_domain_end_to_end_through_chat_to_a_real_document(
    client: Any, services: Any, script: list
) -> None:
    """Turnos: ConversationEngine real → `ausencias` (datos sembrados reales) → `generar_informe` →
    documento real persistido."""
    await seed(services.db)

    def scripted(req: LLMRequest) -> list[LLMEvent]:
        from mia.llm.fake import final_answer  # noqa: PLC0415

        tool_rounds = [m for m in req.messages if m.role == "tool"]
        if not tool_rounds:
            return tool_call("ausencias", {"nombre": "Eva Sol", "desde": "2026-08-03", "hasta": "2026-08-06"})
        if len(tool_rounds) == 1:
            return tool_call("generar_informe", {"formato": "pdf"})
        return final_answer("Aquí tienes el informe de ausencias.", "Listo.")

    script[0] = scripted
    body = (
        await client.post("/api/chat", json={"message": "Informe de ausencias de Eva Sol la primera semana de agosto"})
    ).json()
    assert body["status"] == "ok"
    assert any(p.get("type") == "download" for p in body["presentations"])


async def test_vacation_domain_end_to_end_through_chat_to_a_real_document(
    client: Any, services: Any, script: list
) -> None:
    """Vacaciones: ConversationEngine real → `vacaciones` (solicitud sembrada real de Ana Ruiz) →
    `generar_informe` → documento real persistido."""
    await seed(services.db)

    def scripted(req: LLMRequest) -> list[LLMEvent]:
        from mia.llm.fake import final_answer  # noqa: PLC0415

        tool_rounds = [m for m in req.messages if m.role == "tool"]
        if not tool_rounds:
            return tool_call("vacaciones", {"desde": "2026-08-01", "hasta": "2026-08-31"})
        if len(tool_rounds) == 1:
            return tool_call("generar_informe", {"formato": "pdf"})
        return final_answer("Aquí tienes el informe de vacaciones.", "Listo.")

    script[0] = scripted
    body = (await client.post("/api/chat", json={"message": "Informe de vacaciones de agosto de 2026"})).json()
    assert body["status"] == "ok"
    assert any(p.get("type") == "download" for p in body["presentations"])


async def test_employee_domain_end_to_end_through_chat_to_a_real_document(
    client: Any, services: Any, script: list
) -> None:
    """Plantilla: ConversationEngine real → `plantilla` (empleados sembrados reales) →
    `generar_informe` → documento real persistido."""
    await seed(services.db)

    def scripted(req: LLMRequest) -> list[LLMEvent]:
        from mia.llm.fake import final_answer  # noqa: PLC0415

        tool_rounds = [m for m in req.messages if m.role == "tool"]
        if not tool_rounds:
            return tool_call("plantilla", {})
        if len(tool_rounds) == 1:
            return tool_call("generar_informe", {"formato": "pdf"})
        return final_answer("Aquí tienes el informe de plantilla.", "Listo.")

    script[0] = scripted
    body = (await client.post("/api/chat", json={"message": "Informe de la plantilla actual"})).json()
    assert body["status"] == "ok"
    assert any(p.get("type") == "download" for p in body["presentations"])


# Nóminas: ya cubierto de extremo a extremo (ConversationEngine real → analisis_economico_nominas →
# generar_informe_ejecutivo con redirección real → documento persistido con importes reales de agosto
# de 2026) por tests/test_report_routing_semantic_validation.py::
# test_incident_request_through_the_real_chat_entry_point_delivers_the_real_report — no se repite aquí.
