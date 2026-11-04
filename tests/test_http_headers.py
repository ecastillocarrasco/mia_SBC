from __future__ import annotations

from mia.api.http_headers import content_disposition


def test_ascii_filename_round_trips_in_both_parameters() -> None:
    header = content_disposition("attachment", "informe_agosto.pdf")
    assert header == "attachment; filename=\"informe_agosto.pdf\"; filename*=UTF-8''informe_agosto.pdf"


def test_non_latin1_filename_never_raises_and_keeps_the_real_name_in_filename_star() -> None:
    # Un adjunto de correo externo puede llegar con cualquier nombre: CJK, árabe, cirílico,
    # emoji. Antes de este fix, construir la cabecera directamente con ese nombre lanzaba
    # UnicodeEncodeError (Starlette codifica los headers como Latin-1) y provocaba un 500.
    header = content_disposition("inline", "报告 😀.pdf")
    assert "filename*=UTF-8''%E6%8A%A5%E5%91%8A%20%F0%9F%98%80.pdf" in header
    assert header.encode("latin-1")  # nunca debe lanzar al construir la respuesta real


def test_quotes_and_newlines_are_stripped_to_avoid_header_injection() -> None:
    header = content_disposition("attachment", 'raro".pdf\r\nX-Injected: 1')
    assert '"' not in header.split("filename*=")[0].split('filename="')[1].rstrip('"; ')
    assert "\r" not in header and "\n" not in header
