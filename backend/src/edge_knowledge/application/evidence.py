"""Expand retrieved document evidence within a bounded, provider-independent scope."""

from collections.abc import Callable
from dataclasses import replace

from edge_knowledge.domain.models import AppError, SearchHit

# This bounds automatic parent expansion, not the model's token context. The
# runtime still validates the rendered prompt against its actual tokenizer.
MAX_PARENT_CHARACTERS = 6000
MAX_EVIDENCE_CHARACTERS = 12000


class AnswerEvidence:
    def __init__(self, read: Callable[[str, str], SearchHit]):
        self.read = read

    def expand(self, library: str, hits: list[SearchHit]) -> list[SearchHit]:
        groups: dict[str, list[SearchHit]] = {}
        for hit in hits:
            groups.setdefault(hit.document_id, []).append(hit)
        # Reserve all original matches first. Extra context may never crowd out
        # another relevant result merely because an earlier document is longer.
        used = sum(
            len(hit.text) if hit.content_scope == "full_document" else len(hit.text[:4000])
            for hit in hits
        )
        parents: dict[str, SearchHit] = {}
        for id, matches in groups.items():
            first = matches[0]
            if first.kind != "document" or any(
                hit.content_scope == "full_document" for hit in matches
            ):
                continue
            try:
                parent = self.read(library, id)
            except AppError as exc:
                if exc.code != "original_missing":
                    raise
                # Legacy notes may only have chunks. Keep those as excerpts;
                # never reconstruct an allegedly complete overlapping original.
                continue
            replaced = sum(len(hit.text[:4000]) for hit in matches)
            proposed = used - replaced + len(parent.text)
            if (
                parent.text.strip()
                and len(parent.text) <= MAX_PARENT_CHARACTERS
                and proposed <= MAX_EVIDENCE_CHARACTERS
            ):
                parents[id] = replace(parent, score=first.score)
                used = proposed
        result, emitted = [], set()
        for hit in hits:
            if hit.document_id not in parents:
                result.append(hit)
            elif hit.document_id not in emitted:
                result.append(parents[hit.document_id])
                emitted.add(hit.document_id)
        return result
