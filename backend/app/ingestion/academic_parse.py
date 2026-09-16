# IEEE/学术 PDF 版面解析：双栏阅读序、章节、图/公式/表/引用清单。
# 入库 parse 节点调用；产出写入 Document.structure，供 classify 与论文抽取使用。
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import pymupdf as fitz

from app.observability.pipeline_log import step as pipeline_step

ROMAN = r"I{1,3}|IV|VI{0,3}|IX|X{0,3}I{0,3}"
SECTION_RE = re.compile(rf"^((?:{ROMAN}))\.\s+(.+)$")
SUBSECTION_RE = re.compile(r"^([A-H])\.\s+([A-Z][A-Za-z0-9/ \-:,()]{2,80})$")
NAMED_SECTION_RE = re.compile(
    r"^(Abstract|Index Terms|Keywords|References|Acknowledgment|Acknowledgement|Appendix(?:\s+[A-Z])?)\b",
    re.I,
)
EQ_ONLY_RE = re.compile(r"^\s*\((\d{1,3})\)\s*$")
EQ_TAIL_RE = re.compile(r"^(?P<body>.+?)\s*\((?P<num>\d{1,3})\)\s*$")
FIG_RE = re.compile(r"^(?:Fig(?:ure)?\.?\s*)(\d+[A-Za-z]?)\.\s*(.+)$", re.I)
TABLE_RE = re.compile(r"^(?:TABLE)\s+([IVXLCDM]+|\d+)\.?\s*(.*)$", re.I)
CITE_RE = re.compile(r"\[(\d{1,3}(?:\s*[,;–-]\s*\d{1,3})*)\]")
REF_ENTRY_RE = re.compile(r"^\[(\d{1,3})\]\s*(.+)$")
HEADER_RE = re.compile(
    r"(IEEE\s+JOURNAL|JOURNAL\s+OF\s+SOLID|SOLID-STATE CIRCUITS|"
    r"0018-9200|Authorized\s+licensed|Digital Object Identifier|10\.\d{4}/)",
    re.I,
)
PAGE_NUM_RE = re.compile(r"^\d{1,4}$")
MATH_FONT_RE = re.compile(r"(Math|Symbol|CMMI|CMSY|CMEX|Euclid|STIX|Asana)", re.I)

ACADEMIC_HINTS = (
    "abstract",
    "index terms",
    "references",
    "ieee",
    "jssc",
    "transactions",
    "doi:",
    "10.1109/",
)


def looks_like_academic_paper(text: str, metadata: dict[str, Any] | None = None, filename: str = "") -> bool:
    """启发式判断是否走论文解析：有 DOI/venue 即真；否则看 Abstract/IEEE 等提示词与罗马章节号。"""
    blob = f"{filename}\n{text[:8000]}".lower()
    meta = metadata or {}
    hit_names = [hint for hint in ACADEMIC_HINTS if hint in blob]
    has_roman = bool(SECTION_RE.search(text[:4000]))
    has_abs_ref = "abstract" in blob and "references" in blob
    inputs = {
        "filename": filename,
        "text_len": len(text or ""),
        "doi": meta.get("doi") or "",
        "venue": meta.get("venue") or "",
        "ieee_article_id": meta.get("ieee_article_id") or "",
        "hint_hits": hit_names,
        "has_roman_section": has_roman,
        "has_abstract_and_references": has_abs_ref,
    }
    # 元数据已标明期刊论文，避免扫描件正文过短时被判成 generic
    if meta.get("doi") or meta.get("venue") or meta.get("ieee_article_id"):
        reason = "metadata_doi_or_venue"
        result = True
    elif len(hit_names) >= 2:
        reason = "hint_hits>=2"
        result = True
    elif hit_names and has_roman:
        reason = "hint_plus_roman_section"
        result = True
    elif has_abs_ref:
        reason = "abstract_and_references"
        result = True
    else:
        reason = "no_academic_signal"
        result = False
    pipeline_step(
        "ingest",
        "file_type",
        inputs=inputs,
        result={"academic_paper": result, "genre": "academic_paper" if result else "generic", "reason": reason},
    )
    return result


def parse_pdf_document(doc: fitz.Document) -> dict[str, Any]:
    """逐页抽出文本与图/公式/表，判定 genre；论文才切 IEEE 章节。无 I/O，调用方写入 Document.structure。"""
    metadata = extract_pdf_metadata(doc)
    pages: list[dict[str, Any]] = []
    equations: list[dict[str, Any]] = []
    figures: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    all_cites: list[str] = []

    for idx, page in enumerate(doc, start=1):
        page_data = extract_page_layout(page, page_no=idx)
        pages.append(
            {
                "page": idx,
                "text": page_data["text"],
                "reading_order": page_data["reading_order"],
            }
        )
        equations.extend(page_data["equations"])
        figures.extend(page_data["figures"])
        # Preserve embedded illustrations even if they have no Fig. caption.
        for image_index, image in enumerate(page.get_image_info(), 1):
            rect = fitz.Rect(image["bbox"])
            if rect.width < 16 or rect.height < 16 or rect.get_area() >= page.rect.get_area() * 0.9:
                continue
            if any((rect & fitz.Rect(fig["bbox"])).get_area() >= rect.get_area() * 0.7
                   for fig in page_data["figures"] if len(fig.get("bbox") or []) == 4):
                continue
            figures.append({"fig_id": f"p{idx}-image{image_index}", "page": idx, "caption": "",
                            "bbox": list(rect), "crop_mode": "embedded_image"})
        tables.extend(extract_page_tables(page, idx, page_data["text"]))
        all_cites.extend(page_data["citations"])

    full_text = "\n".join(p["text"] for p in pages)
    pages_ok = sum(1 for page in pages if (page.get("text") or "").strip())
    parse_quality = {
        "pages_ok": pages_ok,
        "pages_total": len(pages),
        "text_len": len(full_text.strip()),
        "pages_ocr": 0,
    }
    genre = "academic_paper" if looks_like_academic_paper(full_text, metadata) else "generic"
    # 扫描件几乎抽不出字但仍有 DOI：保持论文体裁，避免后续走普通切块
    if parse_quality["text_len"] < 80 and metadata.get("doi"):
        genre = "academic_paper"
        pipeline_step(
            "ingest",
            "file_type_override",
            inputs={"text_len": parse_quality["text_len"], "doi": metadata.get("doi")},
            result={"genre": genre, "reason": "short_text_but_has_doi"},
        )
    # 非论文不做罗马章节切分，以免把规范/手册误拆成 I./II.
    sections = split_ieee_sections(pages) if genre == "academic_paper" else []
    citations = collect_citations(pages, all_cites)
    chapters = [
        {"title": f"{item.get('id', '')} {item.get('title', '')}".strip(), "level": item.get("level", 1), "page": item.get("page", 1)}
        for item in sections
    ]
    if not chapters:
        chapters = headings_from_text(full_text)

    if genre == "academic_paper" and not metadata.get("title"):
        metadata["title"] = _guess_title(pages[0]["text"] if pages else full_text)

    return {
        "text": full_text,
        "pages": pages,
        "chapters": chapters,
        "genre": genre,
        "metadata": metadata,
        "sections": sections,
        "equations": _unique_by(equations, "eq_id"),
        "figures": _unique_by(figures, "fig_id"),
        "tables": _unique_by(tables, "table_id"),
        "citations": citations,
        "parse_quality": parse_quality,
    }


def extract_pdf_metadata(doc: fitz.Document) -> dict[str, Any]:
    """从 PDF info + XMP 取 title/authors/DOI/venue；供体裁判定与论文元数据单元使用。"""
    raw = doc.metadata or {}
    meta: dict[str, Any] = {
        "title": (raw.get("title") or "").strip(),
        "authors": [],
        "subject": (raw.get("subject") or "").strip(),
        "keywords": [],
        "venue": "",
        "year": "",
        "doi": "",
        "ieee_article_id": "",
    }
    xml = ""
    try:
        xml = doc.get_xml_metadata() or ""
    except Exception:
        xml = ""
    if xml:
        meta.update(_parse_xmp(xml))
    subject = meta.get("subject") or ""
    # IEEE 常把刊名塞进 Subject，XMP 没有 publicationName 时回填 venue
    if "IEEE" in subject and not meta.get("venue"):
        meta["venue"] = subject.split(";")[0].strip()
    if not meta["year"]:
        match = re.search(r"\b(19|20)\d{2}\b", subject or raw.get("creationDate") or "")
        if match:
            meta["year"] = match.group(0)
    return meta


def extract_page_layout(page: fitz.Page, page_no: int) -> dict[str, Any]:
    """还原双栏阅读序并剥离页眉页脚；顺带收集本页公式、图注与文内引用编号。"""
    info = page.get_text("dict")
    width = float(page.rect.width)
    height = float(page.rect.height)
    mid = width / 2
    full_width: list[tuple[float, str, list[float]]] = []
    left: list[tuple[float, str, list[float], dict[str, Any]]] = []
    right: list[tuple[float, str, list[float], dict[str, Any]]] = []

    image_boxes: list[list[float]] = []
    for block in info.get("blocks") or []:
        bbox = [float(v) for v in block.get("bbox") or [0, 0, 0, 0]]
        if block.get("type") == 1 and len(bbox) == 4:
            image_boxes.append(bbox)
            continue
        if block.get("type") != 0:
            continue
        bbox = [float(v) for v in block.get("bbox") or [0, 0, 0, 0]]
        text, fonts, max_size = _block_text(block)
        if not text or _is_header_footer(text, bbox, height):
            continue
        record = {"fonts": fonts, "max_size": max_size}
        x0, _, x1, _ = bbox
        y0 = bbox[1]
        span = x1 - x0
        # 跨栏标题/摘要走整页宽；其余按中线分左右栏，避免双栏交错成乱序
        if span > width * 0.55 or (x0 < mid - 30 and x1 > mid + 30):
            full_width.append((y0, text, bbox))
        elif (x0 + x1) / 2 < mid:
            left.append((y0, text, bbox, record))
        else:
            right.append((y0, text, bbox, record))

    left.sort(key=lambda item: (item[0], item[2][0]))
    right.sort(key=lambda item: (item[0], item[2][0]))
    full_width.sort(key=lambda item: item[0])
    col_start = min([item[0] for item in left + right], default=height)
    header_blocks = [item for item in full_width if item[0] < col_start - 2]
    footer_blocks = [item for item in full_width if item[0] >= col_start - 2]
    ordered = header_blocks + [(a, b, c) for a, b, c, _ in left] + [(a, b, c) for a, b, c, _ in right] + footer_blocks
    reading_order = "two_column" if left and right else "single"
    lines = [text for _, text, _ in ordered]
    page_text = "\n".join(lines)
    # 分栏失败（扫描件/异常编码）时退回纯文本，仍尽量丢掉刊头与页码
    if not page_text.strip():
        plain = (page.get_text("text") or "").strip()
        if plain:
            page_text = "\n".join(
                line
                for line in plain.splitlines()
                if line.strip() and not HEADER_RE.search(line) and not PAGE_NUM_RE.match(line.strip())
            )
            reading_order = "single"
            left, right = [], []
            ordered = [(0.0, line, [0.0, 0.0, width, 0.0]) for line in page_text.splitlines() if line.strip()]
    # 矢量框图也当图像框，供图注匹配裁剪（电路图常不是嵌入位图）
    try:
        for drawing in page.get_drawings() or []:
            rect = drawing.get("rect")
            if rect is None:
                continue
            box = [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]
            if box[2] - box[0] > 24 and box[3] - box[1] > 24:
                image_boxes.append(box)
    except Exception:
        pass
    equations = extract_equations(left + right, page_no, page_text)
    figures = extract_figure_captions(page_text, page_no, ordered, image_boxes, [0.0, 0.0, width, height])
    citations = [f"[{num}]" for num in _expand_cite_keys(page_text)]
    return {
        "text": page_text,
        "reading_order": reading_order,
        "equations": equations,
        "figures": figures,
        "citations": citations,
    }


def extract_equations(
    column_blocks: list[tuple[float, str, list[float], dict[str, Any]]],
    page_no: int,
    page_text: str,
) -> list[dict[str, Any]]:
    """识别编号公式 (n)：独立编号行合并上一行，或行尾编号且含数学字体/符号。无版面块时按行正则兜底。"""
    found: dict[str, dict[str, Any]] = {}
    for idx, (_, text, bbox, record) in enumerate(column_blocks):
        eq_id = ""
        body = text.strip()
        only = EQ_ONLY_RE.match(body)
        tail = EQ_TAIL_RE.match(body)
        mathish = any(MATH_FONT_RE.search(font) for font in record.get("fonts") or [])
        # IEEE 常见：公式体一行、编号 (n) 单独一行，需并入上一块 bbox 供后续裁 PNG
        if only:
            eq_id = only.group(1)
            prev = column_blocks[idx - 1][1].strip() if idx else ""
            body = prev
            bbox = _merge_bbox(column_blocks[idx - 1][2], bbox) if idx else bbox
        elif tail and (mathish or _looks_like_equation_body(tail.group("body"))):
            eq_id = tail.group("num")
            body = tail.group("body").strip()
        if not eq_id:
            continue
        nearby = _nearby_text(page_text, eq_id)
        found[eq_id] = {
            "eq_id": eq_id,
            "page": page_no,
            "latex": "",
            "raw": body,
            "bbox": [round(v, 2) for v in bbox],
            "nearby_text": nearby,
        }
    # 双栏块丢失时仍要从纯文本捞编号公式，bbox 为空则入库后无法裁图
    if not found:
        for match in re.finditer(r"(?m)^(.{8,160}?)\s+\((\d{1,3})\)\s*$", page_text):
            body, eq_id = match.group(1).strip(), match.group(2)
            if eq_id in found or not _looks_like_equation_body(body):
                continue
            found[eq_id] = {
                "eq_id": eq_id,
                "page": page_no,
                "latex": "",
                "raw": body,
                "bbox": [],
                "nearby_text": _nearby_text(page_text, eq_id),
            }
    for match in re.finditer(
        r"(?P<body>[A-Za-z\\][^\n]{2,90}?=\s*[^\n]{1,90}?)\s*\((?P<num>\d{1,3})\)",
        page_text,
    ):
        eq_id = match.group("num")
        body = match.group("body").strip()
        if eq_id in found or not _looks_like_equation_body(body):
            continue
        found[eq_id] = {
            "eq_id": eq_id,
            "page": page_no,
            "latex": "",
            "raw": body,
            "bbox": [],
            "nearby_text": _nearby_text(page_text, eq_id),
        }
    return list(found.values())


def extract_figure_captions(
    text: str,
    page_no: int,
    ordered: list[tuple[float, str, list[float]]] | None = None,
    image_boxes: list[list[float]] | None = None,
    page_rect: list[float] | None = None,
) -> list[dict[str, Any]]:
    """按 Fig. n. 抽图注，并匹配上方最近图像框；匹配失败用 caption 上方一截页面作 crop 降级。"""
    figures = []
    caption_boxes: dict[str, list[float]] = {}
    for item in ordered or []:
        match = FIG_RE.match(item[1].strip())
        if match:
            caption_boxes[match.group(1)] = item[2]
    for line in text.splitlines():
        match = FIG_RE.match(line.strip())
        if not match:
            continue
        fig_id = match.group(1)
        caption_bbox = caption_boxes.get(fig_id) or []
        # crop_mode=image 走真实框图；page_fallback/missing 仍产出清单，Vision 可降级只用 caption
        image_bbox, crop_mode = _nearest_image_bbox(caption_bbox, image_boxes or [], page_rect)
        figures.append(
            {
                "fig_id": fig_id,
                "caption": match.group(2).strip(),
                "page": page_no,
                "image_key": "",
                "bbox": [round(v, 2) for v in image_bbox] if image_bbox else [],
                "crop_mode": crop_mode,
            }
        )
    return figures


def extract_page_tables(page: fitz.Page, page_no: int, page_text: str) -> list[dict[str, Any]]:
    """用 PyMuPDF 抽表格行，按出现顺序对齐 TABLE 题注；抽表失败仍保留题注清单供检索。"""
    captions = []
    for line in page_text.splitlines():
        match = TABLE_RE.match(line.strip())
        if match:
            captions.append((match.group(1), match.group(2).strip()))
    tables: list[dict[str, Any]] = []
    try:
        found = page.find_tables()
        for idx, table in enumerate(found.tables if found else []):
            rows = table.extract() or []
            table_id, caption = captions[idx] if idx < len(captions) else (f"p{page_no}-table{idx + 1}", "")
            tables.append(
                {
                    "table_id": str(table_id),
                    "caption": caption,
                    "page": page_no,
                    "rows": [[_clean_cell(cell) for cell in row] for row in rows if any(row)],
                    "bbox": list(table.bbox),
                }
            )
    except Exception:
        pass
    # 线框表识别失败时至少留下 table_id + caption，避免论文清单缺表
    if not tables:
        for table_id, caption in captions:
            tables.append({"table_id": str(table_id), "caption": caption, "page": page_no, "rows": []})
    return tables


def split_ieee_sections(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 Abstract / 罗马大节 / A.小节 切章；参考文献内不再把 [n] 或罗马数字当新节。无标题前的文字归 front。"""
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_references = False

    def flush() -> None:
        nonlocal current
        if current is not None:
            current["text"] = current["text"].strip()
            sections.append(current)
            current = None

    for page in pages:
        page_no = int(page.get("page") or 1)
        for line in (page.get("text") or "").splitlines():
            stripped = line.strip()
            if not stripped:
                if current is not None:
                    current["text"] += "\n"
                continue
            heading = _match_heading(stripped, in_references)
            if heading:
                flush()
                # 进入 References 后关闭罗马节匹配，避免文献条目里的 I. 被当成新章
                in_references = heading["title"].lower().startswith("reference")
                current = {
                    "id": heading["id"],
                    "title": heading["title"],
                    "level": heading["level"],
                    "page": page_no,
                    "text": "",
                }
                remainder = heading.get("remainder") or ""
                if remainder:
                    current["text"] += remainder + "\n"
                continue
            if current is None:
                # 标题页、作者栏等尚无节标题，单独成 front 以免并入 Abstract
                current = {
                    "id": "front",
                    "title": "Front Matter",
                    "level": 1,
                    "page": page_no,
                    "text": "",
                }
            current["text"] += stripped + "\n"
    flush()
    return [item for item in sections if item.get("text") or item.get("title")]


def collect_citations(pages: list[dict[str, Any]], inline_keys: list[str]) -> list[dict[str, Any]]:
    """合并参考文献表与正文 [n]/[n–m]；记录 cited_in_sections。表中没有的文内引用也建空条目。"""
    ref_map: dict[str, dict[str, Any]] = {}
    ref_section = ""
    joined = "\n".join(page.get("text") or "" for page in pages)
    match = re.search(r"(?im)^references\s*$", joined)
    if match:
        ref_section = joined[match.end() :]
        for line in ref_section.splitlines():
            entry = REF_ENTRY_RE.match(line.strip())
            if entry:
                key = f"[{entry.group(1)}]"
                ref_map[key] = {
                    "key": key,
                    "text": entry.group(2).strip(),
                    "cited_in_sections": [],
                }
            elif ref_map:
                last = next(reversed(ref_map.values()))
                # 续行接到上一条；遇到罗马节标题则停止，防止附录正文并进文献
                if line.strip() and not SECTION_RE.match(line.strip()):
                    last["text"] = f"{last['text']} {line.strip()}".strip()
    cited_in: dict[str, set[str]] = {}
    sections = split_ieee_sections(pages)
    for section in sections:
        if section["title"].lower().startswith("reference"):
            continue
        # 正文引用才记 cited_in；参考文献章本身跳过以免自指
        for num in _expand_cite_keys(section.get("text") or ""):
            key = f"[{num}]"
            cited_in.setdefault(key, set()).add(section.get("id") or section.get("title") or "")
            if key not in ref_map:
                ref_map[key] = {"key": key, "text": "", "cited_in_sections": []}
    for key in inline_keys:
        ref_map.setdefault(key, {"key": key, "text": "", "cited_in_sections": []})
    for key, sections_set in cited_in.items():
        ref_map[key]["cited_in_sections"] = sorted(sections_set)
    return [ref_map[key] for key in sorted(ref_map, key=lambda item: int(re.sub(r"\D", "", item) or 0))]


def headings_from_text(text: str, page: int = 1) -> list[dict[str, Any]]:
    """无 IEEE 章节时的目录兜底：Markdown #、罗马节、或短行通用标题。只产出 chapters，不切正文。"""
    chapters: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            chapters.append({"title": stripped.lstrip("# ").strip(), "level": min(level, 4), "page": page})
            continue
        heading = _match_heading(stripped, in_references=False)
        if heading:
            title = f"{heading['id']}. {heading['title']}" if heading["id"] and heading["id"] not in {"abstract", "keywords", "references"} else heading["title"]
            chapters.append({"title": title, "level": heading["level"], "page": page})
            continue
        if _looks_like_generic_heading(stripped):
            chapters.append({"title": stripped, "level": 2, "page": page})
    return chapters


def render_region_png(data: bytes, page_no: int, bbox: list[float], zoom: float = 2.0) -> bytes:
    """按 bbox 裁 PDF 页为 PNG；供图/公式资产入库 MinIO。bbox 非法返回空 bytes，不抛错。"""
    doc = fitz.open(stream=data, filetype="pdf")
    page = doc[max(page_no - 1, 0)]
    if len(bbox) != 4:
        return b""
    # 略扩边以免裁掉图框或公式编号
    rect = fitz.Rect(*bbox) + (-3, -3, 3, 3)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, alpha=False)
    return pix.tobytes("png")


def _parse_xmp(xml: str) -> dict[str, Any]:
    """读 Dublin Core / PRISM：补 title、作者、关键词、DOI、刊名、年份。解析失败返回空 dict。"""
    out: dict[str, Any] = {}
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out
    ns = {
        "dc": "http://purl.org/dc/elements/1.1/",
        "prism": "http://prismstandard.org/namespaces/basic/3.0/",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    }

    def texts(xpath: str) -> list[str]:
        values = []
        for node in root.findall(xpath, ns):
            value = "".join(node.itertext()).strip()
            if value:
                values.append(value)
        return values

    titles = texts(".//dc:title//rdf:li") or texts(".//dc:title")
    if titles:
        out["title"] = titles[0]
    authors = texts(".//dc:creator//rdf:li")
    if authors:
        out["authors"] = authors
    subjects = texts(".//dc:subject//rdf:li")
    if subjects:
        out["keywords"] = subjects
    doi = texts(".//prism:doi")
    if doi:
        out["doi"] = doi[0]
    venue = texts(".//prism:publicationName")
    if venue:
        out["venue"] = venue[0]
    year = texts(".//prism:coverDisplayDate")
    if year:
        match = re.search(r"(19|20)\d{2}", year[0])
        if match:
            out["year"] = match.group(0)
    return out


def _block_text(block: dict[str, Any]) -> tuple[str, list[str], float]:
    """拼文本块各 span，并收集字体名与最大字号，供公式数学字体判定。"""
    fonts: list[str] = []
    max_size = 0.0
    lines: list[str] = []
    for line in block.get("lines") or []:
        parts: list[str] = []
        for span in line.get("spans") or []:
            piece = (span.get("text") or "").strip()
            if piece:
                parts.append(piece)
            font = span.get("font") or ""
            if font:
                fonts.append(font)
            max_size = max(max_size, float(span.get("size") or 0))
        if parts:
            lines.append(" ".join(parts))
    return "\n".join(lines).strip(), fonts, max_size


def _is_header_footer(text: str, bbox: list[float], height: float) -> bool:
    """丢掉页眉刊名、页码、IEEE 授权行，避免它们进入章节正文与公式匹配。"""
    y0 = bbox[1] if bbox else 0
    compact = text.strip()
    # 靠近页顶/页底的短行或刊头正则才当页眉页脚，避免误删双栏顶部正文
    if y0 < 36 or y0 > height - 40:
        if len(compact) < 120 or HEADER_RE.search(compact) or PAGE_NUM_RE.match(compact):
            return True
    if HEADER_RE.search(compact) and len(compact) < 180:
        return True
    if compact.lower().startswith("authorized licensed"):
        return True
    return False


def _match_heading(line: str, in_references: bool) -> dict[str, Any] | None:
    """识别 Abstract/Index Terms/References、罗马大节、A.–H. 小节；参考文献区内只认命名节。"""
    named = NAMED_SECTION_RE.match(line)
    if named:
        label = named.group(1)
        key = label.lower().replace("acknowledgement", "acknowledgment")
        remainder = line[named.end() :].lstrip(" .:—–-")
        if key.startswith("abstract"):
            return {"id": "abstract", "title": "Abstract", "level": 1, "remainder": remainder}
        if key.startswith("index") or key.startswith("keyword"):
            return {"id": "keywords", "title": "Index Terms", "level": 1, "remainder": remainder}
        if key.startswith("reference"):
            return {"id": "references", "title": "References", "level": 1, "remainder": remainder}
        return {"id": key, "title": label.title(), "level": 1, "remainder": remainder}
    roman = SECTION_RE.match(line)
    if roman and not in_references:
        title = roman.group(2).strip()
        if len(title) <= 80:
            return {"id": roman.group(1), "title": title.title() if title.isupper() else title, "level": 1, "remainder": ""}
    # 参考文献条目常含 I. / [n]，禁止再当章节标题
    if in_references:
        return None
    sub = SUBSECTION_RE.match(line)
    if sub:
        return {"id": sub.group(1), "title": sub.group(2).strip(), "level": 2, "remainder": ""}
    return None


def _looks_like_generic_heading(line: str) -> bool:
    """非论文 Markdown/规范的短标题启发式，仅用于 chapters 目录，不驱动切章。"""
    if len(line) > 80:
        return False
    if line[:1].isdigit() and ("." in line[:6] or " " in line[:4]):
        return True
    keywords = ("Chapter", "Section", "定义", "原理", "约束", "示例", "CDC", "Setup", "Hold")
    return any(key in line for key in keywords) and len(line.split()) <= 12


def _looks_like_equation_body(text: str) -> bool:
    """区分公式与普通句末 (n)：需含等号/积分等符号或 TeX 命令，避免把叙述编号当公式。"""
    compact = text.replace(" ", "")
    if len(compact) < 2:
        return False
    symbols = set("=≈≤≥±∑∫√∞→←×·^_/")
    return any(ch in text for ch in symbols) or bool(re.search(r"[_^]|\\[a-zA-Z]+", text))


def _nearest_image_bbox(
    caption_bbox: list[float],
    image_boxes: list[list[float]],
    page_rect: list[float] | None,
) -> tuple[list[float], str]:
    """图在注上方同栏：返回图像框与 crop_mode=image；否则 caption 上方约 220pt 作 page_fallback。"""
    if caption_bbox and len(caption_bbox) == 4:
        cx0, cy0, cx1, _cy1 = caption_bbox
        mid = (cx0 + cx1) / 2
        best: list[float] | None = None
        best_score = 1e9
        for box in image_boxes:
            if len(box) != 4:
                continue
            x0, y0, x1, y1 = box
            # 图注下方的框图忽略（常是下一张图）；跨栏加惩罚以免左右栏配错
            if y1 > cy0 + 12:
                continue
            dist = cy0 - y1
            col_penalty = 0.0 if abs((x0 + x1) / 2 - mid) < 90 else 80.0
            score = dist + col_penalty
            if score < best_score:
                best_score = score
                best = box
        if best:
            return best, "image"
        # 无嵌入图时仍裁 caption 上方区域，电路矢量图至少能进 MinIO
        y0 = max(cy0 - 220, float((page_rect or [0, 0, 0, 0])[1] or 40))
        return [cx0 - 8, y0, cx1 + 8, cy0 - 4], "page_fallback"
    if image_boxes:
        return image_boxes[0], "image"
    return [], "missing"


def _nearby_text(page_text: str, eq_id: str, window: int = 240) -> str:
    """截公式编号附近正文，给 Vision/抽取当上下文，避免只看到裸 latex。"""
    needle = f"({eq_id})"
    idx = page_text.find(needle)
    if idx < 0:
        return page_text[:window]
    start = max(idx - window, 0)
    end = min(idx + window, len(page_text))
    return page_text[start:end].strip()


def _expand_cite_keys(text: str) -> list[str]:
    """把 [1,3–5] 展开成独立编号，供引用清单与 cited_in_sections 对齐。"""
    nums: list[str] = []
    for match in CITE_RE.finditer(text):
        blob = match.group(1)
        for part in re.split(r"[,;]", blob):
            part = part.strip()
            range_match = re.match(r"(\d+)\s*[–-]\s*(\d+)", part)
            if range_match:
                lo, hi = int(range_match.group(1)), int(range_match.group(2))
                # 上限 400：挡住页码或乱码被当成超长引用区间
                nums.extend(str(n) for n in range(lo, hi + 1) if 0 < n < 400)
            elif part.isdigit():
                nums.append(part)
    return nums


def _merge_bbox(a: list[float], b: list[float]) -> list[float]:
    """合并公式体与独立编号行的框，保证裁 PNG 时编号仍在图内。"""
    if not a:
        return b
    if not b:
        return a
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _clean_cell(value: Any) -> str:
    """表格单元格压成单行空白，避免换行破坏后续检索文本。"""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _guess_title(text: str) -> str:
    """XMP 无 title 时用首页第一条合适长度的非节标题行，避免把 Abstract 当篇名。"""
    for line in text.splitlines():
        stripped = line.strip()
        if 12 <= len(stripped) <= 180 and not NAMED_SECTION_RE.match(stripped):
            return stripped
    return ""


def _unique_by(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """跨页重复出现的 Fig./Eq. 只留首次，避免清单与知识单元重复。"""
    seen: dict[str, dict[str, Any]] = {}
    for item in items:
        value = str(item.get(key) or "")
        if value and value not in seen:
            seen[value] = item
    return list(seen.values())
