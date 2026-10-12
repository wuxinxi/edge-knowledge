"""Decode local bytes only. Stream bounded audio/video windows, never open media URLs."""

import math
from io import BytesIO

import av
import numpy as np
from PIL import Image

from edge_knowledge.domain.models import AppError
from edge_knowledge.domain.multimodal import EmbeddingInput, InputAsset, MediaInfo

AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
MAX_MEDIA_BYTES = 200 * 1024 * 1024
WINDOW = 24.0  # joint video+soundtrack stays comfortably inside the shared context


class AVMediaDecoder:
    def probe(self, asset: InputAsset) -> MediaInfo:
        try:
            with av.open(
                BytesIO(asset.content), options={"protocol_whitelist": "pipe"}
            ) as container:
                video = next(iter(container.streams.video), None)
                audio = next(iter(container.streams.audio), None)
                if video and video.codec_context.width * video.codec_context.height > 40_000_000:
                    raise AppError("视频画面超过 4000 万像素，请缩小后导入。", 413)
                if asset.kind == "video" and not video or asset.kind == "audio" and not audio:
                    raise AppError("文件内没有相应媒体轨道。", 415)
                origin = float(container.start_time or 0) / av.time_base
                selected = (
                    [audio] if asset.kind == "audio" else [video, *([audio] if audio else [])]
                )
                duration = 0.0
                # Packet presentation timestamps survive VFR/B-frame header duration errors.
                # Scan compressed packets without decoding full video frames.
                for packet in container.demux(selected):
                    if packet.pts is None or packet.time_base is None:
                        continue
                    length = float((packet.duration or 0) * packet.time_base)
                    if packet.stream.type == "video" and length <= 0:
                        length = 1 / float(packet.stream.average_rate or 30)
                    duration = max(duration, float(packet.pts * packet.time_base) - origin + length)
                    if duration > 3600:
                        raise AppError("媒体超过 60 分钟，请拆分后导入。", 413)
                if duration <= 0:
                    duration = float(container.duration or 0) / av.time_base
                    stream = video or audio
                    if not duration:
                        duration = float((stream.duration or 0) * stream.time_base)
                if not math.isfinite(duration) or not 0 < duration <= 3600:
                    raise AppError("无法读取媒体时长，或超过 60 分钟；请拆分后导入。", 413)
                return MediaInfo(asset.kind, duration, asset.media_type, bool(audio))
        except AppError:
            raise
        except Exception as exc:
            raise AppError("媒体无法解码，请检查格式和文件完整性。", 415, "media_invalid") from exc

    def _audio(self, asset: InputAsset, start: float, end: float) -> bytes:
        pieces = []
        with av.open(BytesIO(asset.content), options={"protocol_whitelist": "pipe"}) as container:
            if not container.streams.audio:
                return b""
            stream = container.streams.audio[0]
            origin = float(container.start_time or 0) / av.time_base
            container.seek(int((start + origin) * av.time_base))
            resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
            done = False
            for frame in container.decode(stream):
                for sample in resampler.resample(frame):
                    time = (
                        float(sample.pts * sample.time_base) - origin
                        if sample.pts is not None
                        else start
                    )
                    values = sample.to_ndarray().reshape(-1)
                    left = max(0, round((start - time) * 16000))
                    right = min(len(values), round((end - time) * 16000))
                    if right > left:
                        pieces.append(values[left:right])
                    if time + len(values) / 16000 >= end:
                        done = True
                if done:
                    break
            if not done:
                for sample in resampler.resample(None):
                    time = (
                        float(sample.pts * sample.time_base) - origin
                        if sample.pts is not None
                        else start
                    )
                    values = sample.to_ndarray().reshape(-1)
                    left, right = (
                        max(0, round((start - time) * 16000)),
                        min(len(values), round((end - time) * 16000)),
                    )
                    if right > left:
                        pieces.append(values[left:right])
        return np.concatenate(pieces).astype("<f4").tobytes() if pieces else b""

    def _frames(self, asset: InputAsset, start: float, end: float) -> tuple[bytes, ...]:
        frames, next_time = [], start
        with av.open(BytesIO(asset.content), options={"protocol_whitelist": "pipe"}) as container:
            stream = container.streams.video[0]
            origin = float(container.start_time or 0) / av.time_base
            container.seek(int((start + origin) * av.time_base))
            for frame in container.decode(stream):
                if frame.time is None or not math.isfinite(float(frame.time)):
                    raise AppError("视频缺少有效时间戳，请转码后导入。", 415)
                time = float(frame.time) - origin
                if time >= end:
                    break
                if time + 0.001 < next_time:
                    continue
                image = frame.to_image().convert("RGB")
                image.thumbnail((640, 640))
                # Fixed dimensions permit a single video tensor across changing source resolutions.
                canvas = Image.new("RGB", (640, 640), "black")
                canvas.paste(image, ((640 - image.width) // 2, (640 - image.height) // 2))
                output = BytesIO()
                canvas.save(output, "JPEG", quality=85)
                frames.append(output.getvalue())
                next_time = start + math.floor(time - start) + 1
                if len(frames) >= 24:
                    break
        return tuple(frames)

    def segments(self, asset: InputAsset):
        info = self.probe(asset)
        try:
            for start in np.arange(0, info.duration, WINDOW):
                end = min(float(start) + WINDOW, info.duration)
                frames = self._frames(asset, float(start), end) if info.kind == "video" else ()
                audio = self._audio(asset, float(start), end) if info.has_audio else b""
                if not frames and not audio:
                    raise AppError("媒体片段无法解码，已停止导入。", 415)
                yield EmbeddingInput(audio=audio, frames=frames, start=float(start), end=end)
        except AppError:
            raise
        except Exception as exc:
            raise AppError("媒体分段解码失败，已停止导入。", 415, "media_decode_failed") from exc
