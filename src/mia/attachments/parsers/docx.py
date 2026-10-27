"""Parser de DOCX: párrafos, headings y tablas con referencias de sección."""

from __future__ import annotations

import io
from typing import Any

from mia.attachments.model import AttachmentContent, AttachmentContentType, TableBlock, TextBlock


def parse_docx(content: bytes) -> AttachmentContent:
    import docx  # noqa: PLC0415
    from docx.oxml.ns import qn  # noqa: PLC0415

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
                para_style = element.find(qn("w:pPr"), element.nsmap) or ""
                style_elem = element.find(f".//{qn('w:pStyle')}")
                para_style = style_elem.get(qn("w:val"), "") if style_elem is not None else ""
            except Exception:
                pass

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
                ref = f"heading={current_heading[:40]}" if current_heading else "table"
                tables.append(TableBlock(headers=headers, rows=data_rows, source_ref=ref))

    metadata["tables_count"] = len(tables)

    return AttachmentContent(
        content_type=AttachmentContentType.DOCUMENT,
        text_blocks=text_blocks,
        tables=tables,
        metadata=metadata,
    )
