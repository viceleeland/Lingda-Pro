from __future__ import annotations

import re
from typing import Any

from yuxi.knowledge.chunking.ragflow_like.parsers import book, general, laws, qa, semantic, separator
from yuxi.knowledge.chunking.ragflow_like.presets import map_to_internal_parser_id, normalize_chunk_preset_id

_PDF_PAGE_IMAGE_PATH = "/pdf-pages/page_"
_PDF_PAGE_HEADING_PATTERN = re.compile(r"(?m)^## Page \d+\s*$")
_PDF_PAGE_IMAGE_MARKDOWN_PATTERN = re.compile(
    r"!\[[^\]\n]*\]\([^\)\n]*/pdf-pages/page_[^\)\n]+\)"
)


def _build_chunk_records(
    text_chunks: list[str], file_id: str, filename: str, source_text: str | None = None
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    search_from = 0

    for idx, chunk_content in enumerate(text_chunks):
        text = (chunk_content or "").strip()
        if not text:
            continue

        start_char_pos = None
        end_char_pos = None
        if source_text:
            found_at = source_text.find(text, search_from)
            if found_at >= 0:
                start_char_pos = found_at
                end_char_pos = found_at + len(text)
                search_from = end_char_pos

        records.append(
            {
                "id": f"{file_id}_chunk_{idx}",
                "content": text,
                "file_id": file_id,
                "filename": filename,
                "chunk_index": idx,
                "source": filename,
                "chunk_id": f"{file_id}_chunk_{idx}",
                "start_char_pos": start_char_pos,
                "end_char_pos": end_char_pos,
                "start_token_pos": None,
                "end_token_pos": None,
                "extraction_result": None,
            }
        )

    return records


def _dispatch_markdown_parser(
    preset_id: str, filename: str, markdown_content: str, parser_config: dict[str, Any]
) -> list[str]:
    parser_id = map_to_internal_parser_id(preset_id)

    if parser_id == "naive":
        return general.chunk_markdown(markdown_content, parser_config)
    if parser_id == "qa":
        return qa.chunk_markdown(filename, markdown_content, parser_config)
    if parser_id == "book":
        return book.chunk_markdown(markdown_content, parser_config)
    if parser_id == "laws":
        return laws.chunk_markdown(filename, markdown_content, parser_config)
    if parser_id == "semantic":
        return semantic.chunk_markdown(markdown_content, parser_config)
    if parser_id == "separator":
        return separator.chunk_markdown(markdown_content, parser_config)

    return general.chunk_markdown(markdown_content, parser_config)


def _split_pdf_page_sections(markdown_content: str) -> list[str]:
    """页图 Markdown 按原 PDF 页隔离，避免 overlap 复制相邻页图片。"""

    if _PDF_PAGE_IMAGE_PATH not in markdown_content:
        return [markdown_content]

    matches = list(_PDF_PAGE_HEADING_PATTERN.finditer(markdown_content))
    if not matches:
        return [markdown_content]

    sections: list[str] = []
    prefix = markdown_content[: matches[0].start()].strip()
    if prefix:
        sections.append(prefix)
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_content)
        section = markdown_content[match.start() : end].strip()
        if section:
            sections.append(section)
    return sections


def _chunk_pdf_page_section(
    preset_id: str,
    filename: str,
    section: str,
    parser_config: dict[str, Any],
) -> list[str]:
    """页图不参与 overlap；分块后只绑定到该页首个 chunk。"""

    image_markdown = list(dict.fromkeys(_PDF_PAGE_IMAGE_MARKDOWN_PATTERN.findall(section)))
    if not image_markdown:
        return _dispatch_markdown_parser(preset_id, filename, section, parser_config)

    text_only_section = _PDF_PAGE_IMAGE_MARKDOWN_PATTERN.sub("", section)
    chunks = _dispatch_markdown_parser(preset_id, filename, text_only_section, parser_config)
    image_block = "\n\n".join(image_markdown)
    if not chunks:
        return [image_block]

    first_chunk = chunks[0].strip()
    heading = _PDF_PAGE_HEADING_PATTERN.search(first_chunk)
    if heading:
        chunks[0] = (
            f"{first_chunk[: heading.end()].rstrip()}\n\n"
            f"{image_block}\n\n{first_chunk[heading.end() :].strip()}"
        ).strip()
    else:
        chunks[0] = f"{image_block}\n\n{first_chunk}"
    return chunks


def chunk_markdown(
    markdown_content: str, file_id: str, filename: str, processing_params: dict[str, Any]
) -> list[dict[str, Any]]:
    params = dict(processing_params or {})
    preset_id = normalize_chunk_preset_id(params.get("chunk_preset_id"))
    parser_config = params.get("chunk_parser_config") if isinstance(params.get("chunk_parser_config"), dict) else {}

    text_chunks = []
    for section in _split_pdf_page_sections(markdown_content):
        text_chunks.extend(_chunk_pdf_page_section(preset_id, filename, section, parser_config))
    return _build_chunk_records(text_chunks, file_id, filename, markdown_content)


def chunk_file(
    file_content: str, file_id: str, filename: str, processing_params: dict[str, Any]
) -> list[dict[str, Any]]:
    # 当前链路中入库前均已转换为 markdown，因此与 chunk_markdown 保持同实现。
    return chunk_markdown(file_content, file_id, filename, processing_params)
