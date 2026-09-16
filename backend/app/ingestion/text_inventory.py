"""Recognize explicit Markdown/LaTeX structures without inventing missing media."""
import re


def enrich_text_inventory(structure: dict) -> dict:
    equations = structure.setdefault("equations", [])
    figures = structure.setdefault("figures", [])
    tables = structure.setdefault("tables", [])
    for page in structure.get("pages") or []:
        number = int(page.get("page") or 1)
        text = page.get("text") or ""
        for index, match in enumerate(re.finditer(r"\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]", text), 1):
            latex = (match.group(1) or match.group(2)).strip()
            equations.append({"eq_id": f"p{number}-math{index}", "page": number, "latex": latex,
                              "raw": match.group(0), "nearby_text": text[max(0, match.start()-120):match.end()+120], "bbox": []})
        for index, match in enumerate(re.finditer(r"!\[([^\]]*)\]\(([^\s)]+)(?:\s+[^)]*)?\)", text), 1):
            figures.append({"fig_id": f"p{number}-image{index}", "page": number, "caption": match.group(1),
                            "source_url": match.group(2), "bbox": [], "image_key": "", "asset_status": "linked_only"})
        lines = text.splitlines()
        index = 0
        while index + 1 < len(lines):
            if "|" in lines[index] and re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*", lines[index + 1]):
                rows = [[cell.strip() for cell in lines[index].strip().strip('|').split('|')]]
                index += 2
                while index < len(lines) and '|' in lines[index] and lines[index].strip():
                    rows.append([cell.strip() for cell in lines[index].strip().strip('|').split('|')])
                    index += 1
                tables.append({"table_id": f"p{number}-table{len(tables)+1}", "page": number, "rows": rows, "caption": ""})
            else:
                index += 1
    return structure
