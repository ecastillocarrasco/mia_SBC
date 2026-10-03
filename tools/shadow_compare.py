"""Modo sombra en local: las mismas conversaciones reales a los dos sistemas, respuesta a respuesta.

El sistema anterior no guardó el texto de sus respuestas, así que la única forma de probar
la paridad es preguntar a la vez al antiguo y al nuevo. Requiere los dos arrancados:

    # ANTES de comparar, sincroniza mIA (el antiguo lee SharePoint en vivo; mIA, su última sincronización):
    #   python -m mia.sync
    # sistema anterior, como siempre: python avatar_backend_mia.py (5001) + su gateway: python mIA_LLM_CHAT_V4.py (5002)
    # sistema nuevo en otros puertos:  $env:MIA_PORT=5201; $env:MIA_COMPAT_PORT=5202; python -m mia
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
TECH_ERROR = re.compile(r"(?i)error\s+t[eé]cnico|problema\s+t[eé]cnico")
NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?(?![\w])")


def figures(text: str) -> set[str]:
    """Cifras relevantes de una respuesta (sin fechas ni horas, que cambian de formato entre sistemas)."""
    clean = DATES.sub(" ", text or "")
    return {
        n.replace(",", ".").rstrip("0").rstrip(".") if "." in n.replace(",", ".") else n for n in NUMBER.findall(clean)
    }


def asks_back(text: str) -> bool:
    """Pide una aclaración en vez de responder (sin cifras y terminando en pregunta)."""
    return not figures(text) and text.strip().endswith("?")


def classify(old: str, new: str) -> str:
    old_cannot, new_cannot = bool(CANNOT.search(old)), bool(CANNOT.search(new))
    if not old_cannot and new_cannot:
        return "solo_antiguo"
    if old_cannot and not new_cannot:
        return "solo_nuevo"
    if asks_back(old) != asks_back(new):
        return "antiguo_pide_aclaracion" if asks_back(old) else "nuevo_pide_aclaracion"
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


def main() -> int:  # noqa: PLR0915  (guion secuencial de la comparación)
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
    # Comprobación previa: si el antiguo no lee SharePoint, la comparación no vale nada.
    probe = legacy.ask("¿Cuántos empleados activos hay?")
    legacy.reset()
    if not figures(probe) or re.search(r"(?i)\b0\s+(empleados|personas)|no\s+encuentro", probe):
        print("El sistema ANTERIOR no está devolviendo datos de la plantilla:", file=sys.stderr)
        print(f"  «{probe[:300]}»", file=sys.stderr)
        print(
            "Revisa su .env (MIA_CLIENT_ID, MIA_CERT_PFX_PATH, MIA_CERT_PFX_PASSWORD, MIA_TENANT_ID) y la consola de",
            "su backend. Comparación cancelada.",
            file=sys.stderr,
        )
        return 3
    print(f"Sistema anterior leyendo datos: «{probe[:120]}»")
    new_probe = new.ask("¿Cuántos empleados activos hay?")
    new.reset()
    if not figures(new_probe) or TECH_ERROR.search(new_probe):
        print("mIA nueva no está respondiendo con datos:", file=sys.stderr)
        print(f"  «{new_probe[:300]}»", file=sys.stderr)
        print(
            "Revisa la consola de mIA (error completo), el espacio en disco y la conexión con OpenAI.", file=sys.stderr
        )
        return 4
    print(f"mIA nueva respondiendo: «{new_probe[:120]}»")
    results: list[dict[str, Any]] = []
    conversations = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.domain:
        conversations = [c for c in conversations if any(t.get("domain") == args.domain for t in c["turns"])]
    consecutive_errors = 0
    for n, conversation in enumerate(conversations[: args.limit], 1):
        if consecutive_errors >= 5:
            break
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
            consecutive_errors = consecutive_errors + 1 if TECH_ERROR.search(new_answer) else 0
            if consecutive_errors >= 5:
                print("\nmIA ha fallado 5 veces seguidas con «error técnico»: comparación detenida.", file=sys.stderr)
                print("Revisa su consola; el informe incluye lo comparado hasta aquí.", file=sys.stderr)
                break
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
            for k in (
                "coinciden",
                "difieren",
                "solo_antiguo",
                "solo_nuevo",
                "antiguo_pide_aclaracion",
                "nuevo_pide_aclaracion",
                "sin_cifras",
                "error",
            )
        ],
        "",
    ]
    for kind, title in (
        ("solo_antiguo", "El antiguo responde y el nuevo no (posibles huecos)"),
        ("difieren", "Cifras distintas (revisar cuál es la correcta)"),
        ("nuevo_pide_aclaracion", "mIA pide aclaración donde el antiguo respondía"),
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
