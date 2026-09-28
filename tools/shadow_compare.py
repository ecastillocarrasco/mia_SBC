"""Modo sombra en local: las mismas conversaciones reales a los dos sistemas, respuesta a respuesta.

El sistema anterior no guardó el texto de sus respuestas, así que la única forma de probar
la paridad es preguntar a la vez al antiguo y al nuevo. Requiere los dos arrancados:

    # sistema anterior, como siempre: python mia_backend.py (5001) + su gateway (5002)
    # sistema nuevo en otros puertos:  $env:MIA_PORT=5201; $env:MIA_COMPAT_PORT=""; python -m mia
    python tools/shadow_compare.py --limit 60

Clasifica cada pregunta:
  coinciden     ambos responden y dan las mismas cifras
  difieren      ambos responden con cifras distintas            → revisar
  solo_antiguo  el antiguo responde y el nuevo no puede         → posible hueco de paridad
  solo_nuevo    el nuevo responde y el antiguo no podía         → mejora
  sin_cifras    ambos responden sin cifras (revisión manual opcional)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

CORPUS = Path(__file__).resolve().parents[1] / "tests" / "parity" / "corpus"
CANNOT = re.compile(
    r"(?i)no\s+(puedo|dispongo|tengo\s+acceso|est[aá]\s+disponible|he\s+podido|encuentro\s+(esa|la)\s+informaci)"
    r"|todav[ií]a\s+no\s+(puedo|est[aá])|fuera\s+de\s+mi\s+alcance|problema\s+t[eé]cnico"
)
DATES = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}\b")
NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?(?![\w])")


def figures(text: str) -> set[str]:
    """Cifras relevantes de una respuesta (sin fechas ni horas, que cambian de formato entre sistemas)."""
    clean = DATES.sub(" ", text or "")
    return {
        n.replace(",", ".").rstrip("0").rstrip(".") if "." in n.replace(",", ".") else n for n in NUMBER.findall(clean)
    }


def classify(old: str, new: str) -> str:
    old_cannot, new_cannot = bool(CANNOT.search(old)), bool(CANNOT.search(new))
    if not old_cannot and new_cannot:
        return "solo_antiguo"
    if old_cannot and not new_cannot:
        return "solo_nuevo"
    a, b = figures(old), figures(new)
    if not a and not b:
        return "sin_cifras"
    return "coinciden" if a == b else "difieren"


class Legacy:
    def __init__(self, url: str, path: str) -> None:
        self.http = httpx.Client(base_url=url, timeout=120)
        self.path = path
        self.context: dict[str, Any] = {}

    def reset(self) -> None:
        self.context = {}

    def ask(self, question: str) -> str:
        body = self.http.post(self.path, json={"message": question, "context": self.context}).json()
        if isinstance(body.get("context"), dict):
            self.context = body["context"]
        return str(body.get("answer") or body.get("response") or body.get("message") or "")


class New:
    def __init__(self, url: str) -> None:
        self.http = httpx.Client(base_url=url, timeout=120)
        self.session: str | None = None

    def reset(self) -> None:
        self.session = None

    def ask(self, question: str) -> str:
        body = self.http.post("/api/chat", json={"message": question, "session_id": self.session}).json()
        self.session = body.get("session_id")
        return str(body.get("answer") or "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--legacy-url", default="http://127.0.0.1:5002", help="gateway del sistema anterior")
    parser.add_argument(
        "--legacy-path", default="/api/mia/v4/chat", help="ruta de chat del antiguo (la que usaba el frontend)"
    )
    parser.add_argument("--new-url", default="http://127.0.0.1:5201")
    parser.add_argument("--limit", type=int, default=60, help="conversaciones a reproducir")
    parser.add_argument("--domain", help="solo un dominio (turnos, vacaciones, nominas…)")
    args = parser.parse_args()
    source = CORPUS / "conversations.jsonl"
    if not source.exists():
        print("Falta el corpus: ejecuta antes tools/extract_parity_corpus.py", file=sys.stderr)
        return 2
    legacy, new = Legacy(args.legacy_url, args.legacy_path), New(args.new_url)
    results: list[dict[str, Any]] = []
    conversations = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.domain:
        conversations = [c for c in conversations if any(t.get("domain") == args.domain for t in c["turns"])]
    for n, conversation in enumerate(conversations[: args.limit], 1):
        legacy.reset()
        new.reset()
        for turn in conversation["turns"]:
            question = turn["question"]
            try:
                old_answer, new_answer = legacy.ask(question), new.ask(question)
            except (httpx.HTTPError, ValueError) as exc:
                results.append({"conv": n, "question": question, "kind": "error", "old": "", "new": str(exc)})
                continue
            kind = classify(old_answer, new_answer)
            results.append(
                {
                    "conv": n,
                    "question": question,
                    "kind": kind,
                    "old": old_answer,
                    "new": new_answer,
                    "domain": turn.get("domain"),
                }
            )
        print(f"\r{n}/{min(args.limit, len(conversations))} conversaciones", end="", flush=True)
    print()
    counts = Counter(r["kind"] for r in results)
    lines = [
        "# Modo sombra: sistema anterior frente a mIA",
        "",
        *[
            f"- **{k}**: {counts.get(k, 0)}"
            for k in ("coinciden", "difieren", "solo_antiguo", "solo_nuevo", "sin_cifras", "error")
        ],
        "",
    ]
    for kind, title in (
        ("solo_antiguo", "El antiguo responde y el nuevo no (posibles huecos)"),
        ("difieren", "Cifras distintas (revisar cuál es la correcta)"),
        ("error", "Errores"),
    ):
        rows = [r for r in results if r["kind"] == kind]
        if not rows:
            continue
        lines += [f"## {title}", ""]
        for r in rows:
            lines += [
                f"**{r['question']}** · conv. {r['conv']} · {r.get('domain') or '—'}",
                f"> antiguo: {r['old'][:400]}",
                f"> nuevo: {r['new'][:400]}",
                "",
            ]
    report = CORPUS / "shadow.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:9]))
    print(f"Informe: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
