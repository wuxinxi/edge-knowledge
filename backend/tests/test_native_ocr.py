from io import BytesIO

import pytest
from PIL import Image, ImageDraw, ImageFont

from edge_knowledge.infrastructure.ocr import AppleVisionOCR


@pytest.mark.skipif(not AppleVisionOCR().available, reason="macOS Vision OCR is optional")
def test_real_on_device_ocr_preserves_text_and_normalized_regions():
    image = Image.new("RGB", (900, 180), "white")
    ImageDraw.Draw(image).text(
        (30, 50), "PACKAGE CODE 6583", fill="black", font=ImageFont.load_default(size=60)
    )
    output = BytesIO()
    image.save(output, "PNG")
    result = AppleVisionOCR().recognize(output.getvalue())
    assert result.status == "ready"
    assert "6583" in result.text and result.regions
    for region in result.regions:
        assert 0 <= region.confidence <= 1
        assert all(0 <= coordinate <= 1 for coordinate in region.bbox)
