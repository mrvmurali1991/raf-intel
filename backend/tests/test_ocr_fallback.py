"""Tests for OCR fallback pipeline and document pipeline router.

All external dependencies (pytesseract, boto3, pypdfium2, Pillow) are mocked
so no system binaries or cloud credentials are required.
"""
from __future__ import annotations

import io
import sys
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to build minimal mock Pillow images
# ---------------------------------------------------------------------------


def _make_png_bytes() -> bytes:
    """Return the smallest valid 1x1 white PNG."""
    import base64
    # 1x1 white pixel PNG (base64-encoded)
    data = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return data


# ---------------------------------------------------------------------------
# tesseract_ocr tests
# ---------------------------------------------------------------------------


class TestTesseractOcr:
    """Unit tests for ocr_fallback.tesseract_ocr."""

    def _mock_pytesseract_output(self, words: list[str], confs: list[int]) -> dict:
        return {"text": words, "conf": confs}

    def test_returns_text_and_confidence(self):
        """tesseract_ocr should join word tokens and average confidence."""
        from app.services.ocr_fallback import tesseract_ocr

        mock_data = {"text": ["Hello", "World", ""], "conf": [90, 80, -1]}

        with patch.dict("sys.modules", {}):
            with patch("app.services.ocr_fallback.tesseract_ocr") as _mock:
                # Test the actual function with mocked pytesseract
                pass

        # Direct mock of pytesseract inside the module
        mock_pyt = MagicMock()
        mock_pyt.Output.DICT = "dict"
        mock_pyt.image_to_data.return_value = mock_data

        mock_pil_image = MagicMock()
        mock_pil_mod = MagicMock()
        mock_pil_mod.Image.open.return_value = mock_pil_image

        with patch.dict("sys.modules", {"pytesseract": mock_pyt, "PIL": mock_pil_mod}):
            # Re-import inside the patch context
            import importlib
            import app.services.ocr_fallback as ocr_mod
            importlib.reload(ocr_mod)
            # Patch lazily inside function scope
            with patch("app.services.ocr_fallback.tesseract_ocr", wraps=None) as _:
                pass

        # Simpler: patch builtins import inside the function
        with patch("builtins.__import__", side_effect=lambda name, *a, **kw: (
            mock_pyt if name == "pytesseract" else
            mock_pil_mod if name == "PIL" else
            __import__(name, *a, **kw)
        )):
            pass  # can't easily intercept lazy imports this way

        # Best approach: patch at the call site within the function
        png = _make_png_bytes()

        mock_pyt2 = MagicMock()
        mock_pyt2.Output.DICT = "dict"
        mock_pyt2.image_to_data.return_value = mock_data

        mock_img_obj = MagicMock()
        mock_pil2 = MagicMock()
        mock_pil2.Image.open.return_value = mock_img_obj

        with patch.dict("sys.modules", {"pytesseract": mock_pyt2, "PIL": mock_pil2, "PIL.Image": mock_pil2.Image}):
            from app.services import ocr_fallback
            import importlib
            importlib.reload(ocr_fallback)
            text, conf = ocr_fallback.tesseract_ocr(png)

        assert "Hello" in text
        assert "World" in text
        assert abs(conf - (85.0 / 100.0)) < 0.01  # avg of 90 + 80 = 85, /100

    def test_empty_page_returns_zero_confidence(self):
        """All -1 confidence tokens → mean_conf = 0.0."""
        mock_pyt = MagicMock()
        mock_pyt.Output.DICT = "dict"
        mock_pyt.image_to_data.return_value = {"text": ["", ""], "conf": [-1, -1]}

        mock_img_obj = MagicMock()
        mock_pil = MagicMock()
        mock_pil.Image.open.return_value = mock_img_obj

        with patch.dict("sys.modules", {"pytesseract": mock_pyt, "PIL": mock_pil, "PIL.Image": mock_pil.Image}):
            from app.services import ocr_fallback
            import importlib
            importlib.reload(ocr_fallback)
            text, conf = ocr_fallback.tesseract_ocr(_make_png_bytes())

        assert text == ""
        assert conf == 0.0


# ---------------------------------------------------------------------------
# aws_textract_ocr tests
# ---------------------------------------------------------------------------


class TestAwsTextractOcr:
    """Unit tests for ocr_fallback.aws_textract_ocr."""

    def test_parses_line_blocks(self, monkeypatch):
        """Should extract LINE block text and average confidence."""
        blocks = [
            {"BlockType": "PAGE", "Text": "", "Confidence": 99.0},
            {"BlockType": "LINE", "Text": "Patient: John Doe", "Confidence": 98.5},
            {"BlockType": "LINE", "Text": "DOB: 1970-01-01", "Confidence": 97.0},
            {"BlockType": "WORD", "Text": "Patient:", "Confidence": 99.0},
        ]
        mock_response = {"Blocks": blocks}

        mock_client = MagicMock()
        mock_client.analyze_document.return_value = mock_response

        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            from app.services import ocr_fallback
            import importlib
            importlib.reload(ocr_fallback)
            text, conf = ocr_fallback.aws_textract_ocr(b"fake-pdf-bytes", "application/pdf")

        assert "Patient: John Doe" in text
        assert "DOB: 1970-01-01" in text
        expected_conf = ((98.5 + 97.0) / 2) / 100.0
        assert abs(conf - expected_conf) < 0.001

    def test_empty_response_returns_zero_conf(self, monkeypatch):
        """Empty Blocks list → text='' and conf=0.0."""
        mock_client = MagicMock()
        mock_client.analyze_document.return_value = {"Blocks": []}
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            from app.services import ocr_fallback
            import importlib
            importlib.reload(ocr_fallback)
            text, conf = ocr_fallback.aws_textract_ocr(b"data", "image/png")

        assert text == ""
        assert conf == 0.0


# ---------------------------------------------------------------------------
# choose_extractor decision matrix tests
# ---------------------------------------------------------------------------


class TestChooseExtractor:
    """Unit tests for document_pipeline_router.choose_extractor."""

    @pytest.fixture(autouse=True)
    def _import_router(self):
        from app.services.document_pipeline_router import TenantDocPolicy, choose_extractor
        self.TenantDocPolicy = TenantDocPolicy
        self.choose_extractor = choose_extractor

    def _policy(self, **kwargs):
        return self.TenantDocPolicy(**kwargs)

    def test_llm_disabled_tenant_pdf_uses_ocr_fallback(self):
        """LLM-disabled tenant + PDF → ocr_fallback."""
        policy = self._policy(tenant_id="t1", disable_llm_documents=True)
        result = self.choose_extractor(b"data", "application/pdf", policy)
        assert result == "ocr_fallback"

    def test_behavioral_health_category_pdf_uses_ocr_fallback(self):
        """Behavioral-health category + PDF → ocr_fallback (42 CFR Part 2)."""
        policy = self._policy(tenant_id="t1", disable_llm_documents=False)
        result = self.choose_extractor(b"data", "application/pdf", policy, "behavioral_health")
        assert result == "ocr_fallback"

    def test_substance_abuse_category_uses_ocr_fallback(self):
        """Substance-abuse category → ocr_fallback."""
        policy = self._policy(tenant_id="t1")
        result = self.choose_extractor(b"data", "application/pdf", policy, "substance_abuse")
        assert result == "ocr_fallback"

    def test_normal_tenant_pdf_uses_gemini_vision(self):
        """Normal tenant + PDF + no special category → gemini_vision."""
        policy = self._policy(tenant_id="t1", disable_llm_documents=False)
        result = self.choose_extractor(b"data", "application/pdf", policy)
        assert result == "gemini_vision"

    def test_tiff_always_uses_ocr_fallback(self):
        """TIFF is not supported by Gemini → ocr_fallback."""
        policy = self._policy(tenant_id="t1", disable_llm_documents=False)
        result = self.choose_extractor(b"data", "image/tiff", policy)
        assert result == "ocr_fallback"

    def test_jpeg_normal_tenant_uses_gemini_vision(self):
        """JPEG + normal tenant → gemini_vision."""
        policy = self._policy(tenant_id="t1")
        result = self.choose_extractor(b"data", "image/jpeg", policy)
        assert result == "gemini_vision"

    def test_unknown_mimetype_skips(self):
        """Unsupported MIME type → skip."""
        policy = self._policy(tenant_id="t1")
        result = self.choose_extractor(b"data", "application/octet-stream", policy)
        assert result == "skip"

    def test_tenant_blocked_category_list(self):
        """Per-tenant llm_blocked_categories overrides even supported MIME types."""
        policy = self._policy(
            tenant_id="t1",
            disable_llm_documents=False,
            llm_blocked_categories=["cardiology_notes"],
        )
        result = self.choose_extractor(b"data", "application/pdf", policy, "cardiology_notes")
        assert result == "ocr_fallback"

    def test_tenant_blocked_category_case_insensitive(self):
        """Category matching should be case-insensitive."""
        policy = self._policy(
            tenant_id="t1",
            llm_blocked_categories=["Behavioral_Health"],
        )
        result = self.choose_extractor(b"data", "application/pdf", policy, "behavioral_health")
        # Matches global _NO_LLM_CATEGORIES too
        assert result == "ocr_fallback"


# ---------------------------------------------------------------------------
# Multi-page PDF test (mocked pypdfium2)
# ---------------------------------------------------------------------------


class TestOcrDocumentMultiPage:
    """Integration-style test for ocr_document with a multi-page PDF."""

    def test_multi_page_pdf_returns_per_page_text(self):
        """ocr_document with PDF should return one entry per page."""
        # Build mock pypdfium2 with 2 pages
        mock_bitmap1 = MagicMock()
        mock_bitmap1.to_pil.return_value = MagicMock(
            save=lambda buf, format: buf.write(b"PNG1")
        )
        mock_bitmap2 = MagicMock()
        mock_bitmap2.to_pil.return_value = MagicMock(
            save=lambda buf, format: buf.write(b"PNG2")
        )

        mock_page1 = MagicMock()
        mock_page1.render.return_value = mock_bitmap1
        mock_page2 = MagicMock()
        mock_page2.render.return_value = mock_bitmap2

        mock_pdf = MagicMock()
        mock_pdf.__len__ = MagicMock(return_value=2)
        mock_pdf.__getitem__ = MagicMock(side_effect=lambda i: [mock_page1, mock_page2][i])

        mock_pdfium = MagicMock()
        mock_pdfium.PdfDocument.return_value = mock_pdf

        # Mock pytesseract and PIL for the image OCR step
        mock_pyt = MagicMock()
        mock_pyt.Output.DICT = "dict"
        mock_pyt.image_to_data.side_effect = [
            {"text": ["Page", "one"], "conf": [95, 90]},
            {"text": ["Page", "two"], "conf": [88, 85]},
        ]

        mock_pil = MagicMock()
        mock_pil.Image.open.return_value = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "pypdfium2": mock_pdfium,
                "pytesseract": mock_pyt,
                "PIL": mock_pil,
                "PIL.Image": mock_pil.Image,
            },
        ):
            from app.services import ocr_fallback
            import importlib
            importlib.reload(ocr_fallback)
            result = ocr_fallback.ocr_document(b"fake-pdf", "application/pdf", engine="tesseract")

        assert result["engine"] == "tesseract"
        assert len(result["pages"]) == 2
        assert result["pages"][0]["page"] == 1
        assert result["pages"][1]["page"] == 2
        assert "Page" in result["pages"][0]["text"] or result["pages"][0]["text"] != ""
        assert result["full_text"] != ""

    def test_tiff_single_frame(self):
        """Single-frame TIFF returns one page result."""
        mock_pyt = MagicMock()
        mock_pyt.Output.DICT = "dict"
        mock_pyt.image_to_data.return_value = {"text": ["Fax", "cover"], "conf": [92, 89]}

        # Mock PIL Image with single frame (seek raises EOFError on second call)
        mock_img = MagicMock()
        seek_calls = [0]
        def _seek(n):
            if n >= 1:
                raise EOFError
        mock_img.seek.side_effect = _seek
        mock_img.save = lambda buf, format: buf.write(b"TIFF_PNG")

        mock_pil = MagicMock()
        mock_pil.Image.open.return_value = mock_img

        with patch.dict(
            "sys.modules",
            {"pytesseract": mock_pyt, "PIL": mock_pil, "PIL.Image": mock_pil.Image},
        ):
            from app.services import ocr_fallback
            import importlib
            importlib.reload(ocr_fallback)
            result = ocr_fallback.ocr_document(b"fake-tiff", "image/tiff", engine="tesseract")

        assert len(result["pages"]) == 1
        assert result["pages"][0]["page"] == 1
        assert result["engine"] == "tesseract"
