"""Synthetic, entirely local regressions for mIA's existing sensitive-document indexers.

No SharePoint, OpenAI or PostgreSQL requests are made. Requires local Tesseract spa.
"""
from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFont

from mia.modules.rrhh.document_indexing import (
    DocumentIndexer,
    LocalOCRError,
    extract_document_text_local,
)
from mia.modules.rrhh.curriculums.indexer import CvIndexer


def _image():
    image = Image.new("RGB", (1800, 520), "white")
    canvas = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 50)
    except OSError:
        font = ImageFont.truetype("DejaVuSans.ttf", 50)
    for i, line in enumerate((
        "NOMINA FICTICIA PRUEBA OCR", "Departamento: Cocina",
        "Importe: 2500 euros", "Documento de prueba sin datos reales",
    )):
        canvas.text((90, 55 + i * 105), line, fill="black", font=font)
    return image


def _png_bytes():
    raw = BytesIO()
    _image().save(raw, format="PNG")
    return raw.getvalue()


def _scan_pdf(pages=1, first_native=False):
    import pymupdf
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=900, height=310)
        if i == 0 and first_native:
            page.insert_text((40, 50), "ESTE DOCUMENTO NATIVO ES UNA PRUEBA SIN DATOS REALES", fontsize=16)
        else:
            page.insert_image(page.rect, stream=_png_bytes())
    data = doc.tobytes()
    doc.close()
    return data


def test_image_uses_tesseract_without_llm():
    status, text, detail = extract_document_text_local(_png_bytes(), "imagen.png")
    assert status == "ok" and "Cocina" in text and "2500" in text
    assert detail == "ocr_local:imagen"


def test_native_pdf_keeps_text_without_ocr():
    import pymupdf
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((50, 50), "DOCUMENTO FICTICIO NATIVO DEL DEPARTAMENTO DE COCINA", fontsize=12)
    data = pdf.tobytes()
    pdf.close()
    status, text, detail = extract_document_text_local(data, "a.pdf")
    assert status == "ok" and "COCINA" in text and detail is None


def test_scanned_pdf_entire_content():
    status, text, detail = extract_document_text_local(_scan_pdf(), "fake.pdf")
    assert status == "ok" and "2500" in text and "Cocina" in text
    assert "1/1" in detail


def test_mixed_pdf_preserves_native_and_scanned():
    status, text, detail = extract_document_text_local(_scan_pdf(2, first_native=True), "mixed.pdf")
    assert status == "ok" and "NATIVO" in text and "Cocina" in text
    assert "1/2" in detail


def test_ocr_limit_fails_closed(monkeypatch):
    import mia.modules.rrhh.document_indexing as extraction
    monkeypatch.setattr(extraction, "LOCAL_OCR_MAX_SCANNED_PAGES", 1)
    with pytest.raises(LocalOCRError, match="No se indexa parcialmente"):
        extract_document_text_local(_scan_pdf(2), "long.pdf")


class _NoRemote:
    def __init__(self):
        self.embedded = []
    async def read_image(self, *_args, **_kwargs):
        raise AssertionError("Nunca se debe invocar OCR remoto")
    async def embed(self, texts, model):
        self.embedded.extend(texts)
        return [[1.0, 0.0] for _ in texts]


class _Client:
    def __init__(self, payload):
        self.payload = payload
    async def download_item_file(self, *_args):
        return self.payload
    async def download(self, *_args):
        return self.payload


@pytest.mark.asyncio
async def test_document_indexer_uses_local_ocr_without_remote_or_db():
    payload = _scan_pdf()
    llm = _NoRemote()
    indexer = DocumentIndexer(
        domain="nominas", list_title="Nominas", model=object, db=None,
        client=_Client(payload), llm=llm, embedding_model="fake",
    )
    records = []
    async def persist(*args, **kwargs):
        records.append(kwargs)
    indexer._persist = persist
    doc = SimpleNamespace(sp_id=1, file_name="ficticio.pdf")
    assert await indexer._index_one(doc) == "ok"
    assert len(records) == 1 and "ocr_local" in records[0]["detail"]
    assert llm.embedded


@pytest.mark.asyncio
async def test_cv_indexer_uses_local_ocr_without_remote_or_db():
    payload = _png_bytes()
    llm = _NoRemote()
    indexer = CvIndexer(db=None, client=_Client(payload), llm=llm, embedding_model="fake")
    records = []
    async def persist(*args, **kwargs):
        records.append(kwargs)
    indexer._persist = persist
    doc = SimpleNamespace(sp_id=1, file_ref="ficticio.png", file_name="ficticio.png")
    assert await indexer._index_one(doc) == "ok"
    assert len(records) == 1 and "ocr_local" in records[0]["detail"]
    assert llm.embedded


@pytest.mark.asyncio
async def test_ocr_failure_preserves_previous_index(monkeypatch):
    import mia.modules.rrhh.document_indexing as extraction
    monkeypatch.setattr(extraction, "LOCAL_OCR_MAX_SCANNED_PAGES", 1)
    indexer = DocumentIndexer(
        domain="nominas", list_title="Nominas", model=object, db=None,
        client=_Client(_scan_pdf(2)), llm=_NoRemote(), embedding_model="fake",
    )
    async def forbidden(*args, **kwargs):
        raise AssertionError("No borrar documentos o vectores al fallar OCR")
    indexer._persist = forbidden
    doc = SimpleNamespace(sp_id=1, file_name="ficticio.pdf")
    assert await indexer._index_one(doc) == "error"


def test_previous_render_pdf_pages_import_remains_available():
    # El procesador de adjuntos depende de este import anterior.
    from mia.modules.rrhh.curriculums.indexer import render_pdf_pages
    assert callable(render_pdf_pages)
