"""Aceptación E2E por SSE y descargas reales; no registra respuestas ni credenciales."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import Any
from urllib.parse import urlsplit

import httpx

SUITE = Path(__file__).resolve().parents[1] / "tests/evals/acceptance_orchestration.json"
MONEY = re.compile(r"\d[\d.,]*\s*(?:€|euros?\b)", re.IGNORECASE)
REPORT_URL = re.compile(r"/api/reports/[a-fA-F0-9]{32}\Z")


def successful_tools(result: dict[str, Any]) -> set[str]:
    return {item["name"] for item in result.get("tools", []) if item.get("status") == "ok"}


def downloads(result: dict[str, Any]) -> dict[str, str]:
    found: dict[str, str] = {}
    for presentation in result.get("presentations", []):
        if presentation.get("type") not in {"download", "downloads"}:
            continue
        items = presentation.get("items", []) if presentation.get("type") == "downloads" else [presentation]
        for item in items:
            if item.get("format") and REPORT_URL.fullmatch(item.get("url", "")):
                found[item["format"]] = item["url"]
    return found


def check_result(result: dict[str, Any], stages: set[str], spec: dict[str, Any], bindings: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    tools = successful_tools(result)
    if result.get("status") != spec.get("status", "ok"):
        problems.append("estado_de_tarea")
    if not set(spec.get("tools_all", [])).issubset(tools):
        problems.append("herramientas_requeridas")
    if spec.get("tools_any") and not tools.intersection(spec["tools_any"]):
        problems.append("sin_fuente_esperada")
    if tools.intersection(spec.get("forbidden_tools", [])):
        problems.append("herramienta_no_autorizada")
    if spec.get("require_plan") and "planning" not in stages:
        problems.append("sin_plan_explicito")
    if MONEY.search(result.get("speech", "")):
        problems.append("importe_en_voz")
    if spec.get("refusal") and not re.search(
        r"no (?:puedo|tengo|tienes|dispongo|hay|est[aá]|se puede|se ha encontrado)"
        r"|sin (?:acceso|permiso)|no disponible|pendiente",
        result.get("answer", ""),
        re.I,
    ):
        problems.append("sin_limitacion_explicita")
    if spec.get("must_match") and not re.search(spec["must_match"], result.get("answer", ""), re.I):
        problems.append("respuesta_no_cumple_criterio")
    for reference in spec.get("summary_references", []):
        expected = bindings[reference["reference"]]
        summaries = [
            item.get("summary", {}) for item in result.get("summaries", []) if item.get("tool") == reference["tool"]
        ]
        if not any(summary.get(reference["key"]) == expected for summary in summaries):
            problems.append("dato_no_coincide_con_referencia")
    if not set(spec.get("formats", [])).issubset(downloads(result)):
        problems.append("formatos_pendientes")
    return problems


async def stream_turn(client: httpx.AsyncClient, prompt: str, session: str | None) -> tuple[dict[str, Any], set[str]]:
    result: dict[str, Any] | None = None
    stages: set[str] = set()
    async with client.stream("POST", "/api/chat/stream", json={"message": prompt, "session_id": session}) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            if event.get("type") == "progress":
                stages.add(event.get("stage", ""))
            if event.get("type") == "speech" and not event.get("filler") and MONEY.search(event.get("text", "")):
                stages.add("importe_en_stream")
            if event.get("type") == "result":
                if result is not None:
                    raise ValueError("resultado_duplicado")
                result = event["result"]
    if result is None:
        raise ValueError("stream_sin_resultado_final")
    return result, stages


async def check_downloads(
    client: httpx.AsyncClient,
    result: dict[str, Any],
    formats: list[str],
    expected_table: dict[str, Any] | None = None,
) -> list[str]:
    problems: list[str] = []
    links = downloads(result)
    signatures = {"pdf": b"%PDF", "xlsx": b"PK", "docx": b"PK", "pptx": b"PK"}
    for fmt in formats:
        if fmt not in links:
            continue
        response = await client.get(links[fmt])
        if response.status_code != 200 or not response.content:
            problems.append(f"descarga_{fmt}_fallida")
        elif fmt in signatures and not response.content.startswith(signatures[fmt]):
            problems.append(f"contenido_{fmt}_incorrecto")
        elif fmt == "html" and b"<html" not in response.content.lower():
            problems.append("contenido_html_incorrecto")
        else:
            from mia.reporting.document import Block, Document  # noqa: PLC0415 — lectura solo al verificar archivos
            from mia.reporting.verification import ReportVerificationError, verify_artifact  # noqa: PLC0415

            # La lectura real detecta archivos corruptos que conservan una firma ZIP/PDF.
            # Los valores contra referencias empresariales se verifican por separado.
            blocks = [Block("section", "Lectura", {})]
            if expected_table is not None:
                blocks = [Block("table", "Resultado original", expected_table)]
            probe = Document("Lectura de archivo", blocks)
            try:
                verify_artifact(fmt, response.content, probe)
            except ReportVerificationError:
                suffix = "no_coincide_con_origen" if expected_table is not None else "ilegible"
                problems.append(f"archivo_{fmt}_{suffix}")
    return problems


def missing_bindings(case: dict[str, Any], bindings: dict[str, Any]) -> set[str]:
    required = set(case.get("requires", []))
    for turn in case["turns"]:
        required.update(Template(turn["prompt"]).get_identifiers())
        required.update(item["reference"] for item in turn.get("summary_references", []))
    return required - bindings.keys()


async def run_case(
    case: dict[str, Any], url: str, bindings: dict[str, Any], tokens: dict[str, str] | None = None
) -> dict[str, Any]:
    profile = case.get("profile", "global")
    token = (tokens or {}).get(profile) or os.environ.get(f"MIA_EVAL_TOKEN_{profile.upper()}")
    if missing_bindings(case, bindings) or not token or case.get("manual"):
        return {"id": case["id"], "status": "pending", "reason": "requiere_contexto_identidad_o_comprobacion_manual"}
    errors: list[str] = []
    session = None
    previous_table = None
    try:
        async with httpx.AsyncClient(
            base_url=url, headers={"Authorization": f"Bearer {token}"}, timeout=180, follow_redirects=False
        ) as client:
            for index, spec in enumerate(case["turns"]):
                prompt = Template(spec["prompt"]).substitute(bindings)
                result, stages = await stream_turn(client, prompt, session)
                session = result["session_id"]
                issues = check_result(result, stages, spec, bindings)
                if spec.get("verify_previous_table") and previous_table is None:
                    issues.append("sin_tabla_origen_para_verificar")
                issues += await check_downloads(
                    client,
                    result,
                    spec.get("formats", []),
                    previous_table if spec.get("verify_previous_table") else None,
                )
                tables = [item for item in result.get("presentations", []) if item.get("type") == "table"]
                if len(tables) == 1:
                    previous_table = {key: tables[0][key] for key in ("columns", "rows")}
                if "importe_en_stream" in stages:
                    issues.append("importe_en_stream")
                errors += [f"turno_{index + 1}:{issue}" for issue in issues]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        errors.append(type(exc).__name__)  # nunca imprimir cuerpo HTTP, prompt, sesión o token
    status = "failed" if errors else "review" if case.get("review_required") else "passed"
    return {"id": case["id"], "status": status, "checks_failed": errors}


def question_list(cases: list[dict[str, Any]]) -> str:
    lines = ["# Suite E2E de mIA", "", "Cada caso usa una sesión nueva; los turnos numerados mantienen contexto.", ""]
    for case in cases:
        lines += [f"## {case['id']} · {case['title']}", "", f"Perfil: {case.get('profile', 'global')}.", ""]
        lines += [f"{index}. {turn['prompt']}" for index, turn in enumerate(case["turns"], 1)]
        mode = (
            "Manual" if case.get("manual") else "Automático + revisión" if case.get("review_required") else "Automático"
        )
        lines += ["", f"Criterio: {case['acceptance']}", "", f"Validación: {mode}.", ""]
    return "\n".join(lines)


def interactive_token() -> str:
    import msal  # noqa: PLC0415 — solo se inicializa si se solicita login interactivo

    from mia.settings import get_settings  # noqa: PLC0415 — configuración existente, sin imprimir secretos

    settings = get_settings()
    if not all((settings.auth.entra_tenant_id, settings.auth.entra_desktop_client_id, settings.auth.entra_scope)):
        raise ValueError("configuracion_entra_incompleta")
    app = msal.PublicClientApplication(
        client_id=settings.auth.entra_desktop_client_id,
        authority=f"https://login.microsoftonline.com/{settings.auth.entra_tenant_id}",
    )
    result = app.acquire_token_interactive(scopes=[settings.auth.entra_scope], timeout=180, prompt="select_account")
    token = result.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("login_no_completado")
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=SUITE)
    parser.add_argument("--url")
    parser.add_argument("--bindings", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--profile", help="Ejecutar únicamente los casos del perfil indicado")
    parser.add_argument("--case", action="append", dest="case_ids", help="Limitar a uno o varios IDs de caso")
    parser.add_argument("--login", action="store_true", help="Login Entra interactivo; token solo en memoria")
    args = parser.parse_args()
    cases = json.loads(args.suite.read_text(encoding="utf-8"))["cases"]
    if args.profile:
        cases = [case for case in cases if case.get("profile", "global") == args.profile]
    if args.case_ids:
        cases = [case for case in cases if case["id"] in args.case_ids]
    if not cases:
        parser.error("No hay casos para el perfil solicitado.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.list:
        args.output.write_text(question_list(cases), encoding="utf-8")
        return 0
    target = urlsplit(args.url or "")
    if (
        target.scheme not in {"http", "https"}
        or not target.hostname
        or target.username
        or target.password
        or target.query
        or target.fragment
    ):
        parser.error("Indica --url con la URL base de dev, sin credenciales ni parámetros.")
    if target.scheme == "http" and target.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Solo se permite HTTP sin TLS para el dev local.")
    bindings = json.loads(args.bindings.read_text(encoding="utf-8")) if args.bindings else {}
    tokens: dict[str, str] = {}
    if args.login:
        if not args.profile:
            parser.error("El login requiere --profile; nunca se reutiliza una identidad para otros roles.")
        try:
            tokens[args.profile] = interactive_token()
        except Exception as exc:
            # Solo el tipo local: ni el mensaje de Entra ni su respuesta pueden
            # acabar en los logs, porque pueden contener datos de la identidad.
            parser.exit(2, f"Login Entra no completado ({type(exc).__name__}). No se han ejecutado casos.\n")

    started = datetime.now(UTC).isoformat()
    report = {
        "started_at_utc": started,
        "suite_sha256": hashlib.sha256(args.suite.read_bytes()).hexdigest(),
        "reference_sha256": hashlib.sha256(args.bindings.read_bytes()).hexdigest() if args.bindings else None,
        "profile": args.profile,
        "runtime_revision_verified": False,
        "execution_complete": False,
        "results": [],
    }

    async def execute() -> list[dict[str, Any]]:
        results = []
        for case in cases:
            result = await run_case(case, args.url, bindings, tokens)
            results.append(result)
            report["results"] = results
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{result['id']}: {result['status']}", flush=True)
        return results

    results = asyncio.run(execute())
    report["execution_complete"] = True
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(item["status"] == "passed" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
