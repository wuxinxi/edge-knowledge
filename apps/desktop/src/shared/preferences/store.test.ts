import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { usePreferences, validatePreferences } from './store'
import { useI18n } from '../i18n'
import { memoryStorage } from './test-storage'
beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  setActivePinia(createPinia())
})
it('validates saved settings and clamps font size', () => {
  expect(validatePreferences({ theme: 'bad', language: 'xx', fontSize: NaN }).theme).toBe('system')
  expect(validatePreferences({ fontSize: 100 }).fontSize).toBe(18)
  expect(validatePreferences({ fontSize: 1 }).fontSize).toBe(12)
})
it('persists appearance and language immediately and restores them', () => {
  const store = usePreferences()
  store.values.theme = 'dark'
  store.values.fontSize = 17
  store.values.language = 'en-US'
  setActivePinia(createPinia())
  expect(usePreferences().values).toMatchObject({ theme: 'dark', fontSize: 17, language: 'en-US' })
})
it('changes interface labels reactively without changing unknown source text', () => {
  const { t, preferences } = useI18n()
  expect(t('新对话')).toBe('新对话')
  preferences.values.language = 'en-US'
  expect(t('新对话')).toBe('New chat')
  expect(t('用户文件原文')).toBe('用户文件原文')
})

it('upgrades the previous untouched defaults to the new typography', () => {
  localStorage.setItem(
    'edge-assistant.preferences.v1',
    JSON.stringify({
      theme: 'system',
      accent: 'sage',
      fontSize: 14,
      fontFamily: 'system',
      language: 'zh-CN',
      sendKey: 'enter',
    }),
  )
  expect(usePreferences().values).toMatchObject({ accent: 'neutral', fontSize: 13 })
})
it('preserves customized appearance when migrating saved preferences', () => {
  localStorage.setItem(
    'edge-assistant.preferences.v1',
    JSON.stringify({
      theme: 'dark',
      accent: 'sage',
      fontSize: 14,
      fontFamily: 'serif',
      language: 'en-US',
      sendKey: 'mod-enter',
    }),
  )
  expect(usePreferences().values).toMatchObject({
    theme: 'dark',
    accent: 'sage',
    fontSize: 14,
    fontFamily: 'serif',
    language: 'en-US',
    sendKey: 'mod-enter',
  })
})
it('does not remigrate a new version with deliberately chosen old values', () => {
  localStorage.setItem(
    'edge-assistant.preferences.v1',
    JSON.stringify({
      theme: 'system',
      accent: 'sage',
      fontSize: 14,
      fontFamily: 'system',
      language: 'zh-CN',
      sendKey: 'enter',
      typographyVersion: 2,
    }),
  )
  expect(usePreferences().values).toMatchObject({ accent: 'sage', fontSize: 14 })
})

it('migrates the untouched version 2 typography once and persists the new default', () => {
  localStorage.setItem(
    'edge-assistant.preferences.v1',
    JSON.stringify({
      theme: 'system',
      accent: 'neutral',
      fontSize: 15,
      fontFamily: 'system',
      language: 'zh-CN',
      sendKey: 'enter',
      typographyVersion: 2,
    }),
  )
  expect(usePreferences().values.fontSize).toBe(13)
  expect(JSON.parse(localStorage.getItem('edge-assistant.preferences.v1')!).typographyVersion).toBe(
    3,
  )
})
it('preserves a deliberate larger font in the current typography version', () => {
  localStorage.setItem(
    'edge-assistant.preferences.v1',
    JSON.stringify({
      theme: 'system',
      accent: 'neutral',
      fontSize: 15,
      fontFamily: 'system',
      language: 'zh-CN',
      sendKey: 'enter',
      typographyVersion: 3,
    }),
  )
  expect(usePreferences().values.fontSize).toBe(15)
})
