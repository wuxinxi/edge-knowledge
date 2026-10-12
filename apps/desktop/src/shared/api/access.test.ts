import { afterEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { api } from './client'
afterEach(() => vi.unstubAllGlobals())
describe('native access transport', () => {
  it('sends a cloneable list rather than Vue reactive proxies across IPC', async () => {
    const importFiles = vi.fn(async (_grant: string, ids: string[], _library: string) => {
      expect(structuredClone(ids)).toEqual(['selected-file'])
      return { imported: 1, duplicates: 0, failed: [] }
    })
    vi.stubGlobal('window', { edgeDesktop: { access: { importFiles } } })
    const selected = reactive(['selected-file'])
    expect((await api.accessImport('grant-id', selected, 'default')).imported).toBe(1)
    expect(importFiles.mock.calls[0]![1]).not.toBe(selected)
  })
  it('does not pretend browser preview has native directory access', () => {
    vi.stubGlobal('window', {})
    expect(api.desktopAvailable()).toBe(false)
    expect(() => api.accessList()).toThrow('桌面应用')
  })
})
