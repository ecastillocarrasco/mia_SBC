"""Contrato con el frontend actual: rutas y forma de respuesta."""

from __future__ import annotations

import json

import httpx


async def test_legacy_chat_shape(client: httpx.AsyncClient) -> None:
    for path in ("/api/mia/chat", "/api/mia/v4/chat"):
        response = await client.post(path, json={"message": "Hola", "context": {"cualquier": "cosa"}})
        assert response.status_code == 200
        body = response.json()
        assert {"status", "answer", "speech", "avatar_state", "data", "context", "meta"} <= body.keys()
        assert body["status"] == "ok"
        assert body["context"]["session_id"]
        assert "cualquier" not in body["context"]


async def test_legacy_context_carries_session(client: httpx.AsyncClient) -> None:
    first = (await client.post("/api/mia/chat", json={"message": "uno"})).json()
    second = (await client.post("/api/mia/chat", json={"message": "dos", "context": first["context"]})).json()
    assert second["context"]["session_id"] == first["context"]["session_id"]


async def test_legacy_stream_is_ndjson_with_result(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/mia/chat/stream", json={"message": "Hola"})
    assert response.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert lines[-1]["type"] == "result"
    assert lines[-1]["payload"]["answer"] == "Hola, soy mIA."


async def test_legacy_version_and_health(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/version")).json()["status"] == "ok"
    assert (await client.get("/api/mia/v4/health")).json()["assistant_identity"] == "mIA"


async def test_voice_unavailable_is_503(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/mia/voice", json={"text": "Hola"})
    assert response.status_code == 503


async def test_legacy_report_buttons_return_a_file(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/mia/informes/generar", json={"modulo": "dashboard_rrhh", "formato": "excel"})
    assert response.status_code == 200
    assert "spreadsheetml" in response.headers["content-type"]
    bad = await client.post("/api/mia/informes/generar", json={"modulo": "inventado", "formato": "pdf"})
    assert bad.status_code == 400
