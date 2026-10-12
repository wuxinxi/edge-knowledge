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
