import socket
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from edge_knowledge.domain.models import OCRResult
from edge_knowledge.infrastructure.ocr import AppleVisionOCR, LocalOCR, RapidLocalOCR


def fixture_image():
    image = Image.new("RGB", (900, 180), "white")
    ImageDraw.Draw(image).text(
        (30, 50), "PACKAGE CODE 6583", fill="black", font=ImageFont.load_default(size=60)
    )
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


@pytest.mark.skipif(not RapidLocalOCR().available, reason="portable OCR dependencies optional")
def test_real_portable_ocr_runs_without_network_and_returns_normalized_boxes(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("OCR must never connect to the network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    engine = RapidLocalOCR()
    result = engine.recognize(fixture_image())
    assert result.status == "ready" and "6583" in result.text
    assert result.engine == engine.engine_name and result.regions
    for region in result.regions:
        assert 0 <= region.confidence <= 1 and all(0 <= value <= 1 for value in region.bbox)
        assert region.bbox[0] + region.bbox[2] <= 1 and region.bbox[1] + region.bbox[3] <= 1
    assert engine.recognize(fixture_image()).text == result.text
    chinese = engine.recognize(
        (Path(__file__).parent / "fixtures/ocr-chinese-demo.png").read_bytes()
    )
    assert (
        chinese.status == "ready" and "本地图片文字识别" in chinese.text and "6583" in chinese.text
    )


def test_non_macos_chooses_portable_engine(monkeypatch):
    monkeypatch.setattr("edge_knowledge.infrastructure.ocr.sys.platform", "win32")
    monkeypatch.setattr(RapidLocalOCR, "available", property(lambda self: True))
    monkeypatch.setattr(
        RapidLocalOCR,
        "recognize",
        lambda self, data: OCRResult("ready", "local text", engine=self.engine_name),
    )
    engine = LocalOCR()
    assert not AppleVisionOCR().available and engine.available
    assert engine.engine_name == "RapidOCR · ONNX Runtime"
    assert engine.recognize(b"local").text == "local text"


@pytest.mark.parametrize("status", ["error", "unavailable"])
def test_native_failure_uses_only_local_fallback(monkeypatch, status):
    monkeypatch.setattr(AppleVisionOCR, "available", property(lambda self: True))
    monkeypatch.setattr(RapidLocalOCR, "available", property(lambda self: True))
    monkeypatch.setattr(AppleVisionOCR, "recognize", lambda self, data: OCRResult(status))
    monkeypatch.setattr(
        RapidLocalOCR,
        "recognize",
        lambda self, data: OCRResult("ready", "portable", engine=self.engine_name),
    )
    result = LocalOCR().recognize(b"image")
    assert result.text == "portable" and result.engine == "RapidOCR · ONNX Runtime"


@pytest.mark.parametrize("status", ["ready", "empty"])
def test_native_success_or_empty_does_not_run_fallback(monkeypatch, status):
    monkeypatch.setattr(AppleVisionOCR, "available", property(lambda self: True))
    monkeypatch.setattr(
        AppleVisionOCR,
        "recognize",
        lambda self, data: OCRResult(status, "text" if status == "ready" else ""),
    )
    monkeypatch.setattr(
        RapidLocalOCR, "recognize", lambda *args: pytest.fail("unnecessary fallback")
    )
    result = LocalOCR().recognize(b"image")
    assert result.status == status and result.engine == "macOS Vision"


def test_missing_local_models_reports_unavailable_and_never_initializes(monkeypatch, tmp_path):
    monkeypatch.setattr(RapidLocalOCR, "_root", staticmethod(lambda: tmp_path))
    engine = RapidLocalOCR()
    assert not engine.available
    result = engine.recognize(b"anything")
    assert result.status == "unavailable" and engine._engine is None


@pytest.mark.skipif(not RapidLocalOCR().available, reason="portable OCR dependencies optional")
def test_blank_invalid_images_and_failed_initialization_do_not_fake_text(monkeypatch):
    output = BytesIO()
    Image.new("RGB", (200, 100), "white").save(output, "PNG")
    engine = RapidLocalOCR()
    assert engine.recognize(output.getvalue()).status == "empty"
    result = engine.recognize(b"not an image")
    assert result.status == "error" and not result.text
    assert engine.available
    import rapidocr_onnxruntime

    def fail(**kwargs):
        raise RuntimeError("runtime unavailable")

    monkeypatch.setattr(rapidocr_onnxruntime, "RapidOCR", fail)
    broken = RapidLocalOCR()
    assert broken.recognize(fixture_image()).status == "error"
    assert not broken.available
