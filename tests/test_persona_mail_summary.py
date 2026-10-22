"""Regresión real reportada por el usuario: "resúmeme mis correos sin leer" o "los últimos 10
recibidos" respondía "ahí está la tabla, mira el detalle" en vez de un resumen de verdad. Causa:
la regla general "no repitas una tabla que ya se ve en pantalla" (pensada para listados largos de
empleados) se aplicaba también al correo, donde la tabla NUNCA trae de qué trata cada mensaje.
"""

from __future__ import annotations

from mia.conversation.persona import Persona


def test_system_prompt_requires_a_real_mail_summary_not_just_pointing_at_the_table() -> None:
    prompt = Persona().system_prompt(business_rules=[])
    assert "resúmeme los correos" in prompt
    assert "resumen REAL de cada correo" in prompt
    # La regla debe decir explícitamente que la general de "no repitas la tabla" no aplica aquí.
    assert "NO aplica aquí" in prompt
