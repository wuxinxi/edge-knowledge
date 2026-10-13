from dataclasses import replace

from edge_knowledge.domain.media_relevance import select_media_hits
from edge_knowledge.domain.models import SearchHit


def image(document, text, score, index=0, status="ready"):
    return SearchHit(document, document + ".png", text, "图片文字", index, score, "image", status)


def test_ocr_across_chunks_is_checked_before_visual_deduplication():
    hits = [
        image("target", "unrelated excerpt", 0.95),
        image("target", "Massive Audio", 0.42, 1),
        image("target", "Embedding Benchmark", 0.43, 2),
        image("other", "Audio embedding tools", 0.96),
    ]
    selected, strategy, count = select_media_hits(
        "Massive Audio Embedding Benchmark", hits, 0.55, "auto", True
    )
    assert [hit.document_id for hit in selected] == ["target"]
    assert selected[0].index == 2 and selected[0].score == 0.43
    assert strategy == "image_text" and count == 2


def test_phrase_normalizes_ocr_lines_case_punctuation_and_chinese():
    hits = [
        image("first", "MASSIVE AUDIO\nEmbedding: Benchmark", 0.35),
        image("second", "Audio embedding benchmarks", 0.95),
    ]
    assert select_media_hits("Massive Audio Embedding Benchmark", hits, 0.55, "auto", True)[0] == [
        hits[0]
    ]
    chinese = [image("chart", "音频嵌入\n性能对比", 0.4), image("intro", "音频与视频介绍", 0.9)]
    assert select_media_hits("音频嵌入性能对比", chinese, 0.55, "auto", True)[0] == [chinese[0]]


def test_visual_description_keeps_textless_images_but_drops_weak_neighbors():
    hits = [
        image("bird", "", 0.81, status="empty"),
        image("bird2", "", 0.77, status="empty"),
        image("chart", "audio embedding benchmark", 0.65),
    ]
    selected, strategy, _ = select_media_hits("海边飞翔的鸟", hits, 0.55, "auto", True)
    assert [hit.document_id for hit in selected] == ["bird", "bird2"]
    assert strategy == "semantic"
    assert not select_media_hits(
        "海边飞翔的鸟", [replace(hit, score=0.3) for hit in hits], 0.55, "auto", True
    )[0]


def test_reference_images_and_mixed_queries_are_not_reduced_to_ocr_matches():
    hits = [
        image("chart", "Massive Audio Embedding Benchmark", 0.6),
        image("reference", "", 0.98, status="empty"),
    ]
    selected, strategy, _ = select_media_hits(
        "Massive Audio Embedding Benchmark", hits, 0.55, "auto", False
    )
    assert selected == [hits[1]] and strategy == "semantic"


def test_explicit_ocr_mode_has_no_visual_or_filename_fallback():
    hits = [
        image("Massive Audio Embedding Benchmark", "", 0.99, status="unavailable"),
        image("other", "Audio benchmark unrelated", 0.9),
    ]
    selected, strategy, _ = select_media_hits(
        "Massive Audio Embedding Benchmark", hits, 0.55, "image_text", True
    )
    assert not selected and strategy == "image_text"


def test_broad_mode_still_honors_score_floor_and_does_not_fill_top_k():
    hits = [image("a", "same text", 0.9), image("b", "same text", 0.65), image("c", "", 0.3)]
    selected, strategy, count = select_media_hits("same text", hits, 0.55, "broad", True)
    assert selected == hits[:2] and strategy == "broad" and count == 3
