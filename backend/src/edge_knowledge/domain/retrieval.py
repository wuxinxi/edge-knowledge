"""Local text relevance policy; cosine similarity remains a score, not a probability."""

import math
import re
import unicodedata
from collections import Counter

from .models import SearchHit

NOISE = {
    "what",
    "where",
    "which",
    "please",
    "find",
    "tell",
    "the",
    "is",
    "are",
    "of",
    "and",
    "solution",
    "solutions",
    "method",
    "methods",
    "approach",
    "approaches",
    "option",
    "options",
    "怎么",
    "什么",
    "如何",
    "多少",
    "哪里",
    "是否",
    "请问",
    "帮我",
    "查找",
    "查询",
    "一下",
    "关于",
    "有关",
    "相关",
    "可以",
    "资料",
    "方案",
    "方法",
    "方式",
    "问题",
    "的是",
    "是什么",
}


def normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def retrieval_text(question: str) -> str:
    text = question
    if re.search(r"地址|用户名|密码|服务器|文件传输", text):
        text = re.sub(r"\bfpt\b", "FTP", text, flags=re.IGNORECASE)
    return text


def terms(question: str) -> list[str]:
    text = normalized(retrieval_text(question))
    for phrase in (
        "帮我查询出",
        "帮我查一下",
        "请帮我",
        "帮我",
        "查询",
        "查找",
        "请问",
        "是多少",
        "是什么",
        "在哪里",
        "怎样",
        "有哪些",
        "有哪几种",
        "有什么",
        "如何",
        "怎么",
    ):
        text = text.replace(phrase, " ")
    text = re.sub(r"[的和是与吗呢]", " ", text)
    words = re.findall(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", text)
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        # Overlapping Chinese terms need no language-specific package or cloud tokenizer.
        for size in (2, 4):
            words.extend(run[i : i + size] for i in range(len(run) - size + 1))
    return list(dict.fromkeys(w for w in words if len(w) > 1 and w not in NOISE))[:64]


def anchors(question: str) -> list[str]:
    text = normalized(question)
    quoted = re.findall(r'["“「](.{2,80}?)["”」]', text)
    identifiers = [
        w
        for w in re.findall(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", text)
        if len(w) >= 3 and (any(c.isdigit() for c in w) or "-" in w or "_" in w)
    ]
    return list(dict.fromkeys(quoted + identifiers))[:10]


def contains(text: str, term: str) -> bool:
    if re.fullmatch(r"[a-z0-9._/-]+", term):
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text))
    return term in text


def rank_hits(question: str, hits: list[SearchHit], limit: int, minimum: float) -> list[SearchHit]:
    unique = {(h.document_id, h.index): h for h in hits if h.score >= minimum}
    hits = list(unique.values())
    if not hits:
        return []
    text = {
        (h.document_id, h.index): normalized(h.text + "\n" + h.section + "\n" + h.filename)
        for h in hits
    }
    required = anchors(question)
    if required:
        hits = [h for h in hits if all(contains(text[h.document_id, h.index], a) for a in required)]
        if not hits:
            return []
    words = terms(question)
    frequency = Counter(w for h in hits for w in words if contains(text[h.document_id, h.index], w))
    weights = {
        w: math.log(1 + (len(hits) + 1) / (frequency[w] + 1)) * (2 if len(w) >= 4 else 1)
        for w in words
    }
    total = sum(weights[w] for w in words if frequency[w]) or 1
    coverage = {
        (h.document_id, h.index): sum(
            weights[w] for w in words if contains(text[h.document_id, h.index], w)
        )
        / total
        for h in hits
    }
    hits.sort(
        key=lambda h: (
            -(0.7 * h.score + 0.3 * coverage[h.document_id, h.index]),
            -h.score,
            h.document_id,
            h.index,
        )
    )
    best = coverage[hits[0].document_id, hits[0].index]
    rare = [
        w
        for w in words
        if len(w) >= 4 and frequency[w] == 1 and re.fullmatch(r"[\u3400-\u9fff]+", w)
    ]
    if rare and any(contains(text[hits[0].document_id, hits[0].index], w) for w in rare):
        hits = [h for h in hits if any(contains(text[h.document_id, h.index], w) for w in rare)]
    # Only prune by lexical evidence when the leading passage actually covers the question.
    if best >= 0.5:
        hits = [h for h in hits if coverage[h.document_id, h.index] >= best * 0.45]
    selected, seen_text, per_document = [], set(), Counter()
    for h in hits:
        key = (h.document_id if h.kind != "document" else "", normalized(h.text).strip())
        maximum = 1 if h.kind == "image" else 2
        if key in seen_text or per_document[h.document_id] >= maximum:
            continue
        seen_text.add(key)
        per_document[h.document_id] += 1
        selected.append(h)
        if len(selected) == limit:
            break
    return selected


def contextual_question(question: str, previous: str) -> str:
    # Resolve short explicit follow-ups; do not contaminate a new standalone topic.
    followup = re.match(
        r"^(继续|再解释|再详细|展开|这个|那个|它|上面|上述|刚才|那[么呢]|然后|"
        r"continue\b|it\b|that\b|those\b|what about\b)",
        normalized(question),
    )
    return (
        previous[:2000] + "\n" + question
        if previous and followup and len(question) <= 80
        else question
    )
