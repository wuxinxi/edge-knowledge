"""Conservative local lookup routing; interpretation remains an explicit AI task."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Lookup:
    query: str
    kinds: tuple[str, ...] = ()


def local_lookup(question: str) -> Lookup | None:
    text = question.strip()
    if re.search(
        r"查重|去重|重复|分类|归类|聚类|\b(?:duplicates?|deduplicate|classify|cluster)\b",
        text,
        re.IGNORECASE,
    ):
        return None
    prefix = r"^(?:请帮我|帮我|请|麻烦)?\s*"
    if re.search(prefix + r"(?:总结|解释|分析|比较|对比|解读|翻译|改写|推荐)", text) or re.search(
        r"(?:并|然后|再)(?:帮我)?(?:分析|总结|解释|解读)|^(?:explain|summarize|analyse|analyze|compare)\b",
        text,
        re.IGNORECASE,
    ):
        return None
    command = re.match(
        prefix + r"(?:检索|搜索|查询|查找|找到|找|搜)(?:出|一下|一张|一些)?\s*", text
    )
    english = re.match(r"^(?:please\s+)?(?:find|search|look up|locate)\s+", text, re.IGNORECASE)
    direct_field = bool(
        re.search(
            r"(?:地址|用户名|密码|取件码|文件路径|文件名|编号|端口)(?:是多少|是什么|在哪|多少|哪里|[？?])",
            text,
        )
    )
    if not command and not english and not direct_field:
        return None
    query = text[(command or english).end() :] if command or english else text
    kinds = ()
    if re.search(
        r"图片|照片|截图|图像|图[？?。！!]*$|(?:对比|统计|性能)图|\b(?:image|photo|picture)s?\b",
        text,
        re.IGNORECASE,
    ):
        kinds = ("image",)
        query = re.sub(r"^(?:那|这|一|几)张\s*", "", query)
        query = re.sub(r"(?:的)?(?:图片|照片|截图|图像|图)[？?。！!]*$", "", query).strip()
    elif re.search(r"音视频|视频|录音|音频|\b(?:audio|video)\b", text, re.IGNORECASE):
        kinds = ("audio", "video")
    return Lookup(query or text, kinds)
