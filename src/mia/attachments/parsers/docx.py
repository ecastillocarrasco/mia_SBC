"""Parser de DOCX: párrafos, headings y tablas con referencias de sección."""

from __future__ import annotations

import io
import logging
from typing import Any

from docx.oxml.ns import qn

from mia.attachments.model import AttachmentContent, AttachmentContentType, TableBlock, TextBlock

log = logging.getLogger(__name__)


def _table_block(element: Any, heading: str) -> TableBlock | None:
    # Table
    tbl_rows: list[list[str]] = []
    for row in element.findall(f".//{qn('w:tr')}"):
        cells: list[str] = []
        for cell in row.findall(f".//{qn('w:tc')}"):
            cell_text = "".join(t.text or "" for t in cell.findall(f".//{qn('w:t')}")).strip()
            cells.append(cell_text)
        if any(cells):
            tbl_rows.append(cells)

    if tbl_rows:
        headers = tbl_rows[0]
        data_rows = tbl_rows[1:]
        ref = f"heading={heading[:40]}" if heading else "table"
        return TableBlock(headers=headers, rows=data_rows, source_ref=ref)

    return None


def parse_docx(content: bytes) -> AttachmentContent:
    import docx  # noqa: PLC0415

    document = docx.Document(io.BytesIO(content))

    metadata: dict[str, Any] = {}
    core_props = document.core_properties
    metadata["title"] = core_props.title or ""
    metadata["author"] = core_props.author or ""
    metadata["paragraph_count"] = len(document.paragraphs)

    text_blocks: list[TextBlock] = []
    tables: list[TableBlock] = []
    current_heading: str = ""
    paragraph_index = 0

    for element in document.element.body:
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

        if tag == "p":
            # Paragraph or heading
            para_style = ""
            try:
                style_elem = element.find(f".//{qn('w:pStyle')}")
                para_style = style_elem.get(qn("w:val"), "") if style_elem is not None else ""
            except Exception:
                log.warning("docx.parse_docx.failed")

            # Extract text from runs
            text_parts: list[str] = []
            for r in element.findall(f".//{qn('w:t')}"):
                text_parts.append(r.text or "")
            text = "".join(text_parts).strip()

            if not text:
                continue

            is_heading = para_style.lower().startswith("heading") or para_style.lower().startswith("tit")
            if is_heading:
                current_heading = text
                text_blocks.append(TextBlock(text=text, source_ref=f"heading={text[:60]}"))
            else:
                paragraph_index += 1
                ref = f"paragraph={paragraph_index}"
                if current_heading:
                    ref += f" heading={current_heading[:40]}"
                text_blocks.append(TextBlock(text=text, source_ref=ref))

        elif tag == "tbl":
            if block := _table_block(element, current_heading):
                tables.append(block)

    metadata["tables_count"] = len(tables)

    return AttachmentContent(
        content_type=AttachmentContentType.DOCUMENT,
        text_blocks=text_blocks,
        tables=tables,
        metadata=metadata,
    )
