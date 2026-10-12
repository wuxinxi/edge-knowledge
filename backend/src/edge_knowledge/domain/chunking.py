import re

from .models import AppError, Chunk


def split_document(text: str, chunk_size: int, overlap: int) -> list[Chunk]:
    if chunk_size < 100 or not 0 <= overlap < chunk_size:
        raise AppError("切片长度至少为 100，重叠长度必须小于切片长度。")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise AppError("文档没有可提取的文字。扫描 PDF 请先进行 OCR。")
    sections: list[tuple[str, str]] = []
    title, lines = "", []
    for line in text.splitlines():
        if re.match(r"^#{1,6}\s+", line):
            if lines:
                sections.append((title, "\n".join(lines)))
            title, lines = re.sub(r"^#{1,6}\s+", "", line).strip(), [line]
        else:
            lines.append(line)
    if lines:
        sections.append((title, "\n".join(lines)))
    chunks: list[Chunk] = []
    for title, section in sections:
        start = 0
        while start < len(section):
            end = min(start + chunk_size, len(section))
            # Prefer a nearby paragraph/line ending, while guaranteeing forward progress.
            if end < len(section):
                boundary = section.rfind("\n", start + chunk_size // 2, end)
                if boundary > start + overlap:
                    end = boundary + 1
            piece = section[start:end].strip()
            if piece:
                chunks.append(Chunk(piece, len(chunks), title))
            if end == len(section):
                break
            start = end - overlap
    return chunks
