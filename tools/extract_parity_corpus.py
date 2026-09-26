"""Extrae la batería de paridad a partir de la base del sistema anterior.

Uso:
    python tools/extract_parity_corpus.py RUTA/mia_runtime.sqlite3

Genera en ``tests/parity/corpus/`` (excluido de git porque contiene datos
personales):

* ``conversations.jsonl``: una conversación por línea, con cada pregunta del
  usuario, el dominio, el ejecutor que la resolvió, su estado y su latencia.
* ``questions.jsonl``: preguntas únicas con su frecuencia, para priorizar.
* ``summary.md``: resumen por dominio y ejecutor.

El sistema anterior no guardaba el texto literal, sino la versión normalizada
(minúsculas y sin tildes); es suficiente para reproducir la intención.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parents[1] / "tests" / "parity" / "corpus"


def _json(value: str | None) -> dict[str, Any]:
    try:
        data = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def extract(db_path: Path) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    plans = {
        row[0]: row[1]
        for row in con.execute("SELECT request_id, primary_domain FROM query_plans WHERE request_id NOT NULL")
    }
    executions: dict[str, tuple[str, str, float]] = {}
    query = (
        "SELECT request_id, executor, status, elapsed_ms FROM execution_log_v12 WHERE request_id IS NOT NULL"
    )
    for request_id, executor, status, elapsed in con.execute(query):
        executions[request_id] = (executor, status, float(elapsed or 0))

    sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows = con.execute(
        "SELECT session_id, request_id, role, semantic_json, created_at FROM conversation_turns "
        "ORDER BY session_id, created_at"
    )
    pending: dict[str, dict[str, Any]] = {}
    for session_id, request_id, role, semantic_json, created_at in rows:
        semantic = _json(semantic_json)
        if role == "user":
            text = str(semantic.get("normalized") or "").strip()
            if not text:
                continue
            turn = {
                "question": text,
                "domain": (semantic.get("domains") or [None])[0],
                "references_previous": bool(semantic.get("references_previous")),
                "executor": None,
                "status": None,
                "elapsed_ms": None,
                "created_at": created_at,
            }
            sessions[session_id].append(turn)
            pending[session_id] = turn
        elif role == "assistant" and session_id in pending:
            # En el sistema anterior el request_id solo se guardaba en el turno de respuesta.
            turn = pending.pop(session_id)
            turn["legacy_intent"] = semantic.get("intent")
            executor, status, elapsed = executions.get(request_id, (None, None, None))
            turn.update(executor=executor, status=status, elapsed_ms=elapsed)
            turn["domain"] = plans.get(request_id) or turn["domain"]
    con.close()

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "conversations.jsonl").open("w", encoding="utf-8") as fh:
        for session_id, turns in sessions.items():
            fh.write(json.dumps({"session": session_id, "turns": turns}, ensure_ascii=False) + "\n")

    questions = Counter(t["question"] for turns in sessions.values() for t in turns)
    domain_of: dict[str, str | None] = {}
    for turns in sessions.values():
        for t in turns:
            domain_of.setdefault(t["question"], t["domain"])
    with (OUT / "questions.jsonl").open("w", encoding="utf-8") as fh:
        for question, count in questions.most_common():
            record = {"question": question, "count": count, "domain": domain_of.get(question)}
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    all_turns = [t for turns in sessions.values() for t in turns]
    by_domain = Counter(t["domain"] or "sin_dominio" for t in all_turns)
    by_status = Counter(t["status"] or "sin_registro" for t in all_turns)
    latency: dict[str, list[float]] = defaultdict(list)
    for t in all_turns:
        if t["executor"] and t["elapsed_ms"] is not None:
            latency[t["executor"]].append(t["elapsed_ms"])
    multi = sum(1 for turns in sessions.values() if len(turns) > 1)
    followups = sum(1 for t in all_turns if t["references_previous"])

    lines = [
        "# Batería de paridad · resumen",
        "",
        f"- Conversaciones: {len(sessions)} ({multi} con más de un turno)",
        f"- Preguntas: {len(all_turns)} ({len(questions)} únicas)",
        f"- Preguntas que dependen del contexto anterior: {followups}",
        "",
        "## Por dominio",
        "",
        "| Dominio | Preguntas |",
        "|---|---|",
        *[f"| {d} | {n} |" for d, n in by_domain.most_common()],
        "",
        "## Por estado en el sistema anterior",
        "",
        "| Estado | Preguntas |",
        "|---|---|",
        *[f"| {s} | {n} |" for s, n in by_status.most_common()],
        "",
        "## Latencia por ejecutor (sistema anterior)",
        "",
        "| Ejecutor | n | p50 ms | p90 ms |",
        "|---|---|---|---|",
    ]
    for executor, values in sorted(latency.items(), key=lambda kv: -len(kv[1]))[:20]:
        values.sort()
        p90 = values[min(len(values) - 1, int(0.9 * len(values)))]
        lines.append(f"| {executor} | {len(values)} | {statistics.median(values):.0f} | {p90:.0f} |")
    (OUT / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "sessions": len(sessions),
        "questions": len(all_turns),
        "unique": len(questions),
        "multi_turn": multi,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("database", type=Path, help="Ruta a mia_runtime.sqlite3 del sistema anterior")
    args = parser.parse_args()
    stats = extract(args.database)
    print(json.dumps(stats, ensure_ascii=False))
    print(f"Corpus generado en {OUT}")


if __name__ == "__main__":
    main()
