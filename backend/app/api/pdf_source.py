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


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def page_text_layer(raw: bytes, page_number: int) -> dict:
    """抽出一页文字及相对 page.rect 的归一化包围盒，供前端叠在渲染图上选中复制。

    get_text('dict') 的 bbox 相对未旋转页；乘 rotation_matrix 后与 get_pixmap 画面一致。
    """
    with _pdf_lock, _open_pdf(raw) as pdf:
        if not 1 <= page_number <= pdf.page_count:
            raise HTTPException(404, "PDF 页码超出范围")
        page = pdf[page_number - 1]
        page_rect = page.rect
        width, height = page_rect.width, page_rect.height
        if width <= 0 or height <= 0:
            raise HTTPException(422, "PDF 页面尺寸无效")
        extracted = page.get_text("dict")
        spans: list[dict] = []
        for block in extracted.get("blocks") or []:
            if block.get("type") != 0:
                continue
            for line in block.get("lines") or []:
                text = "".join(str(span.get("text") or "") for span in (line.get("spans") or []))
                if not text.strip():
                    continue
                box = fitz.Rect(line["bbox"]) * page.rotation_matrix
                box &= page_rect
                if box.is_empty or box.width <= 0 or box.height <= 0:
                    continue
                spans.append({
                    "text": text,
                    "x": _clip01(box.x0 / width),
                    "y": _clip01(box.y0 / height),
                    "w": _clip01(box.width / width),
                    "h": _clip01(box.height / height),
                })
        return {
            "page": page_number,
            "width": width,
            "height": height,
            "spans": spans,
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
