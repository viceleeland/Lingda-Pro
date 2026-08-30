"""
DeepSeek OCR Parser

Uses DeepSeek-OCR via SiliconFlow API for document parsing and OCR.
"""

import base64
import io
import os
import re
import ssl
import time
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import requests
from pypdf import PdfReader

from yuxi.knowledge.parser.base import BaseDocumentProcessor, DocumentParserException
from yuxi.knowledge.parser.pdf_visual import format_pdf_page_markdown, is_visual_page
from yuxi.utils import logger


_TRANSIENT_HTTP_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
_MAX_HTTP_ATTEMPTS = 2
_RETRY_BACKOFF_SECONDS = 1.0
_MAX_RETRY_AFTER_SECONDS = 15.0


def _is_retryable_request_error(error: requests.RequestException) -> bool:
    """仅识别适合安全重试一次的瞬时网络错误。"""

    if isinstance(error, requests.exceptions.SSLError):
        error_text = str(error).upper()
        return isinstance(error.__cause__, ssl.SSLEOFError) or "UNEXPECTED_EOF_WHILE_READING" in error_text
    return isinstance(
        error,
        (
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ReadTimeout,
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ConnectionError,
        ),
    )


def _retry_delay_seconds(response: requests.Response | None = None) -> float:
    if response is not None and response.status_code in {429, 503}:
        retry_after = (getattr(response, "headers", None) or {}).get("Retry-After")
        try:
            return min(max(float(retry_after), 0.0), _MAX_RETRY_AFTER_SECONDS)
        except (TypeError, ValueError):
            pass
    return _RETRY_BACKOFF_SECONDS


class DeepSeekOCRParser(BaseDocumentProcessor):
    """DeepSeek OCR Parser using SiliconFlow API"""

    service_name = "deepseek_ocr"
    display_name = "DeepSeek OCR"
    supported_extensions = [".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".webp"]
    api_key_env = "SILICONFLOW_API_KEY"
    default_api_url = "https://api.siliconflow.cn/v1/chat/completions"
    default_model = "deepseek-ai/DeepSeek-OCR"
    default_prompt = "<image>\n<|grounding|>Convert the document to markdown. "
    request_body_overrides: dict[str, Any] = {}

    # MIME type mapping for supported formats
    MIME_TYPE_MAP = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }

    def __init__(self, api_key: str | None = None, api_url: str | None = None):
        """使用配置中心传入的 SiliconFlow 凭证和固定服务端点初始化解析器。"""

        self.api_key = api_key or os.getenv(self.api_key_env)
        if not self.api_key:
            raise DocumentParserException(
                f"{self.api_key_env} environment variable not set",
                self.get_service_name(),
                "missing_api_key",
            )

        self.api_url = api_url or self.default_api_url
        self.model = self.default_model
        self.prompt = self.default_prompt

        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def check_health(self) -> dict[str, Any]:
        """Check API availability and key validity"""
        try:
            # We can't easily "ping" without cost, but we can check if the model list is accessible
            models_url = self.api_url.rsplit("/chat/completions", 1)[0] + "/models"
            response = requests.get(models_url, headers=self.headers, timeout=10)

            if response.status_code == 200:
                return {
                    "status": "healthy",
                    "message": f"{self.display_name} is available",
                    "details": {"api_url": self.api_url, "model": self.model},
                }
            elif response.status_code == 401:
                return {"status": "unhealthy", "message": "Invalid API Key", "details": {"error_code": "401"}}
            else:
                return {
                    "status": "unhealthy",
                    "message": f"API Error: {response.status_code}",
                    "details": {"status_code": response.status_code},
                }
        except Exception as e:
            return {"status": "unavailable", "message": f"Connection failed: {str(e)}", "details": {"error": str(e)}}

    def process_file(self, file_path: str, params: dict[str, Any] | None = None) -> str:
        """
        Process file using DeepSeek OCR via SiliconFlow
        """
        if not os.path.exists(file_path):
            raise DocumentParserException(f"File not found: {file_path}", self.get_service_name(), "file_not_found")

        file_ext = Path(file_path).suffix.lower()
        if not self.supports_file_type(file_ext):
            raise DocumentParserException(
                f"Unsupported file type: {file_ext}", self.get_service_name(), "unsupported_file_type"
            )

        try:
            start_time = time.time()
            logger.info(f"DeepSeek OCR starting: {os.path.basename(file_path)}")

            params = params or {}
            if file_ext == ".pdf":
                content = self._process_pdf(file_path, params)
            else:
                content = self._process_image(file_path, params)

            processing_time = time.time() - start_time
            logger.info(
                f"DeepSeek OCR finished: {os.path.basename(file_path)} - {len(content)} chars ({processing_time:.2f}s)"
            )

            return content

        except Exception as e:
            if isinstance(e, DocumentParserException):
                raise
            error_msg = f"DeepSeek OCR failed: {str(e)}"
            logger.error(error_msg)
            raise DocumentParserException(error_msg, self.get_service_name(), "processing_failed")

    def _process_pdf(self, file_path: str, params: dict[str, Any]) -> str:
        """Process PDF by converting pages to images"""
        pdf = pdfium.PdfDocument(file_path)
        try:
            full_text = []

            total_pages = len(pdf)
            logger.info(f"Processing PDF with {total_pages} pages")

            # pypdfium2 的 scale 是 72dpi 的倍数，200dpi 对应 scale=200/72
            scale = int(params.get("pdf_dpi", 200)) / 72

            for i in range(total_pages):
                logger.debug(f"Processing page {i + 1}/{total_pages}")
                bitmap = pdf[i].render(scale=scale).to_pil()
                buf = io.BytesIO()
                bitmap.save(buf, format="PNG")
                img_bytes = buf.getvalue()

                page_text = self._call_api(img_bytes, "image/png", params)
                if params.get("preserve_page_images"):
                    full_text.append(format_pdf_page_markdown(i + 1, page_text))
                else:
                    full_text.append(page_text)

            return "\n\n".join(full_text)
        finally:
            pdf.close()

    def _process_image(self, file_path: str, params: dict[str, Any]) -> str:
        """Process single image file"""
        mime_type = self._get_mime_type(file_path)
        with open(file_path, "rb") as f:
            file_content = f.read()
        return self._call_api(file_content, mime_type, params)

    def _call_api(self, data_bytes: bytes, mime_type: str, params: dict[str, Any]) -> str:
        """Call SiliconFlow API"""
        encoded_string = base64.b64encode(data_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{encoded_string}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": self.prompt},
                ],
            }
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": int(params.get("max_tokens", 4096)),
            "temperature": float(params.get("temperature", 0.1)),
        }
        payload.update(self.request_body_overrides)

        response = self._post_with_transient_retry(
            payload,
            timeout=int(params.get("timeout_seconds", 120)),
        )

        if response.status_code != 200:
            error_msg = f"API Error {response.status_code}: {response.text}"
            logger.error(error_msg)
            raise DocumentParserException(error_msg, self.get_service_name(), f"http_{response.status_code}")

        result = response.json()
        content = result["choices"][0]["message"]["content"]

        # Clean up special tags like <|ref|>...<|/ref|> and <|det|>...<|/det|>
        content = re.sub(r"<\|ref\|>.*?<\|/ref\|>", "", content)
        content = re.sub(r"<\|det\|>.*?<\|/det\|>", "", content)
        # content = re.sub(r"<\|.*?\|>", "", content)

        return content.strip()

    def _post_with_transient_retry(self, payload: dict[str, Any], *, timeout: int) -> requests.Response:
        """在单页请求边界对瞬时失败重试一次，避免重跑整本文档。"""

        for attempt in range(1, _MAX_HTTP_ATTEMPTS + 1):
            try:
                response = requests.post(
                    self.api_url,
                    headers=self.headers,
                    json=payload,
                    timeout=timeout,
                )
            except requests.RequestException as error:
                if attempt >= _MAX_HTTP_ATTEMPTS or not _is_retryable_request_error(error):
                    raise DocumentParserException(
                        f"Network request failed: {type(error).__name__}",
                        self.get_service_name(),
                        "network_error",
                    ) from error
                delay = _retry_delay_seconds()
                logger.warning(
                    f"{self.get_service_name()} transient network error "
                    f"({type(error).__name__}), retrying {attempt + 1}/{_MAX_HTTP_ATTEMPTS} "
                    f"after {delay:.1f}s"
                )
                time.sleep(delay)
                continue

            if response.status_code not in _TRANSIENT_HTTP_STATUS_CODES or attempt >= _MAX_HTTP_ATTEMPTS:
                return response

            delay = _retry_delay_seconds(response)
            logger.warning(
                f"{self.get_service_name()} transient HTTP {response.status_code}, "
                f"retrying {attempt + 1}/{_MAX_HTTP_ATTEMPTS} after {delay:.1f}s"
            )
            time.sleep(delay)

        raise AssertionError("unreachable")

    def _get_mime_type(self, file_path: str) -> str:
        file_ext = Path(file_path).suffix.lower()
        return self.MIME_TYPE_MAP.get(file_ext, "image/jpeg")  # Default fallback


class DeepSeekVisionParser(DeepSeekOCRParser):
    """使用 DeepSeek 官方视觉模型生成 Markdown 与视觉描述。"""

    service_name = "deepseek_vision"
    display_name = "DeepSeek 官方视觉"
    api_key_env = "DEEPSEEK_API_KEY"
    default_api_url = "https://api.deepseek.com/chat/completions"
    default_model = "deepseek-v4-flash-vision-exp"
    default_prompt = (
        "Convert this document image to Markdown. Preserve headings, tables, formulas, "
        "figure labels and visible text. Add a concise visual description of charts, "
        "diagrams, contours, colors and geometry."
    )
    request_body_overrides = {"thinking": {"type": "disabled"}}

    def _process_pdf(self, file_path: str, params: dict[str, Any]) -> str:
        """读取普通页文本，只对视觉页调用官方视觉模型。"""

        reader = PdfReader(file_path)
        pdf = pdfium.PdfDocument(file_path)
        scale = int(params.get("pdf_dpi", 160)) / 72
        pages: list[str] = []
        visual_page_count = 0

        try:
            for index, page in enumerate(reader.pages):
                page_number = index + 1
                text = (page.extract_text() or "").strip()
                parts = [f"## Page {page_number}"]
                if text:
                    parts.append(text)

                if is_visual_page(text, page):
                    bitmap = pdf[index].render(scale=scale).to_pil()
                    buffer = io.BytesIO()
                    bitmap.save(buffer, format="PNG")
                    description = self._call_api(buffer.getvalue(), "image/png", params)
                    parts.extend(["### Visual description", description])
                    visual_page_count += 1

                pages.append("\n\n".join(parts))
        finally:
            pdf.close()

        logger.info(
            f"DeepSeek Vision PDF completed: pages={len(reader.pages)}, visual_pages={visual_page_count}"
        )
        return "\n\n".join(pages)
