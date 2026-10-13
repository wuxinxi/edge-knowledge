import importlib.util
import math
import sys
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from threading import RLock

from edge_knowledge.domain.models import OCRResult, TextRegion


class AppleVisionOCR:
    """On-device macOS Vision OCR; no remote fallback or synthetic text."""

    engine_name = "macOS Vision"

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
                return OCRResult(
                    "ready" if text.strip() else "empty", text, regions, engine=self.engine_name
                )
        except Exception:
            return OCRResult("error", message="本地 OCR 处理失败。图片仍可检索，可尝试云端看图。")


class RapidLocalOCR:
    """CPU-only OCR with models bundled in the pinned wheel; byte inputs only."""

    engine_name = "RapidOCR · ONNX Runtime"
    model_files = {
        "det": "ch_PP-OCRv4_det_infer.onnx",
        "cls": "ch_ppocr_mobile_v2.0_cls_infer.onnx",
        "rec": "ch_PP-OCRv4_rec_infer.onnx",
    }

    def __init__(self):
        self._engine = None
        self._lock = RLock()
        self._failed = False

    @staticmethod
    def _root() -> Path | None:
        spec = importlib.util.find_spec("rapidocr_onnxruntime")
        return Path(spec.origin).parent if spec and spec.origin else None

    @property
    def available(self) -> bool:
        try:
            root = self._root()
            return bool(
                not self._failed
                and root
                and all(
                    importlib.util.find_spec(name)
                    for name in ("onnxruntime", "cv2", "pyclipper", "shapely", "yaml")
                )
                and (root / "config.yaml").is_file()
                and all((root / "models" / name).is_file() for name in self.model_files.values())
            )
        except (ImportError, ValueError, OSError):
            return False

    def recognize(self, content: bytes) -> OCRResult:
        if not self.available:
            return OCRResult(
                "unavailable",
                message="跨平台本地 OCR 依赖或模型未准备，请安装 ocr 依赖。图片语义检索仍可使用。",
                engine=self.engine_name,
            )
        with self._lock:
            try:
                from PIL import Image
                from rapidocr_onnxruntime import RapidOCR

                if self._engine is None:
                    root = self._root()
                    self._engine = RapidOCR(
                        config_path=str(root / "config.yaml"),
                        **{
                            f"{kind}_model_path": str(root / "models" / name)
                            for kind, name in self.model_files.items()
                        },
                        intra_op_num_threads=2,
                        inter_op_num_threads=1,
                        det_use_cuda=False,
                        cls_use_cuda=False,
                        rec_use_cuda=False,
                        det_use_dml=False,
                        cls_use_dml=False,
                        rec_use_dml=False,
                        print_verbose=False,
                    )
                with Image.open(BytesIO(content)) as image:
                    width, height = image.size
                rows, _timings = self._engine(content)
                regions = []
                for box, text, confidence in rows or []:
                    if not str(text).strip():
                        continue
                    confidence = float(confidence)
                    points = [(float(point[0]), float(point[1])) for point in box]
                    if (
                        not math.isfinite(confidence)
                        or not points
                        or not all(math.isfinite(v) for point in points for v in point)
                    ):
                        raise ValueError("Invalid OCR region")
                    x1 = max(0.0, min(width, min(x for x, _ in points)))
                    y1 = max(0.0, min(height, min(y for _, y in points)))
                    x2 = max(x1, min(width, max(x for x, _ in points)))
                    y2 = max(y1, min(height, max(y for _, y in points)))
                    regions.append(
                        TextRegion(
                            str(text),
                            max(0.0, min(1.0, confidence)),
                            (x1 / width, y1 / height, (x2 - x1) / width, (y2 - y1) / height),
                        )
                    )
                text = "\n".join(region.text for region in regions)
                return OCRResult(
                    "ready" if text.strip() else "empty", text, regions, engine=self.engine_name
                )
            except Exception:
                if self._engine is None:
                    self._failed = True
                return OCRResult(
                    "error",
                    message="跨平台本地 OCR 处理失败，请检查依赖与图片内容。图片未发送到云端。",
                    engine=self.engine_name,
                )


class LocalOCR:
    """Prefer native macOS recognition; use bundled local OCR on other platforms/failures."""

    def __init__(self):
        self._native = AppleVisionOCR()
        self._portable = RapidLocalOCR()

    @property
    def available(self) -> bool:
        return self._native.available or self._portable.available

    @property
    def engine_name(self) -> str:
        if self._native.available:
            return self._native.engine_name
        return self._portable.engine_name if self._portable.available else ""

    def recognize(self, content: bytes) -> OCRResult:
        if self._native.available:
            result = self._native.recognize(content)
            if result.status not in {"error", "unavailable"}:
                return replace(result, engine=self._native.engine_name)
            if not self._portable.available:
                return replace(result, engine=self._native.engine_name)
        return self._portable.recognize(content)
