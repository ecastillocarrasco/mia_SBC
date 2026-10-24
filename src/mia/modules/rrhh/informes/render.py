"""Compatibilidad: los renderizadores compartidos viven en ``mia.reporting.render``."""

from mia.reporting.render import RENDERERS, _chart_of, _chart_segments, _rows, to_pdf, to_pptx, to_xlsx
from mia.reporting.render_docx import to_docx

__all__ = ["RENDERERS", "to_docx", "to_pdf", "to_pptx", "to_xlsx"]
