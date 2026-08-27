from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncGenerator

from ..services.router import RouteDecision


UPLOADS_DIR = Path(__file__).parent.parent.parent / "uploads"
_converter = None


def _get_converter():
    global _converter
    if _converter is None:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        options = PdfPipelineOptions()
        options.do_ocr = True
        options.do_table_structure = True
        _converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
    return _converter


async def handle_documents(
    messages: list[dict],
    user_id: str,
    location: dict | None,
    attachments: list[str],
    decision: RouteDecision,
) -> AsyncGenerator[str, None]:
    """Handle document upload and processing."""
    latest_text = messages[-1].get("content", "").lower() if messages else ""

    if "list" in latest_text or "what" in latest_text:
        # List uploads
        files = [item.name for item in UPLOADS_DIR.iterdir() if item.is_file()]
        yield json.dumps(files) if files else "No uploads yet."
    elif attachments:
        # Process the most recent attachment
        filename = attachments[-1]
        path = UPLOADS_DIR / filename
        if not path.exists():
            yield f"'{filename}' not found."
            return

        suffix = path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            yield f"Uploaded image available: {path.name}. This backend is text-first, so ask for a summary request or document upload when possible."
        elif suffix in {".pdf", ".docx", ".doc"}:
            result = _get_converter().convert(str(path))
            text = result.document.export_to_markdown()[:8000]
            yield text
        else:
            text = path.read_text(errors="replace")[:8000]
            yield text
    else:
        # List uploads by default
        files = [item.name for item in UPLOADS_DIR.iterdir() if item.is_file()]
        yield json.dumps(files) if files else "No uploads yet. Upload a file using the 📎 button."
