"""Explainable media relevance; embedding scores are never probabilities or OCR evidence."""

import re
from collections import defaultdict

from .models import SearchHit
from .retrieval import contains, normalized, terms

DEFAULT_MEDIA_MINIMUM = 0.55
SEMANTIC_SCORE_WINDOW = 0.08
IMAGE_QUERY_NOISE = {
    "image",
    "images",
    "picture",
    "pictures",
    "photo",
    "photos",
    "show",
    "me",
    "图片",
    "照片",
}


def _phrase(text: str) -> str:
    # Ignore OCR line breaks/punctuation while preserving English word boundaries.
    return " ".join(re.findall(r"[a-z0-9]+|[\u3400-\u9fff]", normalized(text)))


def select_media_hits(
    question: str,
    hits: list[SearchHit],
    minimum: float,
    mode: str,
    text_only: bool,
) -> tuple[list[SearchHit], str, int]:
    ordered = sorted(hits, key=lambda h: (-h.score, h.document_id, h.index))
    image_rows: dict[str, list[SearchHit]] = defaultdict(list)
    candidates, seen = [], set()
    for hit in ordered:
        if hit.kind == "image":
            image_rows[hit.document_id].append(hit)
            if hit.document_id in seen:
                continue
            seen.add(hit.document_id)
        candidates.append(hit)
    count = len(candidates)
    # OCR is combined before deduplication: the highest vector chunk may not contain the title.
    ocr = {
        document: "\n".join(dict.fromkeys(row.text for row in rows if row.ocr_status == "ready"))
        for document, rows in image_rows.items()
    }
    only_images = bool(candidates) and all(hit.kind == "image" for hit in candidates)
    if text_only and (only_images or mode == "image_text") and mode != "broad":
        phrase = _phrase(question)
        exact = {
            document
            for document, content in ocr.items()
            if phrase and f" {phrase} " in f" {_phrase(content)} "
        }
        words = [word for word in terms(question) if word not in IMAGE_QUERY_NOISE]
        total = sum(2 if len(word) >= 4 else 1 for word in words) or 1
        coverage = {
            document: sum(
                2 if len(word) >= 4 else 1 for word in words if contains(normalized(content), word)
            )
            / total
            for document, content in ocr.items()
        }
        complete = {document for document, value in coverage.items() if value >= 0.8}
        matches = exact or complete
        if matches or mode == "image_text":
            # Literal OCR evidence need not have high cross-modal cosine similarity.
            selected = [hit for hit in candidates if hit.document_id in matches]
            selected = [
                max(
                    (row for row in image_rows[hit.document_id] if row.ocr_status == "ready"),
                    key=lambda row: (
                        bool(phrase and f" {phrase} " in f" {_phrase(row.text)} "),
                        sum(1 for word in words if contains(normalized(row.text), word)),
                        row.score,
                    ),
                )
                for hit in selected
            ]
            selected.sort(key=lambda h: (-coverage.get(h.document_id, 0), -h.score, h.document_id))
            return selected, "image_text", count
    selected = [hit for hit in candidates if hit.score >= minimum]
    if mode != "broad" and selected:
        floor = selected[0].score - SEMANTIC_SCORE_WINDOW
        selected = [hit for hit in selected if hit.score >= floor]
    return selected, "broad" if mode == "broad" else "semantic", count
