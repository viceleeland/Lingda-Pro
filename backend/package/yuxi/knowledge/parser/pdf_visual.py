"""PDF 视觉页识别与图题提取。"""

from __future__ import annotations

import re
from typing import Any


VISUAL_CAPTION_PATTERN = re.compile(
    r"(?im)^\s*(?:"
    r"(?:figure|fig\.?|table)\s+"
    r"(?:[a-z]?\d+[a-z]?(?:[.-]\d+[a-z]?)*|[a-z](?:[.-]\d+)+|[ivxlcdm]+)"
    r"|(?:图|表)\s*(?:\d+[a-z]?(?:[.-]\d+[a-z]?)*|[一二三四五六七八九十百]+)"
    r")(?=\s|[:：,，.;()（）\-–—]|$)[^\n]*"
)
_LEADING_PAGE_HEADING_PATTERN = re.compile(r"\A## Page \d+\s*(?:\n+|\Z)", re.IGNORECASE)


def format_pdf_page_markdown(page_number: int, text: str) -> str:
    """用可信原页码包装单页正文，并去掉 OCR 可能重复返回的页标题。"""

    page_text = _LEADING_PAGE_HEADING_PATTERN.sub("", (text or "").strip(), count=1).strip()
    if page_text:
        return f"## Page {page_number}\n\n{page_text}"
    return f"## Page {page_number}"


def _xobjects_contain_raster_image(xobjects: Any, visited: set[int]) -> bool:
    """递归检查 XObject；图片常被包在 Form XObject 内。"""

    resolved = xobjects.get_object() if xobjects else {}
    for value in resolved.values():
        obj = value.get_object()
        identity = id(obj)
        if identity in visited:
            continue
        visited.add(identity)

        subtype = obj.get("/Subtype")
        if subtype == "/Image":
            return True
        if subtype != "/Form":
            continue

        resources = obj.get("/Resources")
        resources = resources.get_object() if resources else {}
        if _xobjects_contain_raster_image(resources.get("/XObject"), visited):
            return True
    return False


def page_has_raster_image(page: Any) -> bool:
    """检查 PDF 页资源中是否存在内嵌栅格图片。"""

    try:
        resources = page.get("/Resources")
        resources = resources.get_object() if resources else {}
        return _xobjects_contain_raster_image(resources.get("/XObject"), set())
    except Exception:
        return False


def is_visual_page(text: str, page: Any) -> bool:
    """按图题或内嵌图片判断页面是否需要保留视觉内容。"""

    return bool(VISUAL_CAPTION_PATTERN.search(text)) or page_has_raster_image(page)


def visual_page_caption(text: str, page_number: int) -> str:
    """返回适合 Markdown 图片替代文本的页图标题。"""

    match = VISUAL_CAPTION_PATTERN.search(text)
    caption = match.group(0).strip() if match else f"Page {page_number} visual content"
    return caption.replace("[", "").replace("]", "")
