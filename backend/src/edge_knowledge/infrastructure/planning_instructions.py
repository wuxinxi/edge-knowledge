"""Shared task semantics for local and explicit cloud planning adapters."""

CONTENT_SELECTION = (
    "按用户要的最终结果区分操作，不按‘找/find’等开头动词判断。"
    "找文件、图片、原文位置用 search/read；从资料内容中选出满足条件的具体对象，"
    "或判断、推荐、比较对象用 answer。这些也属于明确的解读需求。"
    "lookup_mode 只是用户当前查找入口的提示，allow_answer=true 时仍可规划明确的内容选择。"
    "对象的能力、语言或适用条件来自正文，不是文档目录的属性；"
    "不要把对象条件编成目录字段过滤，也不要只搜这些条件中的一个词。"
    "选择时保留全部条件和条件关系，不能把同时满足改为任意满足。"
    "已有 current_documents 时，内容选择用 answer、use_context=true、"
    "source_scope=full_document；它限定要读的资料，不代表已有正确答案。"
)
