from __future__ import annotations

import json

from mia.conversation.speech import SpeechExtractor


def _feed_in_chunks(payload: str, size: int) -> list[str]:
    extractor = SpeechExtractor()
    out: list[str] = []
    for i in range(0, len(payload), size):
        out.extend(extractor.feed(payload[i : i + size]))
    out.extend(extractor.finish())
    return out


def test_emits_sentences_as_they_complete() -> None:
    extractor = SpeechExtractor()
    assert extractor.feed('{"habla": "Hola, soy mIA. ') == ["Hola, soy mIA."]
    assert extractor.feed("Te lo busco") == []
    assert extractor.feed(' ahora.", "estado_avatar": "hablando"') == ["Te lo busco ahora."]
    assert extractor.closed


def test_same_result_regardless_of_chunking() -> None:
    habla = 'Tienes 3 días. ¿Quieres verlos? ¡Vamos "allá"!'
    payload = json.dumps({"habla": habla, "estado_avatar": "hablando", "texto": "x"}, ensure_ascii=False)
    expected = ["Tienes 3 días.", "¿Quieres verlos?", '¡Vamos "allá"!']
    for size in (1, 2, 3, 5, 8, 50, 1000):
        assert _feed_in_chunks(payload, size) == expected


def test_handles_escaped_unicode_split_across_chunks() -> None:
    payload = json.dumps({"habla": "Pedro está de vacaciones."}, ensure_ascii=True)
    for size in (1, 2, 3, 4, 7):
        assert _feed_in_chunks(payload, size) == ["Pedro está de vacaciones."]


def test_finish_flushes_unterminated_text() -> None:
    extractor = SpeechExtractor()
    extractor.feed('{"habla": "Respuesta cortada')
    assert extractor.finish() == ["Respuesta cortada"]


def test_no_speech_field() -> None:
    assert _feed_in_chunks('{"texto": "solo texto"}', 3) == []
