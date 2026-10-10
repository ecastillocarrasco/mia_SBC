"""Parser de CSV: detecta delimitador, encoding y estructura."""

from __future__ import annotations

import csv
import io
from typing import Any

from mia.attachments.model import AttachmentContent, AttachmentContentType, DatasetSheet


_MAX_ROWS = 5000
_CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]


def _detect_delimiter(sample: str) -> str:
    counts = {d: sample.count(d) for d in _CANDIDATE_DELIMITERS}
    return max(counts, key=lambda d: counts[d])


def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1", errors="replace")


def _infer_type(values: list[str]) -> str:
    sample = [v.strip() for v in values if v.strip()][:20]
    if not sample:
        return "empty"
    numeric = 0
    for v in sample:
        try:
            float(v.replace(",", "."))
            numeric += 1
        except ValueError:
            pass
    if numeric == len(sample):
        return "numeric"
    return "text"


def parse_csv(content: bytes) -> AttachmentContent:
    text = _decode(content)
    sample = text[:4096]
    delimiter = _detect_delimiter(sample)

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows_raw: list[list[str]] = []
    for row in reader:
        if len(rows_raw) >= _MAX_ROWS + 1:
            break
        rows_raw.append(row)

    if not rows_raw:
        return AttachmentContent(
            content_type=AttachmentContentType.DATASET,
            sheets=[],
            metadata={"row_count": 0},
        )

    headers = [h.strip() or f"Col{i+1}" for i, h in enumerate(rows_raw[0])]
    data_rows: list[list[Any]] = []
    for row in rows_raw[1:]:
        # Normalizar longitud a la de headers
        padded = row + [""] * max(0, len(headers) - len(row))
        values: list[Any] = []
        for v in padded[: len(headers)]:
            stripped = v.strip()
            if not stripped:
                values.append(None)
                continue
            try:
                values.append(int(stripped))
                continue
            except ValueError:
                pass
            try:
                values.append(float(stripped.replace(",", ".")))
                continue
            except ValueError:
                pass
            values.append(stripped)
        data_rows.append(values)

    col_texts: dict[str, list[str]] = {h: [] for h in headers}
    for row in data_rows:
        for i, h in enumerate(headers):
            if i < len(row) and row[i] is not None:
                col_texts[h].append(str(row[i]))

    inferred = {h: _infer_type(col_texts[h]) for h in headers}

    sheet = DatasetSheet(
        name="datos",
        headers=headers,
        rows=data_rows,
        inferred_types=inferred,
        row_count=len(data_rows),
    )

    return AttachmentContent(
        content_type=AttachmentContentType.DATASET,
        sheets=[sheet],
        metadata={
            "delimiter": delimiter,
            "row_count": len(data_rows),
            "col_count": len(headers),
            "sheet_count": 1,
            "sheet_names": ["datos"],
        },
    )
