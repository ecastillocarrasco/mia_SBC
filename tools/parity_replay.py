"""Reproduce conversaciones reales del sistema anterior contra mIA.

Uso (con mIA arrancada, LLM real y datos sincronizados):
    python tools/parity_replay.py --limit 40
    python tools/parity_replay.py --domain vacaciones --limit 20

Lee ``tests/parity/corpus/conversations.jsonl`` (generado con
extract_parity_corpus.py), reproduce cada conversación turno a turno en una
sesión nueva y escribe un informe en ``tests/parity/corpus/replay.md`` para
revisarlo a mano. El informe contiene datos personales: no sale del equipo.

Señales que marca como sospechosas:
* la pregunta es de un dominio con datos pero no se usó ninguna herramienta;
* una herramienta terminó en error o fuente no disponible;
* la respuesta tardó más de 8 segundos.
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

CORPUS = Path(__file__).resolve().parents[1] / "tests" / "parity" / "corpus"
DATA_DOMAINS = {"empleados", "departamentos", "turnos", "vacaciones", "saldo_vacaciones"}
SLOW_MS = 8000


def _conversations(domain: str | None, limit: int) -> list[dict[str, Any]]:
    selected = []
    with (CORPUS / "conversations.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            conv = json.loads(line)
            domains = {t.get("domain") for t in conv["turns"]}
            if not domains & DATA_DOMAINS or (domain and domain not in domains):
                continue
            selected.append(conv)
    # Conversaciones de 2 a 8 turnos primero (prueban el foco); las sesiones larguísimas
    # suelen ser baterías de QA del sistema anterior y se dejan para el final.
    selected.sort(key=lambda c: (not 2 <= len(c["turns"]) <= 8, -len(c["turns"])))
    return selected[:limit]


@dataclass
class TurnResult:
    lines: list[str]
    flagged: bool
    session_id: str | None = None
    elapsed: int | None = None
    failed: bool = False
    used_tool: bool = False


def _replay_turn(
    client: httpx.Client, turn: dict[str, Any], session_id: str | None, previous_used_tool: bool
) -> TurnResult:
    payload: dict[str, Any] = {"message": turn["question"]}
    if session_id:
        payload["session_id"] = session_id
    try:
        response = client.post("/api/chat", json=payload)
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        error = f"⚠️ error de conexión: {type(exc).__name__}: {exc}"
        return TurnResult([f"**{turn['question']}**  ", error, ""], flagged=True, failed=True)
    tools = body.get("tools", [])
    elapsed = int(body.get("elapsed_ms", 0))
    flags = []
    notes = []
    if response.status_code >= 400 or body.get("status") == "error":
        flags.append(f"respuesta de error ({response.status_code})")
    if turn.get("domain") in DATA_DOMAINS and not tools:
        # Un seguimiento («¿cuántos son?») puede contestarse con el resultado anterior.
        (notes if previous_used_tool else flags).append("sin herramienta")
    if any(t["status"] in {"error", "source_unavailable"} for t in tools):
        flags.append("error de herramienta")
    if elapsed > SLOW_MS:
        flags.append("lenta")
    mark = "⚠️ " + ", ".join(flags) if flags else ("ℹ️ seguimiento " + ", ".join(notes) if notes else "✅")
    tool_names = ", ".join(f"{t['name']}:{t['status']}" for t in tools) or "—"
    lines = [
        f"**{turn['question']}**  ",
        f"{mark} · {elapsed} ms · herramientas: {tool_names}  ",
        f"> {str(body.get('answer', '')).strip()[:400]}",
        "",
    ]
    result = TurnResult(lines, bool(flags), body.get("session_id"), elapsed)
    result.used_tool = bool(tools)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:5001")
    parser.add_argument("--limit", type=int, default=30, help="número de conversaciones")
    parser.add_argument("--domain", default=None)
    args = parser.parse_args()

    conversations = _conversations(args.domain, args.limit)
    lines = ["# Reproducción de conversaciones reales", ""]
    latencies: list[int] = []
    flagged = 0
    consecutive_errors = 0
    with httpx.Client(base_url=args.url, timeout=90) as client:
        try:
            client.get("/health/live").raise_for_status()
        except httpx.HTTPError:
            raise SystemExit(
                f"mIA no responde en {args.url}: arráncala con «python -m mia» en otra ventana."
            ) from None
        for n, conv in enumerate(conversations, 1):
            session_id = None
            used_tool = False
            lines.append(f"## Conversación {n}")
            for turn in conv["turns"]:
                result = _replay_turn(client, turn, session_id, used_tool)
                lines += result.lines
                flagged += result.flagged
                if result.elapsed is not None:
                    latencies.append(result.elapsed)
                if result.failed:
                    consecutive_errors += 1
                    if consecutive_errors >= 3:
                        lines.append("_Reproducción detenida: el servidor no responde (revisa su consola)._")
                        print("\nEl servidor ha dejado de responder: revisa la consola de mIA.")
                        break
                    continue
                consecutive_errors = 0
                session_id = result.session_id
                used_tool = used_tool or result.used_tool
            if consecutive_errors >= 3:
                break
            print(f"{n}/{len(conversations)} conversaciones", end="\r")
    turns = len(latencies)
    p90 = sorted(latencies)[int(0.9 * (turns - 1))] if latencies else 0
    header = [
        f"- Conversaciones: {len(conversations)} · turnos: {turns}",
        f"- Turnos marcados para revisar: {flagged}",
        f"- Latencia p50: {int(statistics.median(latencies)) if latencies else 0} ms · p90: {p90} ms",
        "",
    ]
    lines[2:2] = header
    out = CORPUS / "replay.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(header))
    print(f"Informe: {out}")


if __name__ == "__main__":
    main()
