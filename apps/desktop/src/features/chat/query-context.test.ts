import { expect, it } from 'vitest'
import { conversationDocuments } from './query-context'
import type { Message } from './store'

it('builds optional context from document identities without inspecting question wording', () => {
  const message: Message = {
    id: 'answer',
    role: 'assistant',
    content: '结果',
    mode: 'search',
    status: 'complete',
    resultKind: 'retrieval',
    sources: [
      {
        document_id: 'a',
        filename: 'index.md',
        text: '片段',
        section: '正文',
        index: 0,
        score: 0.8,
      },
    ],
  }
  expect(conversationDocuments([message])).toEqual([{ id: 'a', filename: 'index.md' }])
  expect(
    conversationDocuments([
      { ...message, sources: [...message.sources, { ...message.sources[0]!, index: 1 }] },
    ]),
  ).toHaveLength(1)
  expect(
    conversationDocuments([
      { ...message, sources: [...message.sources, { ...message.sources[0]!, document_id: 'b' }] },
    ]),
  ).toHaveLength(2)
  for (const patch of [
    { status: 'stopped' },
    { status: 'error' },
    { error: '错误' },
    { resultKind: 'catalog' },
    { resultKind: 'comparison' },
  ])
    expect(conversationDocuments([{ ...message, ...patch } as Message])).toEqual([])
  expect(
    conversationDocuments([{ ...message, sources: [{ ...message.sources[0]!, kind: 'image' }] }]),
  ).toEqual([])
})
