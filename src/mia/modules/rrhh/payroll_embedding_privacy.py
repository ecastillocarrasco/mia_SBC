"""Representacion de nominas minimizada para embeddings externos.

Regla de seguridad: NUNCA reutilizar extractos ni valores originales en el payload
para embeddings. Solo se construye texto desde un vocabulario fijo y auditado.
Los textos originales siguen disponibles en PostgreSQL bajo sus ACL habituales.

La deteccion por palabras clave es deliberadamente conservadora: ciertos conceptos
raros, diagnosticos medicos, embargos, personas, fechas, departamentos, cuantias y
referencias de documentos no aparecen nunca en la salida.
"""

from __future__ import annotations

import re
import unicodedata

# Version explicita para reconocer documentos procesados desde esta politica.
PAYROLL_EMBEDDING_POLICY_VERSION = "nominas_min_v1"

# Solo se incluyen categorias habituales, no conceptos medicos, juridicos o
# individualizadores. Los patrones normalizados son subcadenas de palabras enteras.
_CONCEPTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("salario base", ("salario base", "sueldo base")),
    ("salario bruto", ("salario bruto", "total devengado", "total devengos")),
    ("salario neto", ("salario neto", "liquido a percibir", "total liquido", "neto a percibir")),
    ("cotizaciones sociales", ("cotizacion", "cotizaciones", "seguridad social", "contingencias comunes")),
    ("retenciones fiscales", ("irpf", "i r p f", "retencion fiscal", "retenciones fiscales")),
    ("deducciones", ("deduccion", "deducciones", "total a deducir")),
    ("pagas extraordinarias", ("paga extra", "pagas extras", "paga extraordinaria", "pagas extraordinarias", "prorrata de pagas")),
    ("complementos salariales", ("complemento salarial", "complementos salariales", "plus salarial")),
    ("horas extraordinarias", ("horas extras", "horas extraordinarias")),
)

_BASE = "Documento laboral: nomina. Contenido retributivo general sin datos individuales."
_FOOTER = "Se excluyen importes, identificadores, fechas, departamentos y detalles personales."


def _normalized_words(text: str) -> str:
    ascii_text = "".join(
        char for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )
    return " " + re.sub(r"[^a-z0-9]+", " ", ascii_text).strip() + " "


def project_payroll_embedding(text: str) -> str:
    """Devuelve exclusivamente un resumen de vocabulario permitido.

    No copia ninguna parte de `text` al resultado. Aunque Presidio no detecte
    un identificador, un importe o un prompt inyectado, no podran salir por esta
    funcion. Si el texto no contiene categorias reconocidas, devuelve solo
    una descripcion generica para que el documento siga pudiendo indexarse.
    """
    words = _normalized_words(text)
    found = [
        concept
        for concept, variants in _CONCEPTS
        if any(f" {variant} " in words for variant in variants)
    ]
    concepts = "; ".join(found) if found else "conceptos generales de nomina"
    return f"{_BASE} Conceptos: {concepts}. {_FOOTER}"
