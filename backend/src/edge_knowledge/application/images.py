from edge_knowledge.domain.models import AppError, ImageAttachment, OCRResult, PreparedImage

from .ports import OCR, AssetStore, ImageProcessor

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class ImageService:
    """Local image preparation, OCR, and evidence storage through independent ports."""

    def __init__(self, processor: ImageProcessor, ocr: OCR, assets: AssetStore):
        self.processor, self.ocr, self.assets = processor, ocr, assets

    def prepare(self, content: bytes) -> tuple[PreparedImage, OCRResult]:
        if len(content) > 20 * 1024 * 1024:
            raise AppError("单张图片不能超过 20 MB。", 413, "file_too_large")
        image = self.processor.prepare(content)
        return image, self.ocr.recognize(image.data)

    def attachment(self, library_id: str, document_id: str, filename: str) -> ImageAttachment:
        stored = self.assets.get(library_id, document_id)
        resized = self.processor.for_generation(stored.data)
        return ImageAttachment(document_id, filename, resized.data, resized.media_type)
