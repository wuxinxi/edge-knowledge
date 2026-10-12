import warnings
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from edge_knowledge.domain.models import AppError, Asset, PreparedImage


class PillowImageProcessor:
    def _open(self, content: bytes) -> Image.Image:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as source:
                    if source.format not in {"PNG", "JPEG", "WEBP"}:
                        raise AppError("仅支持 PNG、JPEG 和 WebP 图片。", 415, "unsupported_image")
                    if getattr(source, "n_frames", 1) != 1:
                        raise AppError("暂不支持动画图片，请导入单张静态图片。", 415)
                    if max(source.size) > 8192 or source.width * source.height > 24_000_000:
                        raise AppError("图片过大：单边不能超过 8192 像素，总像素不能超过 2400 万。")
                    oriented = ImageOps.exif_transpose(source)
                    if "A" in oriented.getbands() or "transparency" in oriented.info:
                        rgba = oriented.convert("RGBA")
                        image = Image.new("RGB", rgba.size, "white")
                        image.paste(rgba, mask=rgba.getchannel("A"))
                    else:
                        image = oriented.convert("RGB")
                    image.load()
                    image.info.clear()
                    return image
        except AppError:
            raise
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise AppError("图片无法读取，请确认格式正确且文件未损坏。") from exc

    def prepare(self, content: bytes) -> PreparedImage:
        image = self._open(content)
        full, preview = BytesIO(), BytesIO()
        image.save(full, format="PNG")
        if full.tell() > 32 * 1024 * 1024:
            raise AppError("图片解码后体积过大，请缩小图片后再导入。", 413)
        thumb = image.copy()
        thumb.thumbnail((480, 480))
        thumb.save(preview, format="PNG")
        return PreparedImage(full.getvalue(), preview.getvalue(), image.width, image.height)

    def for_generation(self, content: bytes) -> Asset:
        image = self._open(content)
        image.thumbnail((2048, 2048))
        output = BytesIO()
        image.save(output, format="JPEG", quality=90)
        if output.tell() > 8 * 1024 * 1024:
            raise AppError("图片无法压缩到生成服务的请求预算内。", 413)
        return Asset(output.getvalue(), "image/jpeg")
