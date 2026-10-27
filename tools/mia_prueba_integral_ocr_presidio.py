"""mIA SBC: prueba sintetica completa OCR -> indexador -> Presidio -> Fake embeddings.

Solo memoria; no accede a PostgreSQL, SharePoint ni OpenAI. Los datos son ficticios.
Ejecutar desde raiz mIA con el entorno virtual y PYTHONPATH=src.
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from mia.llm.fake import FakeLLMProvider
from mia.modules.rrhh.document_indexing import DocumentIndexer
from mia.privacy_gateway.gateway import PrivacyGateway
from mia.settings import get_settings

DATOS = {
    "nombre": "María García López",
    "dni": "12345678Z",
    "correo": "prueba@example.com",
    "iban": "ES9121000418450200051332",
    "departamento": "Cocina",
    "importe": "2500",
}


def pdf_escaneado_ficticio() -> bytes:
    imagen = Image.new("RGB", (2100, 1160), "white")
    lienzo = ImageDraw.Draw(imagen)
    try:
        fuente = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 53)
    except OSError:
        fuente = ImageFont.load_default()
    lineas = [
        "NOMINA FICTICIA - PRUEBA INTEGRAL",
        f"Nombre: {DATOS['nombre']}",
        f"DNI: {DATOS['dni']}",
        f"Correo: {DATOS['correo']}",
        f"IBAN: {DATOS['iban']}",
        f"Departamento: {DATOS['departamento']}",
        f"Salario bruto: {DATOS['importe']} euros",
        "DOCUMENTO SINTETICO SIN PERSONAS REALES",
    ]
    for indice, linea in enumerate(lineas):
        lienzo.text((85, 65 + 130 * indice), linea, fill="black", font=fuente)
    png = BytesIO()
    imagen.save(png, format="PNG")
    pdf = pymupdf.open()
    pagina = pdf.new_page(width=1050, height=580)
    pagina.insert_image(pagina.rect, stream=png.getvalue())
    pdf_bytes = pdf.tobytes()
    pdf.close()
    return pdf_bytes


class ClienteSoloMemoria:
    def __init__(self, contenido: bytes):
        self.contenido = contenido

    async def download_item_file(self, *_args):
        return self.contenido


class Capturador(FakeLLMProvider):
    def __init__(self):
        super().__init__()
        self.fragmentos_recibidos = []

    async def embed(self, texts, model):
        self.fragmentos_recibidos.extend(texts)
        return await super().embed(texts, model)


async def main() -> None:
    settings = get_settings()
    if not settings.privacy_gateway.enabled or settings.privacy_gateway.fail_open:
        raise SystemExit("BLOQUEADO: Presidio debe estar activado y Fail Open desactivado")

    pdf_bytes = pdf_escaneado_ficticio()
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
        sin_capa_texto = not bool(pdf[0].get_text().strip())

    proveedor_fake = Capturador()
    gateway = PrivacyGateway(
        proveedor_fake,
        settings.privacy_gateway,
        provider_name="fake",
        model="prueba-local",
    )
    indexador = DocumentIndexer(
        domain="nominas",
        list_title="Prueba Ficticia",
        model=object,
        db=None,
        client=ClienteSoloMemoria(pdf_bytes),
        llm=gateway,
        embedding_model="text-embedding-3-small",
        batch=1,
    )
    capturas_persistencia = []

    async def persistencia_simulada(_documento, **kwargs):
        capturas_persistencia.append(kwargs)

    indexador._persist = persistencia_simulada
    documento = SimpleNamespace(sp_id=-1, file_name="nomina_ficticia_ocr.pdf")
    estado = await indexador._index_one(documento)
    if estado != "ok" or not capturas_persistencia or not proveedor_fake.fragmentos_recibidos:
        raise SystemExit(f"PRUEBA NO COMPLETADA: estado={estado}, simulaciones={len(capturas_persistencia)}")

    guardado_local = capturas_persistencia[0]
    texto_local = guardado_local["text"]
    texto_externo_simulado = "\n".join(proveedor_fake.fragmentos_recibidos)
    print("=== OCR + INDEXADOR + PRESIDIO + EMBEDDINGS SIMULADOS ===")
    print("PDF sin capa de texto:", sin_capa_texto)
    print("Extraccion/indexador:", estado)
    print("Origen OCR:", guardado_local.get("detail"))
    print("Fragmentos generados:", len(guardado_local["chunks"]))
    print("Vectores simulados:", len(guardado_local["vectors"]))

    print("\n--- Reconocimiento OCR (texto local; NO salio del equipo) ---")
    for nombre, valor in DATOS.items():
        reconocido = valor.casefold() in texto_local.casefold()
        print(f"OCR {nombre}: {'RECONOCIDO' if reconocido else 'NO RECONOCIDO - REVISAR OCR'}")

    print("\n--- Texto que recibiria el proveedor de embeddings ---")
    for nombre in ("nombre", "dni", "correo", "iban"):
        valor = DATOS[nombre]
        reconocido = valor.casefold() in texto_local.casefold()
        presente_en_salida = valor.casefold() in texto_externo_simulado.casefold()
        if not reconocido:
            resultado = "NO EVALUABLE (el OCR no reconocio el dato exacto)"
        else:
            resultado = "PROTEGIDO" if not presente_en_salida else "EXPOSICION DETECTADA"
        print(f"Presidio {nombre}: {resultado}")

    salario_enviable = DATOS["importe"] in texto_externo_simulado
    print("Importe salarial permaneceria en el envio:", salario_enviable)
    print("Departamento permaneceria en el envio:", DATOS["departamento"] in texto_externo_simulado)
    print("Acceso SharePoint externo: NO (cliente simulado)")
    print("Llamadas a OpenAI: NINGUNA (proveedor simulado)")
    print("Escrituras PostgreSQL: NINGUNA (persistencia simulada)")
    if salario_enviable:
        print("AVISO: bloquear indexacion REAL hasta acordar politica de importes salariales")


if __name__ == "__main__":
    asyncio.run(main())
