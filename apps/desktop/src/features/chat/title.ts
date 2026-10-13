import type { Conversation } from '../../shared/types/conversations'
const generic = /^(新对话|new chat|untitled|未命名|新会话)?$/i
export function conversationSummary(chat: Conversation): string {
  const first = chat.messages.find((m) => m.role === 'user' && m.content.trim())?.content ?? ''
  let topic = first
    .trim()
    .replace(/\s+/g, ' ')
    .replace(
      /^(请帮我|帮我|麻烦你|请问|请|能否|可以帮我|please\s+)(查询出|查询|查找|查一下|整理|解释|总结|告诉我)?\s*/i,
      '',
    )
    .replace(/(是多少|是什么|怎么办|如何处理|吗|呢)[？?。！!]*$/, '')
    .replace(/[？?。！!]+$/, '')
    .trim()
  if (/\b(fpt|ftp)\b/i.test(topic) && /地址|用户名|密码/.test(topic)) {
    const entity = topic
      .split(/的?\s*(?:fpt|ftp)\b/i)[0]
      ?.replace(/的$/, '')
      .trim()
    topic = `${entity ? entity + ' · ' : ''}FTP 连接信息`
  }
  return topic.length > 28 ? topic.slice(0, 27) + '…' : topic
}
export function updateConversationTitle(chat: Conversation) {
  if (chat.titleSource === 'manual') return
  const first = chat.messages.find((m) => m.role === 'user')?.content.trim() ?? ''
  if (
    chat.titleSource === 'auto' ||
    generic.test(chat.title.trim()) ||
    chat.title === first.slice(0, 40)
  ) {
    chat.title = conversationSummary(chat)
    chat.titleSource = 'auto'
  }
}
