// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import ChatMessage from './ChatMessage.vue'
import type { Message } from './store'
import { api } from '../../shared/api/client'
import { memoryStorage } from '../../shared/preferences/test-storage'

vi.mock('../../shared/api/client', () => ({ api: { imageAsset: vi.fn() } }))
vi.mock('../../shared/components/MediaPreview.vue', () => ({
  default: {
    props: ['library', 'document'],
    template: '<div class="local-media">Local media</div>',
  },
}))
let root: HTMLDivElement, view: ReturnType<typeof createApp>
const rawOCR = 'Mean Score\n(Task)\n60\n50\nMassive Audio Embedding Benchmark\nEmbeddingGemma 2'
const imageSource = {
  document_id: 'image',
  filename: 'chart.png',
  kind: 'image' as const,
  ocr_status: 'ready',
  text: rawOCR,
  index: 1,
  section: '图片文字',
  score: 0.8264,
}
async function mount(message: Message) {
  root = document.createElement('div')
  document.body.append(root)
  view = createApp(ChatMessage, {
    message,
    library: 'isolated-demo',
    generating: false,
    canRetry: false,
  }).use(createPinia())
  view.mount(root)
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}
beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  vi.clearAllMocks()
  vi.mocked(api.imageAsset).mockResolvedValue(new Blob(['fixture'], { type: 'image/png' }))
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:local-fixture')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {
    configurable: true,
    value: vi.fn(),
  })
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  })
})
afterEach(() => {
  view?.unmount()
  root?.remove()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('shows the found image in chat without opening a source dialog and keeps OCR collapsed', async () => {
  await mount({
    id: 'result',
    role: 'assistant',
    mode: 'search',
    content: '找到 1 份相关资料，结果如下。',
    sources: [imageSource],
  })
  expect(
    root
      .querySelector('.answer-source-grid.inline-source-grid .image-preview img')
      ?.getAttribute('src'),
  ).toBe('blob:local-fixture')
  expect(api.imageAsset).toHaveBeenCalledWith(
    'isolated-demo',
    'image',
    true,
    expect.any(AbortSignal),
  )
  const details = root.querySelector<HTMLDetailsElement>('.source-original-text')!
  expect(details.open).toBe(false)
  expect(details.querySelector('summary')?.textContent).toContain('本地 OCR')
  expect(details.querySelector('pre')?.textContent).toBe(rawOCR)
  const copy = [...details.querySelectorAll('button')].find((button) =>
    button.textContent?.includes('复制原文'),
  )!
  copy.click()
  await nextTick()
  expect(navigator.clipboard.writeText).toHaveBeenCalledWith(rawOCR)
})
it('shows images alongside AI interpretations too', async () => {
  await mount({
    id: 'result',
    role: 'assistant',
    mode: 'chat',
    content: '解读',
    sources: [imageSource],
  })
  expect(root.querySelector('.source-content-image img')).not.toBeNull()
  expect(root.textContent).toContain('DeepSeek 解读')
})

it('discloses AI planning for a locally calculated result without claiming the entire request was local', async () => {
  await mount({
    id: 'result',
    role: 'assistant',
    mode: 'search',
    planner: 'deepseek',
    content: '合计 6',
    sources: [],
    notice: '本次已调用 DeepSeek 规划，结果由本机计算。',
  })
  expect(root.querySelector('.assistant-mode')?.textContent).toContain('本机结果 · AI 规划')
  expect(root.textContent).toContain('已调用 DeepSeek 规划')
})
it('renders all matching document excerpts as safe Markdown while retaining full raw text', async () => {
  const source = {
    document_id: 'doc',
    filename: 'notes.md',
    text: '# 操作清单\n\n- 第一步\n- 第二步\n\n<script>alert(1)</script>',
    section: '操作',
    index: 0,
    score: 0.9,
  }
  await mount({
    id: 'result',
    role: 'assistant',
    mode: 'search',
    content: '找到 1 份相关资料',
    sources: [source, { ...source, index: 1, text: '后续步骤' }],
  })
  expect(root.querySelectorAll('.source-document-excerpt')).toHaveLength(2)
  expect(root.querySelector('.source-document-excerpt h1')?.textContent).toBe('操作清单')
  expect(root.querySelectorAll('.source-document-excerpt li')).toHaveLength(2)
  expect(root.querySelector('script')).toBeNull()
  expect(root.querySelector('.source-original-text pre')?.textContent).toBe(source.text)
})
it('does not display unavailable OCR labels as recognized image text', async () => {
  await mount({
    id: 'result',
    role: 'assistant',
    mode: 'search',
    content: '找到图片',
    sources: [{ ...imageSource, ocr_status: 'unavailable', text: '图片：chart.png' }],
  })
  expect(root.querySelector('.source-original-text')).toBeNull()
  expect(root.textContent).toContain('暂无可用图片文字')
})

it('does not render YAML frontmatter as an oversized heading and retains the original', async () => {
  const text = '---\ntitle: 九月笔记\nupdatedAt: 2026-10-07\ndescription: 测试描述\n---\n\n正文内容'
  await mount({
    id: 'result',
    role: 'assistant',
    mode: 'search',
    content: '结果',
    sources: [
      { document_id: 'doc', filename: 'index.md', text, section: '', index: 0, score: 0.9 },
    ],
  })
  expect(root.querySelector('.source-document-excerpt h2')).toBeNull()
  expect(root.querySelector('.source-document-excerpt')?.textContent).toContain('正文内容')
  expect(root.querySelector('.source-original-text pre')?.textContent).toBe(text)
})

it('labels local model answers separately from local retrieval and cloud answers', async () => {
  await mount({
    id: 'local',
    role: 'assistant',
    mode: 'chat',
    generator: 'local',
    planner: 'local_model',
    content: '本地回答',
    sources: [],
  })
  expect(root.querySelector('.assistant-mode')?.textContent).toContain('本地模型回答')
  expect(root.querySelector('.assistant-mode')?.textContent).not.toContain('DeepSeek')
})
