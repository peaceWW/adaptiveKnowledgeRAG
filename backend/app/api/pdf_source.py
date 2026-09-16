"""Render the stored PDF itself, without reconstructing extracted knowledge text."""
from __future__ import annotations

import math
from threading import RLock

import pymupdf as fitz
from fastapi import HTTPException

# PyMuPDF documents are opened per request and rendering is serialized.
_pdf_lock = RLock()


def _open_pdf(raw: bytes):
    if not raw:
        raise HTTPException(404, "原始 PDF 文件不存在，请重新上传原文件")
    try:
        pdf = fitz.open(stream=raw, filetype="pdf")
    except Exception as exc:
        raise HTTPException(422, "原始文件无法作为 PDF 打开") from exc
    if pdf.needs_pass:
        pdf.close()
        raise HTTPException(422, "PDF 已加密，请上传解除密码保护的文件")
    if not pdf.page_count:
        pdf.close()
        raise HTTPException(422, "PDF 没有可显示的页面")
    return pdf


def pdf_manifest(raw: bytes) -> dict:
    with _pdf_lock, _open_pdf(raw) as pdf:
        return {
            "page_count": pdf.page_count,
            "pages": [
                {"number": i + 1, "width": page.rect.width, "height": page.rect.height,
                 "rotation": page.rotation}
                for i, page in enumerate(pdf)
            ],
        }


def render_pdf_page(raw: bytes, page_number: int, width: int = 1600) -> bytes:
    with _pdf_lock, _open_pdf(raw) as pdf:
        if not 1 <= page_number <= pdf.page_count:
            raise HTTPException(404, "PDF 页码超出范围")
        page = pdf[page_number - 1]
        rect = page.rect
        # Bound both dimensions and total pixel count, including unusual tall pages.
        zoom = min(max(600, min(width, 3000)) / rect.width,
                   6000 / rect.height, math.sqrt(12_000_000 / (rect.width * rect.height)))
        fitz.TOOLS.mupdf_warnings(reset=True)
        try:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB,
                                    alpha=False, annots=True)
        except Exception as exc:
            raise HTTPException(422, "PDF 页面无法渲染，请检查原文件是否损坏") from exc
        warnings = fitz.TOOLS.mupdf_warnings(reset=True).lower()
        if any(problem in warnings for problem in ("zlib error", "read error", "cannot read", "failed to read")):
            raise HTTPException(422, "PDF 页面数据损坏，无法完整展示。请重新上传可正常打开的原始 PDF")
        return pixmap.tobytes("png")
