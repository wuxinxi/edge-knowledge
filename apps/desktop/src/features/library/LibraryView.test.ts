// @vitest-environment jsdom
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import LibraryView from './LibraryView.vue'
import { useAppStore } from '../../app/store'
import { api } from '../../shared/api/client'
import { memoryStorage } from '../../shared/preferences/test-storage'
vi.mock('../../app/store', async () => {
  const { reactive } = await import('vue')
  const app = reactive({
    activeLibrary: 'notes-a',
    health: {},
    capabilities: { embedding: { ready: true }, ocr: { available: true } },
    currentLibrary: { name: 'Notes', chunks: 2 },
    refreshLibraries: vi.fn().mockResolvedValue(undefined),
    refreshCapabilities: vi.fn(),
  })
  return { useAppStore: () => app }
})
vi.mock('../folders/FolderSourcesPanel.vue', () => ({
  default: { template: '<div class="folder-panel-test" />' },
}))
vi.mock('../../shared/api/client', () => ({
  api: {
    documents: vi.fn(),
    archived: vi.fn(),
    foldersAvailable: vi.fn(() => false),
    archiveDocuments: vi.fn(),
    pauseFolderSources: vi.fn().mockResolvedValue(undefined),
    extractImageText: vi.fn(),
    ingest: vi.fn(),
  },
}))
const entries = [
  {
    id: 'one',
    filename: 'one.md',
    kind: 'document',
    size: 200,
    chunks: 1,
    created_at: '2026-10-13',
  },
  {
    id: 'two',
    filename: 'two.md',
    kind: 'document',
    size: 300,
    chunks: 1,
    created_at: '2026-10-13',
  },
]
let root: HTMLDivElement, view: ReturnType<typeof createApp>
async function wait() {
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}
function button(text: string) {
  return [...root.querySelectorAll<HTMLButtonElement>('button')].find(
    (el) => el.textContent?.trim() === text,
  )!
}
async function mount() {
  root = document.createElement('div')
  document.body.append(root)
  view = createApp(LibraryView).use(createPinia())
  view.mount(root)
  await wait()
}
beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  vi.stubGlobal(
    'URL',
    class extends URL {
      static createObjectURL() {
        return 'blob:ocr-test'
      }
      static revokeObjectURL() {}
    },
  )
  Object.defineProperty(HTMLElement.prototype, 'hidePopover', {
    configurable: true,
    value: vi.fn(),
  })
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true,
    value() {
      this.setAttribute('open', '')
    },
  })
  vi.clearAllMocks()
  const app = useAppStore()
  app.activeLibrary = 'notes-a'
  app.capabilities!.embedding.ready = true
  vi.mocked(api.documents).mockResolvedValue(entries as never)
  vi.mocked(api.archived).mockResolvedValue([])
  vi.mocked(api.archiveDocuments).mockResolvedValue({
    archived: 2,
    document_ids: ['one', 'two'],
    folder_sync_paused: true,
  })
})
afterEach(() => {
  view?.unmount()
  root?.remove()
  vi.unstubAllGlobals()
})
it('shows files immediately and keeps imports, folder management and OCR reachable without large tool panels', async () => {
  await mount()
  expect(root.querySelectorAll('.document-row')).toHaveLength(2)
  expect(root.querySelector('.upload-zone')).toBeNull()
  expect(root.querySelector('.ocr-tool')).toBeNull()
  expect(root.querySelector('details.library-source-details')?.hasAttribute('open')).toBe(false)
  expect(root.querySelector('.library-bulk-bar')).toBeNull()
  expect(button('添加资料')).toBeDefined()
  expect(root.querySelector('#library-add-menu')?.textContent).toContain('导入文件')
  expect(root.querySelector('#library-add-menu')?.textContent).toContain('提取图片文字')
})
it('shows selection actions when needed and submits only selected IDs', async () => {
  await mount()
  root.querySelector<HTMLInputElement>('.document-checkbox')!.click()
  await wait()
  expect(root.querySelector('.library-bulk-bar')).not.toBeNull()
  button('删除所选').click()
  await wait()
  button('确认移入回收站').click()
  await wait()
  expect(api.archiveDocuments).toHaveBeenCalledWith('notes-a', ['one'], false)
})
it('clears the whole current library even when a name filter only shows one file', async () => {
  await mount()
  const search = root.querySelector<HTMLInputElement>('.library-filters input')!
  search.value = 'one'
  search.dispatchEvent(new Event('input'))
  await wait()
  expect(root.querySelectorAll('.document-row')).toHaveLength(1)
  button('清空全部资料').click()
  await wait()
  expect(root.querySelector('.library-bulk-scope')?.textContent).toContain('2')
  button('确认移入回收站').click()
  await wait()
  expect(api.pauseFolderSources).toHaveBeenCalledWith('notes-a')
  expect(api.archiveDocuments).toHaveBeenCalledWith('notes-a', [], true)
})
it('keeps standalone OCR available when the embedding model is not ready', async () => {
  useAppStore().capabilities!.embedding.ready = false
  vi.mocked(api.extractImageText).mockResolvedValue({
    text: 'A safe OCR sample',
    status: 'ready',
    engine: 'RapidOCR · ONNX Runtime',
  } as never)
  await mount()
  expect(button('提取图片文字本地识字，无需检索模型').disabled).toBe(false)
  const input = root.querySelector<HTMLInputElement>(
    'input[type="file"][accept=".png,.jpg,.jpeg,.webp"]',
  )!
  Object.defineProperty(input, 'files', { value: [new File(['image'], 'sample.png')] })
  input.dispatchEvent(new Event('change'))
  await wait()
  expect(api.extractImageText).toHaveBeenCalledTimes(1)
  expect(api.ingest).not.toHaveBeenCalled()
  expect(root.querySelector('.library-ocr-dialog')?.hasAttribute('open')).toBe(true)
  expect(root.querySelector('.library-ocr-dialog')?.textContent).toContain(
    'RapidOCR · ONNX Runtime',
  )
  expect(root.querySelector<HTMLTextAreaElement>('.ocr-extraction textarea')?.value).toBe(
    'A safe OCR sample',
  )
})

it('keeps select-all reachable before selecting an individual row', async () => {
  await mount()
  root.querySelector<HTMLInputElement>('.document-select-all input')!.click()
  await wait()
  expect(root.querySelector('.library-selected-count')?.textContent).toContain('2')
  expect(
    [...root.querySelectorAll<HTMLInputElement>('.document-checkbox')].every(
      (input) => input.checked,
    ),
  ).toBe(true)
})
