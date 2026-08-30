from __future__ import annotations

import asyncio
import base64
import ssl
import time
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import requests
import yuxi.knowledge.parser.factory as factory_module
import yuxi.knowledge.parser.unified as parser_unified
from docx import Document
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from yuxi.knowledge.parser.base import DocumentParserException
from yuxi.knowledge.parser.deepseek_ocr import DeepSeekOCRParser, DeepSeekVisionParser
from yuxi.knowledge.parser.factory import DocumentProcessorFactory
from yuxi.knowledge.parser.mineru import MinerUParser
from yuxi.knowledge.parser.mineru_official import MinerUOfficialParser
from yuxi.knowledge.parser.pdf_visual import is_visual_page, page_has_raster_image
from yuxi.knowledge.parser.pp_structure_v3 import PPStructureV3Parser
from yuxi.knowledge.parser.rapid_ocr import RapidOCRParser
from yuxi.knowledge.parser.registry import PROCESSOR_TYPES, get_parser_metadata
from yuxi.services.ocr_service import parse_document


def test_factory_cache_key_does_not_contain_credential():
    cache_key = DocumentProcessorFactory._build_cache_key("deepseek_ocr", {"api_key": "top-secret"})

    assert cache_key.startswith("deepseek_ocr|")
    assert "top-secret" not in cache_key


def test_clear_cache_can_target_single_engine(monkeypatch: pytest.MonkeyPatch):
    first = SimpleNamespace()
    second = SimpleNamespace()
    monkeypatch.setattr(
        factory_module,
        "_PROCESSOR_CACHE",
        {"rapid_ocr|one": first, "mineru_ocr|two": second},
    )

    DocumentProcessorFactory.clear_cache("rapid_ocr")

    assert factory_module._PROCESSOR_CACHE == {"mineru_ocr|two": second}


def test_parser_metadata_comes_from_parser_classes():
    metadata = {engine_id: get_parser_metadata(engine_id) for engine_id in PROCESSOR_TYPES}

    assert metadata["rapid_ocr"] == {
        "service_name": "rapid_ocr",
        "display_name": "RapidOCR (ONNX)",
        "supported_extensions": RapidOCRParser.supported_extensions,
    }
    assert all(item["service_name"] == engine_id for engine_id, item in metadata.items())
    assert all(item["display_name"] for item in metadata.values())


def test_mineru_parser_normalizes_trailing_slash():
    parser = MinerUParser(server_url="http://mineru-api:30001/")

    assert parser.server_url == "http://mineru-api:30001"
    assert parser.parse_endpoint == "http://mineru-api:30001/file_parse"


def test_mineru_official_health_check_does_not_create_task(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "yuxi.knowledge.parser.mineru_official.requests.post",
        lambda *args, **kwargs: pytest.fail("健康检查不应创建解析任务"),
    )

    health = MinerUOfficialParser(api_key="test-key").check_health()

    assert health["status"] == "configured"


def test_mineru_official_parsing_does_not_reject_configured_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    file_path = tmp_path / "mineru.pdf"
    file_path.write_bytes(b"pdf")
    parser = MinerUOfficialParser(api_key="test-key")

    monkeypatch.setattr(parser, "_upload_file", lambda *args, **kwargs: "batch-id")
    monkeypatch.setattr(
        parser,
        "_poll_batch_result",
        lambda *args, **kwargs: {"state": "done", "full_zip_url": "https://example.test/result.zip"},
    )

    def raise_download_error(*args, **kwargs):
        raise RuntimeError("use markdown fallback")

    monkeypatch.setattr(parser, "_download_zip", raise_download_error)
    monkeypatch.setattr(parser, "_download_and_extract", lambda *args, **kwargs: "parsed markdown")

    assert parser.process_file(str(file_path)) == "parsed markdown"


def test_rapid_ocr_health_check_does_not_load_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "yuxi.knowledge.parser.rapid_ocr.RapidOCR",
        lambda *args, **kwargs: pytest.fail("健康检查不应加载 OCR 模型"),
    )

    health = RapidOCRParser().check_health()

    assert health["status"] == "healthy"


def _build_pdf(file_path: Path, text: str) -> None:
    """用 pypdf 构造带文本的最小 PDF（pypdfium2 只读不能写，测试造 PDF 改用 pypdf）。"""
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        }
    )
    resources = DictionaryObject()
    resources[NameObject("/Font")] = DictionaryObject({NameObject("/F1"): font})
    page[NameObject("/Resources")] = writer._add_object(resources)
    writer.write(str(file_path))


def _build_two_page_pdf(file_path: Path, first_text: str, second_text: str) -> None:
    writer = PdfWriter()
    for text in (first_text, second_text):
        page = writer.add_blank_page(width=595, height=842)
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            }
        )
        resources = DictionaryObject()
        resources[NameObject("/Font")] = DictionaryObject({NameObject("/F1"): font})
        page[NameObject("/Resources")] = writer._add_object(resources)
    writer.write(str(file_path))


def _build_docx(file_path: Path, text: str) -> None:
    document = Document()
    document.add_paragraph(text)
    document.save(str(file_path))


def _build_png(file_path: Path) -> None:
    image = Image.new("RGB", (120, 80), "white")
    image.save(str(file_path))


@pytest.mark.asyncio
async def test_parse_document_pdf_returns_markdown_text(tmp_path: Path):
    file_path = tmp_path / "parser_test.pdf"
    _build_pdf(file_path, "Parser PDF content")

    markdown = await parse_document(str(file_path), params={"ocr_engine": "disable"})

    assert "Parser" in markdown
    assert "content" in markdown


@pytest.mark.asyncio
async def test_parse_document_docx_returns_markdown_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    file_path = tmp_path / "parser_test.docx"
    _build_docx(file_path, "Parser DOCX content")

    # 避免测试依赖 docling 行为，直接验证统一 parser 可回退到 python-docx。
    def _raise_docling_error(*args, **kwargs):
        raise RuntimeError("force fallback to python-docx")

    monkeypatch.setattr(parser_unified, "_convert_with_docling", _raise_docling_error)

    markdown = await parse_document(str(file_path))

    assert "Parser DOCX content" in markdown


def test_convert_csv_to_markdown_preserves_column_dtypes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "parser_test.csv"
    file_path.write_text("id,score\n9007199254740993,2.5\n", encoding="utf-8")
    captured_dtypes: list[dict[str, object]] = []
    original_to_markdown = pd.DataFrame.to_markdown

    def _capture_dtypes(dataframe: pd.DataFrame, *args, **kwargs) -> str:
        captured_dtypes.append(dataframe.dtypes.to_dict())
        return original_to_markdown(dataframe, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_markdown", _capture_dtypes)

    markdown = parser_unified._convert_csv_to_markdown(file_path)

    assert markdown
    assert str(captured_dtypes[0]["id"]) == "int64"


def test_convert_with_docling_reinserts_image_links_in_document_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    file_path = tmp_path / "parser_test.docx"
    file_path.write_bytes(b"fake docx")
    first_image = base64.b64encode(b"first image").decode()
    second_image = base64.b64encode(b"second image").decode()
    fake_doc = SimpleNamespace(
        pictures=[
            SimpleNamespace(image=SimpleNamespace(uri=f"data:image/png;base64,{first_image}")),
            SimpleNamespace(image=SimpleNamespace(uri="https://example.test/remote.png")),
            SimpleNamespace(image=SimpleNamespace(uri=f"data:image/png;base64,{second_image}")),
        ],
        export_to_markdown=lambda: "before\n<!-- image -->\nremote\n<!-- image -->\nbetween\n<!-- image -->\nafter",
    )
    fake_result = SimpleNamespace(status=SimpleNamespace(name="SUCCESS"), document=fake_doc)
    uploaded_images: list[bytes] = []

    class FakeConverter:
        def convert(self, path: Path):
            assert path == file_path
            return fake_result

    def _fake_upload_image_to_minio(image_data, filename, bucket_name, object_prefix):
        uploaded_images.append(image_data)
        return f"https://example.test/{len(uploaded_images)}.png"

    monkeypatch.setattr(parser_unified, "_get_docling_converter", lambda: FakeConverter())
    monkeypatch.setattr(parser_unified, "_upload_image_to_minio", _fake_upload_image_to_minio)
    image_timestamps = iter([1.0, 2.0])
    monkeypatch.setattr(parser_unified.time, "time", lambda: next(image_timestamps))

    markdown = parser_unified._convert_with_docling(file_path)

    assert uploaded_images == [b"first image", b"second image"]
    assert markdown == (
        "before\n"
        "![image_1000000.png](https://example.test/1.png)\n"
        "remote\n"
        "\n"
        "between\n"
        "![image_2000000.png](https://example.test/2.png)\n"
        "after"
    )


def test_convert_with_docling_keeps_image_placeholder_when_upload_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    file_path = tmp_path / "parser_test.docx"
    file_path.write_bytes(b"fake docx")
    image = base64.b64encode(b"image data").decode()
    fake_doc = SimpleNamespace(
        pictures=[SimpleNamespace(image=SimpleNamespace(uri=f"data:image/png;base64,{image}"))],
        export_to_markdown=lambda: "before\n<!-- image -->\nafter",
    )
    fake_result = SimpleNamespace(status=SimpleNamespace(name="SUCCESS"), document=fake_doc)

    class FakeConverter:
        def convert(self, path: Path):
            assert path == file_path
            return fake_result

    def _raise_upload_error(*args, **kwargs):
        raise RuntimeError("upload failed")

    monkeypatch.setattr(parser_unified, "_get_docling_converter", lambda: FakeConverter())
    monkeypatch.setattr(parser_unified, "_upload_image_to_minio", _raise_upload_error)
    monkeypatch.setattr(parser_unified.time, "time", lambda: 1.0)

    markdown = parser_unified._convert_with_docling(file_path)

    assert markdown == "before\n[图片: image_1000000.png]\nafter"


@pytest.mark.asyncio
async def test_parse_document_png_returns_markdown_text_with_mocked_ocr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    file_path = tmp_path / "parser_test.png"
    _build_png(file_path)

    async def _fake_parse_image_async(file, params=None):
        return "Parser PNG content"

    async def _resolve_params(params=None, db=None):
        del db
        return params or {}

    monkeypatch.setattr(parser_unified, "parse_image_async", _fake_parse_image_async)
    monkeypatch.setattr("yuxi.services.ocr_service.resolve_ocr_task_params", _resolve_params)

    markdown = await parse_document(str(file_path), params={"ocr_engine": "rapid_ocr"})

    assert "Parser PNG content" in markdown


def test_parse_image_ignores_ocr_engine_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "parser_test.png"
    _build_png(file_path)
    captured = {}

    def _fake_process_file(processor_type, file, params=None, processor_kwargs=None):
        captured["processor_type"] = processor_type
        captured["file"] = file
        captured["params"] = params
        return "OCR content"

    monkeypatch.setattr(DocumentProcessorFactory, "process_file", _fake_process_file)

    result = parser_unified.parse_image(
        str(file_path),
        params={
            "ocr_engine": "mineru_ocr",
            "backend": "old-backend",
            "ocr_engine_config": {"backend": "pipeline", "formula_enable": False},
        },
    )

    assert result == "OCR content"
    assert captured["processor_type"] == "mineru_ocr"
    assert captured["file"] == str(file_path)
    assert captured["params"]["backend"] == "old-backend"
    assert "formula_enable" not in captured["params"]


def test_parse_image_ignores_enable_ocr(tmp_path: Path) -> None:
    file_path = tmp_path / "parser_test.png"
    _build_png(file_path)

    with pytest.raises(ValueError, match="必须启用OCR"):
        parser_unified.parse_image(str(file_path), params={"ocr_engine": "disable", "enable_ocr": "rapid_ocr"})


def test_low_level_pdf_parser_requires_resolved_ocr_engine(tmp_path: Path) -> None:
    file_path = tmp_path / "parser_test.pdf"
    _build_pdf(file_path, "Parser PDF content")

    with pytest.raises(ValueError, match="请通过 parse_document"):
        parser_unified.parse_pdf(str(file_path), params={})


@pytest.mark.asyncio
async def test_parse_document_docx_does_not_block_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "parser_test_async.docx"
    file_path.write_bytes(b"fake docx")
    completion_order: list[str] = []

    def _slow_docling_conversion(*args, **kwargs) -> str:
        time.sleep(0.1)
        return "Async DOCX content"

    async def _parse_document() -> None:
        await parse_document(str(file_path))
        completion_order.append("parse")

    async def _record_event_loop_progress() -> None:
        await asyncio.sleep(0.01)
        completion_order.append("event_loop")

    monkeypatch.setattr(parser_unified, "_convert_with_docling", _slow_docling_conversion)

    await asyncio.gather(_parse_document(), _record_event_loop_progress())

    assert completion_order == ["event_loop", "parse"]


@pytest.mark.asyncio
async def test_parse_document_uses_config_default_ocr_when_engine_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "parser_test.pdf"
    _build_pdf(file_path, "Parser PDF content")
    captured = {}

    def _fake_process_file(processor_type, file, params=None, processor_kwargs=None):
        captured["processor_type"] = processor_type
        captured["file"] = file
        captured["params"] = params
        return "default OCR content"

    async def _build_processor_kwargs(db, engine_id):
        del db, engine_id
        return {}

    async def _system_options_get(_option, _db=None):
        return {"default_ocr_engine": "mineru_ocr"}

    monkeypatch.setattr("yuxi.config.options.Option.get", _system_options_get)
    monkeypatch.setattr(DocumentProcessorFactory, "process_file", _fake_process_file)
    monkeypatch.setattr("yuxi.services.ocr_service._build_processor_kwargs", _build_processor_kwargs)

    result = await parse_document(str(file_path), params={}, db=object())

    assert result == "default OCR content"
    assert captured["processor_type"] == "mineru_ocr"
    assert captured["file"] == str(file_path)


def test_parse_pdf_keeps_explicit_disable_when_default_ocr_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "parser_test.pdf"
    _build_pdf(file_path, "Parser PDF content")
    result = parser_unified.parse_pdf(str(file_path), params={"ocr_engine": "disable"})

    assert "Parser PDF content" in result


def test_pdfreader_preserves_searchable_visual_page_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "visual.pdf"
    _build_pdf(file_path, "Figure 7 Stress contour")
    uploaded: list[tuple[bytes, str, str, str]] = []

    def _fake_upload(data, filename, bucket_name, object_prefix, *, stable_name=False):
        uploaded.append((data, filename, bucket_name, object_prefix))
        assert stable_name is True
        return "/api/knowledge/databases/kb-1/images/kb-images/pdf-pages/page_0001.png"

    monkeypatch.setattr(parser_unified, "_upload_image_to_minio", _fake_upload)

    markdown = parser_unified.pdfreader(
        file_path,
        params={
            "preserve_page_images": True,
            "image_bucket": "kb-images",
            "image_prefix": "kb-1/kb-images",
        },
    )

    assert "## Page 1" in markdown
    assert "![Figure 7 Stress contour]" in markdown
    assert "Figure 7 Stress contour" in markdown
    assert uploaded[0][1:] == ("page_0001.png", "kb-images", "kb-1/kb-images/pdf-pages")
    assert uploaded[0][0].startswith(b"\x89PNG")


def test_pdfreader_preserves_english_table_page_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "table.pdf"
    _build_pdf(file_path, "Table 18 PEEQ RF S")
    uploaded: list[str] = []

    def _fake_upload(data, filename, bucket_name, object_prefix, *, stable_name=False):
        del data, bucket_name, object_prefix
        assert stable_name is True
        uploaded.append(filename)
        return "/api/knowledge/databases/kb-1/images/kb-images/pdf-pages/page_0001.png"

    monkeypatch.setattr(parser_unified, "_upload_image_to_minio", _fake_upload)

    markdown = parser_unified.pdfreader(
        file_path,
        params={
            "preserve_page_images": True,
            "image_bucket": "kb-images",
            "image_prefix": "kb-1/kb-images",
        },
    )

    assert "![Table 18 PEEQ RF S]" in markdown
    assert uploaded == ["page_0001.png"]


def test_pdfreader_does_not_render_plain_text_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "plain.pdf"
    _build_pdf(file_path, "Plain text only")
    monkeypatch.setattr(
        parser_unified,
        "_upload_image_to_minio",
        lambda *args, **kwargs: pytest.fail("plain page should not be rendered"),
    )

    markdown = parser_unified.pdfreader(file_path, params={"preserve_page_images": True})

    assert markdown == "## Page 1\n\nPlain text only"


@pytest.mark.parametrize(
    "text",
    [
        "Figure out the next step",
        "Table of contents",
        "表明该方法可以工作",
        "图书馆开放时间",
    ],
)
def test_visual_page_caption_detection_rejects_plain_prose(text: str) -> None:
    page = SimpleNamespace(get=lambda key: None)

    assert is_visual_page(text, page) is False


@pytest.mark.parametrize(
    "caption",
    [
        "Figure A-2 Stress contour",
        "Fig. IV Mesh detail",
        "Table 3.1 Material properties",
        "图 2-1 接触示意图",
        "表三 材料参数",
    ],
)
def test_visual_page_caption_detection_accepts_numbered_captions(caption: str) -> None:
    page = SimpleNamespace(get=lambda key: None)

    assert is_visual_page(caption, page) is True


def test_visual_page_detects_raster_image_nested_in_form_xobject() -> None:
    class PdfObject(dict):
        def get_object(self):
            return self

    image = PdfObject({"/Subtype": "/Image"})
    form = PdfObject(
        {
            "/Subtype": "/Form",
            "/Resources": PdfObject({"/XObject": PdfObject({"/Im1": image})}),
        }
    )
    page = PdfObject({"/Resources": PdfObject({"/XObject": PdfObject({"/Fm1": form})})})

    assert page_has_raster_image(page) is True


def test_pdf_visual_render_scale_caps_pixel_area_and_dimensions() -> None:
    normal_scale = parser_unified._bounded_pdf_render_scale(595, 842, 144)
    huge_scale = parser_unified._bounded_pdf_render_scale(50_000, 50_000, 144)
    panoramic_scale = parser_unified._bounded_pdf_render_scale(100_000, 100, 144)

    assert normal_scale == pytest.approx(2.0)
    assert 50_000 * huge_scale <= parser_unified._PDF_PAGE_RENDER_MAX_DIMENSION
    assert (50_000 * huge_scale) ** 2 <= parser_unified._PDF_PAGE_RENDER_MAX_PIXELS
    assert 100_000 * panoramic_scale <= parser_unified._PDF_PAGE_RENDER_MAX_DIMENSION


def test_pdfreader_reports_page_image_upload_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "visual-upload-error.pdf"
    _build_pdf(file_path, "Figure 3 Failure path")

    def _raise_upload_error(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("minio unavailable")

    monkeypatch.setattr(parser_unified, "_upload_image_to_minio", _raise_upload_error)

    with pytest.raises(DocumentParserException) as exc_info:
        parser_unified.pdfreader(file_path, params={"preserve_page_images": True})

    assert exc_info.value.service_name == "pdf_visual"
    assert exc_info.value.status_code == "page_image_failed"
    assert "page=1" in str(exc_info.value)


@pytest.mark.parametrize("ocr_engine", ["rapid_ocr", "pp_structure_v3_ocr"])
def test_text_only_ocr_appends_visual_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ocr_engine: str,
) -> None:
    file_path = tmp_path / "ocr_visual.pdf"
    _build_pdf(file_path, "Figure 9 Contact force diagram")
    monkeypatch.setattr(
        DocumentProcessorFactory,
        "process_file",
        lambda *args, **kwargs: "OCR text",
    )
    monkeypatch.setattr(
        parser_unified,
        "_upload_image_to_minio",
        lambda *args, **kwargs: "/api/knowledge/databases/kb-1/images/kb-images/pdf-pages/page_0001.png",
    )

    markdown = parser_unified.parse_pdf(
        str(file_path),
        params={
            "ocr_engine": ocr_engine,
            "preserve_page_images": True,
            "image_bucket": "kb-images",
            "image_prefix": "kb-1/kb-images",
        },
    )

    assert markdown.startswith("OCR text\n\n# Visual pages\n\n## Page 1")
    assert "![Figure 9 Contact force diagram]" in markdown
    assert markdown.endswith("Figure 9 Contact force diagram")


def test_rapid_ocr_preserves_pdf_page_boundaries_for_page_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "rapid-pages.pdf"
    _build_two_page_pdf(file_path, "source one", "source two")
    parser = RapidOCRParser()
    page_texts = iter(["## Page 99\n\nOCR page one", "OCR page two"])
    monkeypatch.setattr(parser, "process_image", lambda image: next(page_texts))

    markdown = parser.process_pdf(str(file_path), {"preserve_page_images": True})

    assert markdown == "## Page 1\n\nOCR page one\n\n## Page 2\n\nOCR page two"


def test_deepseek_ocr_preserves_pdf_page_boundaries_for_page_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "deepseek-pages.pdf"
    _build_two_page_pdf(file_path, "source one", "source two")
    parser = DeepSeekOCRParser(api_key="test-key")
    page_texts = iter(["OCR page one", "OCR page two"])
    monkeypatch.setattr(parser, "_call_api", lambda *args, **kwargs: next(page_texts))

    markdown = parser._process_pdf(str(file_path), {"preserve_page_images": True})

    assert markdown == "## Page 1\n\nOCR page one\n\n## Page 2\n\nOCR page two"


def test_pp_structure_preserves_pdf_page_boundaries_for_page_images() -> None:
    parser = PPStructureV3Parser(server_url="http://paddlex.test")
    api_result = {
        "result": {
            "layoutParsingResults": [
                {"markdown": {"text": "OCR page one"}},
                {"markdown": {"text": "OCR page two"}},
            ]
        }
    }

    result = parser._parse_api_result(
        api_result,
        "manual.pdf",
        include_page_headings=True,
    )

    assert result["full_text"] == "## Page 1\n\nOCR page one\n\n## Page 2\n\nOCR page two"


@pytest.mark.parametrize(
    "ocr_engine",
    ["rapid_ocr", "pp_structure_v3_ocr", "deepseek_ocr", "paddleocr_pp_ocrv6"],
)
def test_text_only_ocr_binds_page_image_to_same_ocr_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ocr_engine: str,
) -> None:
    file_path = tmp_path / "ocr-page-bound.pdf"
    _build_two_page_pdf(file_path, "Plain introduction", "Figure 2 Stress contour")
    ocr_markdown = "## Page 1\n\nOCR introduction\n\n## Page 2\n\nOCR stress results"
    monkeypatch.setattr(
        DocumentProcessorFactory,
        "process_file",
        lambda *args, **kwargs: ocr_markdown,
    )
    image_url = (
        "/api/knowledge/databases/kb-1/images/"
        "kb-images/file-1/pdf-pages/page_0002.png"
    )
    image_markdown = f"![Figure 2 Stress contour]({image_url})"
    monkeypatch.setattr(
        parser_unified,
        "_upload_image_to_minio",
        lambda *args, **kwargs: image_url,
    )

    markdown = parser_unified.parse_pdf(
        str(file_path),
        params={
            "ocr_engine": ocr_engine,
            "preserve_page_images": True,
            "image_bucket": "kb-images",
            "image_prefix": "kb-1/kb-images/file-1",
        },
    )

    page_one, page_two = markdown.split("## Page 2", 1)
    assert "# Visual pages" not in markdown
    assert image_markdown not in page_one
    assert page_two.startswith(f"\n\n{image_markdown}\n\nOCR stress results")


def test_deepseek_vision_only_calls_visual_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "vision.pdf"
    _build_two_page_pdf(file_path, "Plain introduction", "Figure 2 Stress contour")
    parser = DeepSeekVisionParser(api_key="test-key")
    calls: list[bytes] = []

    def _fake_call_api(data_bytes, mime_type, params):
        calls.append(data_bytes)
        assert mime_type == "image/png"
        return "A colored stress contour plot."

    monkeypatch.setattr(parser, "_call_api", _fake_call_api)

    markdown = parser._process_pdf(str(file_path), {})

    assert len(calls) == 1
    assert calls[0].startswith(b"\x89PNG")
    assert "## Page 1\n\nPlain introduction" in markdown
    assert "## Page 2\n\nFigure 2 Stress contour" in markdown
    assert "### Visual description\n\nA colored stress contour plot." in markdown


def test_deepseek_vision_uses_official_multimodal_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = DeepSeekVisionParser(api_key="test-key")
    captured = {}

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "visual markdown"}}]}

    def _post(url, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr("yuxi.knowledge.parser.deepseek_ocr.requests.post", _post)

    result = parser._call_api(b"image", "image/png", {})

    assert result == "visual markdown"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["json"]["model"] == "deepseek-v4-flash-vision-exp"
    assert captured["json"]["thinking"] == {"type": "disabled"}
    prompt = captured["json"]["messages"][0]["content"][1]["text"]
    assert "<image>" not in prompt
    assert "visual description" in prompt


def test_deepseek_vision_retries_ssl_eof_once(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = DeepSeekVisionParser(api_key="test-key")
    calls = []
    sleeps = []

    class Response:
        status_code = 200
        text = ""
        headers = {}

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "recovered"}}]}

    outcomes = iter(
        [
            requests.exceptions.SSLError(
                ssl.SSLEOFError(8, "[SSL: UNEXPECTED_EOF_WHILE_READING] unexpected eof")
            ),
            Response(),
        ]
    )

    def _post(*args, **kwargs):
        calls.append((args, kwargs))
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("yuxi.knowledge.parser.deepseek_ocr.requests.post", _post)
    monkeypatch.setattr("yuxi.knowledge.parser.deepseek_ocr.time.sleep", sleeps.append)

    result = parser._call_api(b"image", "image/png", {})

    assert result == "recovered"
    assert len(calls) == 2
    assert calls[0][1]["json"] == calls[1][1]["json"]
    assert sleeps == [1.0]


def test_deepseek_vision_does_not_retry_certificate_error(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = DeepSeekVisionParser(api_key="test-key")
    calls = []
    sleeps = []

    def _post(*args, **kwargs):
        calls.append((args, kwargs))
        raise requests.exceptions.SSLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))

    monkeypatch.setattr("yuxi.knowledge.parser.deepseek_ocr.requests.post", _post)
    monkeypatch.setattr("yuxi.knowledge.parser.deepseek_ocr.time.sleep", sleeps.append)

    with pytest.raises(DocumentParserException) as exc_info:
        parser._call_api(b"image", "image/png", {})

    assert exc_info.value.status_code == "network_error"
    assert len(calls) == 1
    assert sleeps == []


def test_deepseek_vision_caps_retry_after_for_transient_http_status(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = DeepSeekVisionParser(api_key="test-key")
    sleeps = []

    class Response:
        text = ""

        def __init__(self, status_code, headers=None):
            self.status_code = status_code
            self.headers = headers or {}

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "recovered"}}]}

    outcomes = iter([Response(429, {"Retry-After": "120"}), Response(200)])
    monkeypatch.setattr("yuxi.knowledge.parser.deepseek_ocr.requests.post", lambda *args, **kwargs: next(outcomes))
    monkeypatch.setattr("yuxi.knowledge.parser.deepseek_ocr.time.sleep", sleeps.append)

    assert parser._call_api(b"image", "image/png", {}) == "recovered"
    assert sleeps == [15.0]


def test_deepseek_vision_parse_binds_page_image_to_same_page_description(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "vision-bound.pdf"
    _build_two_page_pdf(file_path, "Plain introduction", "Figure 2 Stress contour")
    vision_markdown = (
        "## Page 1\n\nPlain introduction\n\n"
        "## Page 2\n\nFigure 2 Stress contour\n\n"
        "### Visual description\n\nA colored stress contour plot."
    )
    monkeypatch.setattr(
        DocumentProcessorFactory,
        "process_file",
        lambda *args, **kwargs: vision_markdown,
    )
    monkeypatch.setattr(
        parser_unified,
        "_upload_image_to_minio",
        lambda *args, **kwargs: (
            "/api/knowledge/databases/kb-1/images/"
            "kb-images/file-1/pdf-pages/page_0002.png"
        ),
    )

    markdown = parser_unified.parse_pdf(
        str(file_path),
        params={
            "ocr_engine": "deepseek_vision",
            "preserve_page_images": True,
            "image_bucket": "kb-images",
            "image_prefix": "kb-1/kb-images/file-1",
        },
    )

    page_two = markdown.split("## Page 2", 1)[1]
    image_markdown = (
        "![Figure 2 Stress contour](/api/knowledge/databases/kb-1/images/"
        "kb-images/file-1/pdf-pages/page_0002.png)"
    )
    after_image = page_two.split(image_markdown, 1)[1]
    assert "# Visual pages" not in markdown
    assert page_two.startswith(f"\n\n{image_markdown}")
    assert after_image.index("Figure 2 Stress contour") < after_image.index("### Visual description")
    assert "A colored stress contour plot." in page_two


def test_rapid_ocr_resolves_model_dir_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target_dir = tmp_path / "custom_models"
    monkeypatch.setenv("RAPIDOCR_MODEL_DIR", str(target_dir))
    parser = RapidOCRParser()
    params = parser._get_model_params()

    assert params["Global.model_root_dir"] == str(target_dir)
    assert target_dir.exists()
