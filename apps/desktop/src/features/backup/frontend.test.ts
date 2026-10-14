import { describe, it, expect } from 'vitest'
import { portableFrontend, restoredChats, validateChatBackup } from './frontend'
import { preferenceDefaults } from '../../shared/preferences/store'
const conversation = {
  id: 'chat',
  library: 'default',
  title: 'Sample',
  createdAt: '2026-10-12',
  updatedAt: '2026-10-12',
  references: [{ id: 'doc', filename: 'notes.md' }],
  messages: [
    {
      id: 'm',
      role: 'assistant' as const,
      content: 'Text',
      sources: [
        {
          document_id: 'doc',
          filename: 'notes.md',
          text: 'Source',
          section: 'Intro',
          index: 0,
          score: 0.8,
        },
      ],
      mode: 'chat' as const,
    },
  ],
}
describe('portable conversation backups', () => {
  it('keeps explicit result kinds and previous answer kinds through backup and restore', () => {
    const message = {
      ...conversation.messages[0]!,
      resultKind: 'retrieval' as const,
      versions: [
        {
          content: '请补充年份',
          sources: [],
          savedAt: '2026',
          resultKind: 'clarification' as const,
        },
      ],
    }
    const backup = portableFrontend([{ ...conversation, messages: [message] }], preferenceDefaults)
    const restored = restoredChats(backup.chats, { default: 'copy' })[0]!.messages[0]!
    expect(restored.resultKind).toBe('retrieval')
    expect(restored.versions![0]!.resultKind).toBe('clarification')
    expect(() =>
      validateChatBackup({
        version: 1,
        sessions: [{ ...conversation, messages: [{ ...message, resultKind: 'unknown' }] }],
      }),
    ).toThrow()
  })
  it('preserves unsent drafts without including upload permission and rejects malformed drafts', () => {
    const draft = {
      content: '  完整草稿\n\n结尾  ',
      mode: 'search' as const,
      allowImageUpload: true,
    }
    const backup = portableFrontend([{ ...conversation, draft }], preferenceDefaults)
    const restored = restoredChats(backup.chats, { default: 'copy' })[0]!
    expect(restored.draft).toEqual({ content: draft.content, mode: 'search' })
    expect(JSON.stringify(backup)).not.toContain('allowImageUpload')
    expect(
      validateChatBackup({ version: 1, sessions: [{ ...conversation, draft: null }] })[0]!.draft,
    ).toBeUndefined()
    expect(() =>
      validateChatBackup({
        version: 1,
        sessions: [{ ...conversation, draft: { content: 1, mode: 'chat' } }],
      }),
    ).toThrow()
  })
  it('remaps restored conversations without replacing existing identifiers', () => {
    const restored = restoredChats(
      { version: 1, sessions: [conversation] },
      { default: 'restored-library' },
    )
    expect(restored[0]!.library).toBe('restored-library')
    expect(restored[0]!.id).not.toBe('chat')
    expect(restored[0]!.messages[0]!.id).not.toBe('m')
    expect(restored[0]!.references).toEqual(conversation.references)
    expect(conversation.library).toBe('default')
  })
  it('rejects malformed conversations and omits unrelated scopes', () => {
    expect(() =>
      validateChatBackup({
        version: 1,
        sessions: [{ ...conversation, messages: [{ role: 'script' }] }],
      }),
    ).toThrow()
    expect(restoredChats({ version: 1, sessions: [conversation] }, {})).toEqual([])
  })
  it('exports only whitelisted conversation and preference fields', () => {
    const extraChat = { ...conversation, api_key: 'excluded' }
    const extraPreferences = { ...preferenceDefaults, api_key: 'excluded' }
    const result = portableFrontend([extraChat], extraPreferences)
    expect(JSON.stringify(result)).not.toContain('excluded')
    expect(result.preferences.fontSize).toBe(13)
  })
})

it('exports full long messages and previous answer versions without truncation', () => {
  const content = '完整文字\n'.repeat(40000)
  const chat = {
    ...conversation,
    titleSource: 'manual' as const,
    messages: [
      {
        ...conversation.messages[0]!,
        content,
        status: 'complete' as const,
        versions: [
          {
            content,
            sources: conversation.messages[0]!.sources,
            savedAt: '2026',
            notice: '旧回答',
          },
        ],
      },
    ],
  }
  const result = portableFrontend([chat], preferenceDefaults)
  const restored = restoredChats(result.chats, { default: 'copy' })[0]!
  expect(restored.messages[0]!.content).toBe(content)
  expect(restored.messages[0]!.versions![0]!.content).toBe(content)
  expect(restored.messages[0]!.versions![0]!.notice).toBe('旧回答')
  expect(restored.titleSource).toBe('manual')
})

it('preserves both duplicate sides, original whitespace and historical comparisons', () => {
  const source = {
    ...conversation.messages[0]!.sources[0]!,
    path: 'notes/项目/notes.md',
    text: '  原文\n\n结尾  ',
  }
  const pair = {
    left: source,
    right: { ...source, document_id: 'copy', path: 'archive/项目/notes.md' },
    score: 1,
    exact: true,
    body_exact: true,
    content_similarity: 1,
  }
  const backup = validateChatBackup({
    version: 1,
    sessions: [
      {
        ...conversation,
        messages: [
          {
            ...conversation.messages[0],
            comparisons: [pair],
            versions: [{ content: 'Old', sources: [], savedAt: '2026-10-13', comparisons: [pair] }],
          },
        ],
      },
    ],
  })
  expect(backup[0]!.messages[0]!.comparisons).toEqual([pair])
  expect(backup[0]!.messages[0]!.versions![0]!.comparisons).toEqual([pair])
})

it('preserves processing activity for the answer and each historic version and rejects invalid stages', () => {
  const processing = {
    startedAt: 100,
    finishedAt: 600,
    steps: [{ stage: 'retrieving' as const, startedAt: 100 }],
  }
  const message = {
    ...conversation.messages[0]!,
    processing,
    versions: [{ content: 'old', sources: [], savedAt: '2026', processing }],
  }
  const saved = validateChatBackup({
    version: 1,
    sessions: [{ ...conversation, messages: [message] }],
  })[0]!.messages[0]!
  expect(saved.processing).toEqual(processing)
  expect(saved.versions![0]!.processing).toEqual(processing)
  expect(() =>
    validateChatBackup({
      version: 1,
      sessions: [
        {
          ...conversation,
          messages: [
            {
              ...message,
              processing: { ...processing, steps: [{ stage: 'invented', startedAt: 100 }] },
            },
          ],
        },
      ],
    }),
  ).toThrow('处理过程')
})

it('preserves full document scope and all text through backup restoration and answer history', () => {
  const source = {
    ...conversation.messages[0]!.sources[0]!,
    content_scope: 'full_document' as const,
    text: '完整原文\n' + '内容。'.repeat(3000),
  }
  const message = {
    ...conversation.messages[0]!,
    sources: [source],
    versions: [{ content: '此前回答', sources: [source], savedAt: '2026' }],
  }
  const backup = portableFrontend([{ ...conversation, messages: [message] }], preferenceDefaults)
  const restored = restoredChats(backup.chats, { default: 'copy' })[0]!.messages[0]!
  expect(restored.sources[0]!.content_scope).toBe('full_document')
  expect(restored.sources[0]!.text).toBe(source.text)
  expect(restored.versions![0]!.sources[0]!.content_scope).toBe('full_document')
  expect(() =>
    validateChatBackup({
      version: 1,
      sessions: [
        {
          ...conversation,
          messages: [{ ...message, sources: [{ ...source, content_scope: 'partial-as-full' }] }],
        },
      ],
    }),
  ).toThrow()
})
