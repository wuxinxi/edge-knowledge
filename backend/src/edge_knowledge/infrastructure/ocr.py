import importlib.util
import sys

from edge_knowledge.domain.models import OCRResult, TextRegion


class AppleVisionOCR:
    """On-device macOS Vision OCR; no remote fallback or synthetic text."""

    @property
    def available(self) -> bool:
        return sys.platform == "darwin" and importlib.util.find_spec("Vision") is not None

    def recognize(self, content: bytes) -> OCRResult:
        if not self.available:
            return OCRResult(
                "unavailable", message="本地 OCR 未安装或当前系统不支持。图片仍可检索。"
            )
        try:
            import Foundation
            import objc
            import Vision

            with objc.autorelease_pool():
                request = Vision.VNRecognizeTextRequest.alloc().init()
                request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
                request.setRecognitionLanguages_(["zh-Hans", "en-US"])
                request.setUsesLanguageCorrection_(True)
                data = Foundation.NSData.dataWithBytes_length_(content, len(content))
                handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(
                    data, Foundation.NSDictionary.dictionary()
                )
                success, _error = handler.performRequests_error_([request], None)
                if not success:
                    return OCRResult("error", message="本地 OCR 未能读取文字。图片仍可检索。")
                regions = []
                for observation in request.results() or []:
                    candidates = observation.topCandidates_(1)
                    if not candidates:
                        continue
                    candidate = candidates[0]
                    box = observation.boundingBox()
                    regions.append(
                        TextRegion(
                            str(candidate.string()),
                            float(candidate.confidence()),
                            (
                                float(box.origin.x),
                                float(1 - box.origin.y - box.size.height),
                                float(box.size.width),
                                float(box.size.height),
                            ),
                        )
                    )
                text = "\n".join(region.text for region in regions)
                return OCRResult("ready" if text.strip() else "empty", text, regions)
        except Exception:
            return OCRResult("error", message="本地 OCR 处理失败。图片仍可检索，可尝试云端看图。")
