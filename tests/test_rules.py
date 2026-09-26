from __future__ import annotations

from datetime import UTC, datetime

from mia.conversation import Persona
from mia.rules import RULES, rule, rules_for_prompt


def test_rule_ids_are_unique() -> None:
    ids = [r.id for r in RULES]
    assert len(ids) == len(set(ids))


def test_rules_reach_the_prompt() -> None:
    text = "\n".join(rules_for_prompt())
    assert "[POB-001]" in text
    assert "activos por defecto" in rule("POB-001").statement


def test_persona_forbids_unkeepable_promises() -> None:
    prompt = Persona().system_prompt(user_name="Enrique", now=datetime.now(UTC), business_rules=[])
    assert "No prometas lo que no puedes hacer" in prompt
    assert "no la repitas" in prompt
