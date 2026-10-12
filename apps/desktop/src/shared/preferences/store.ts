import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export interface Preferences {
  theme: 'system' | 'light' | 'dark'
  accent: 'neutral' | 'sage' | 'indigo' | 'amber'
  language: 'zh-CN' | 'en-US'
  fontSize: number
  fontFamily: 'system' | 'serif' | 'mono'
  sendKey: 'enter' | 'mod-enter'
}
export const preferenceDefaults: Preferences = {
  theme: 'system',
  accent: 'neutral',
  language: 'zh-CN',
  fontSize: 13,
  fontFamily: 'system',
  sendKey: 'enter',
}
const storageKey = 'edge-assistant.preferences.v1'
export function validatePreferences(value: unknown): Preferences {
  const input = value && typeof value === 'object' ? (value as Partial<Preferences>) : {}
  return {
    theme: ['light', 'dark', 'system'].includes(input.theme ?? '') ? input.theme! : 'system',
    accent: ['neutral', 'sage', 'indigo', 'amber'].includes(input.accent ?? '')
      ? input.accent!
      : 'neutral',
    language: input.language === 'en-US' ? 'en-US' : 'zh-CN',
    fontSize:
      typeof input.fontSize === 'number' && Number.isFinite(input.fontSize)
        ? Math.min(18, Math.max(12, input.fontSize))
        : preferenceDefaults.fontSize,
    fontFamily: ['system', 'serif', 'mono'].includes(input.fontFamily ?? '')
      ? input.fontFamily!
      : 'system',
    sendKey: input.sendKey === 'mod-enter' ? 'mod-enter' : 'enter',
  }
}
export const usePreferences = defineStore('preferences', () => {
  let initial = preferenceDefaults
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? '{}')
    initial = validatePreferences(saved)
    // Upgrade only the previous untouched defaults; keep customized reading choices.
    if (
      !saved.typographyVersion &&
      saved.theme === 'system' &&
      saved.accent === 'sage' &&
      saved.fontSize === 14 &&
      saved.fontFamily === 'system' &&
      saved.language === 'zh-CN' &&
      saved.sendKey === 'enter'
    ) {
      initial = { ...initial, accent: 'neutral', fontSize: preferenceDefaults.fontSize }
    }
    if (
      saved.typographyVersion === 2 &&
      saved.theme === 'system' &&
      saved.accent === 'neutral' &&
      saved.fontSize === 15 &&
      saved.fontFamily === 'system' &&
      saved.language === 'zh-CN' &&
      saved.sendKey === 'enter'
    )
      initial = { ...initial, fontSize: preferenceDefaults.fontSize }
  } catch {
    /* default on unavailable storage */
  }
  const values = ref<Preferences>({ ...initial })
  const storageError = ref(false)
  const media =
    typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-color-scheme: dark)')
      : undefined
  function apply() {
    if (typeof document === 'undefined') return
    const root = document.documentElement
    root.dataset.theme =
      values.value.theme === 'system' ? (media?.matches ? 'dark' : 'light') : values.value.theme
    root.dataset.accent = values.value.accent
    root.dataset.font = values.value.fontFamily
    root.lang = values.value.language
    root.style.setProperty('--font-ui-size', `${values.value.fontSize}px`)
  }
  media?.addEventListener('change', apply)
  watch(
    values,
    () => {
      apply()
      try {
        localStorage.setItem(storageKey, JSON.stringify({ ...values.value, typographyVersion: 3 }))
        storageError.value = false
      } catch {
        storageError.value = true
      }
    },
    { deep: true, flush: 'sync', immediate: true },
  )
  function reset() {
    values.value = { ...preferenceDefaults }
  }
  return { values, storageError, reset }
})
