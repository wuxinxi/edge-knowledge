"""Blockwise cosine comparison: count all matching pairs, retain only a bounded page."""

import hashlib
import heapq
import re

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

from edge_knowledge.domain.models import AppError


class NumpySimilarityMatcher:
    def match(self, vectors, fingerprints, threshold, limit, offset, texts=None):
        if not vectors:
            return {"total": 0, "candidate_documents": 0, "pairs": []}
        try:
            matrix = np.asarray(vectors, dtype=np.float32)
            norms = np.linalg.norm(matrix, axis=1)
            if (
                matrix.ndim != 2
                or len(fingerprints) != len(matrix)
                or not np.isfinite(matrix).all()
                or (norms < 1e-12).any()
            ):
                raise ValueError
            matrix = matrix / norms[:, None]
        except (ValueError, TypeError, np.exceptions.AxisError) as exc:
            raise AppError(
                "资料向量不完整或维度不一致，请检查索引。", 409, "invalid_similarity_vectors"
            ) from exc
        features = body_fingerprints = feature_counts = None
        if texts is not None:
            bodies = [
                re.sub(
                    r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|$)", "", text, count=1, flags=re.S
                )
                for text in texts
            ]
            if len(bodies) != len(matrix):
                raise AppError("正文对比范围不完整。", 409, "invalid_similarity_vectors")
            body_fingerprints = np.asarray(
                [
                    hashlib.sha256(body.replace("\r\n", "\n").encode()).hexdigest()
                    if body.strip()
                    else ""
                    for body in bodies
                ]
            )
            features = HashingVectorizer(
                n_features=65536,
                analyzer="char",
                ngram_range=(3, 5),
                binary=True,
                alternate_sign=False,
                norm=None,
            ).transform(bodies)
            feature_counts = features.getnnz(axis=1)
        fingerprints = np.asarray(fingerprints)
        retained, total = [], 0
        matched = np.zeros(len(matrix), dtype=bool)
        take = limit + offset
        columns = np.arange(len(matrix))[None, :]
        for start in range(0, len(matrix), 128):
            end = min(start + 128, len(matrix))
            scores = np.clip(matrix[start:end] @ matrix.T, -1, 1)
            identical = fingerprints[start:end, None] == fingerprints[None, :]
            scores[identical] = 1.0
            body_same = np.zeros_like(identical)
            overlap = None
            if features is not None:
                intersection = (features[start:end] @ features.T).toarray()
                denominator = feature_counts[start:end, None] + feature_counts[None, :]
                overlap = np.divide(
                    2 * intersection,
                    denominator,
                    out=np.zeros_like(intersection),
                    where=denominator != 0,
                )
                body_same = (body_fingerprints[start:end, None] == body_fingerprints[None, :]) & (
                    body_fingerprints[start:end, None] != ""
                )
                evidence = identical | body_same | ((scores >= threshold) & (overlap >= 0.6))
            else:
                evidence = scores >= threshold
            eligible = (columns > np.arange(start, end)[:, None]) & evidence
            left, right = np.nonzero(eligible)
            left += start
            total += len(left)
            matched[left] = True
            matched[right] = True
            values = scores[left - start, right]
            # Native sorting keeps even dense result sets out of Python's quadratic storage.
            strength = 2 * identical[left - start, right].astype(int) + body_same[
                left - start, right
            ].astype(int)
            best = np.lexsort((right, left, -values, -strength))[:take]
            for position in best:
                left_index, right_index, score = (
                    int(left[position]),
                    int(right[position]),
                    float(values[position]),
                )
                entry = (
                    int(strength[position]),
                    score,
                    -left_index,
                    -right_index,
                    bool(fingerprints[left_index] == fingerprints[right_index]),
                    bool(body_same[left_index - start, right_index]),
                    float(overlap[left_index - start, right_index])
                    if overlap is not None
                    else -1.0,
                )
                if len(retained) < take:
                    heapq.heappush(retained, entry)
                elif entry > retained[0]:
                    heapq.heapreplace(retained, entry)
        pairs = [
            {
                "left": -left_index,
                "right": -right_index,
                "score": round(score, 4),
                "exact": exact,
                **(
                    {"body_exact": body_exact, "content_similarity": round(content_similarity, 4)}
                    if texts is not None
                    else {}
                ),
            }
            for _, score, left_index, right_index, exact, body_exact, content_similarity in sorted(
                retained, reverse=True
            )[offset : offset + limit]
        ]
        return {"total": total, "candidate_documents": int(matched.sum()), "pairs": pairs}
