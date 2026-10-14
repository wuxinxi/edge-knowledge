// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
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
async function mount(
  message: Message,
  options: {
    request?: Message
    canRetry?: boolean
    canEdit?: boolean
    hasDraft?: boolean
    onEdit?: () => void
  } = {},
) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: ['/', '/library'].map((path) => ({ path, component: { template: '<div />' } })),
  })
  await router.push('/')
  root = document.createElement('div')
  document.body.append(root)
  view = createApp(ChatMessage, {
    message,
    library: 'isolated-demo',
    generating: false,
    canRetry: false,
    ...options,
  })
    .use(createPinia())
    .use(router)
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
it('keeps AI answer sources compact and opens the original image only on demand', async () => {
  await mount({
    id: 'result',
    role: 'assistant',
    mode: 'chat',
    content: '解读',
    sources: [imageSource],
  })
  expect(root.querySelector('.source-content-image img')).toBeNull()
  expect(api.imageAsset).not.toHaveBeenCalled()
  expect(root.textContent).toContain('DeepSeek 解读')
  const toggle = root.querySelector<HTMLButtonElement>('.source-disclosure')!
  expect(toggle.getAttribute('aria-expanded')).toBe('false')
  toggle.click()
  await nextTick()
  expect(root.querySelectorAll('.answer-source-card')).toHaveLength(1)
  expect(api.imageAsset).not.toHaveBeenCalled()
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true,
    value: vi.fn(),
  })
  root.querySelector<HTMLButtonElement>('.answer-source-card')!.click()
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(root.querySelector('.source-preview-body img')).not.toBeNull()
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
  expect(root.querySelectorAll('.source-document-excerpt')).toHaveLength(1)
  root.querySelector<HTMLButtonElement>('.source-snippet-toggle')!.click()
  await nextTick()
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

it('shows duplicate notes side by side with safe excerpts and distinguishes exact matches', async () => {
  const source = {
    document_id: 'left',
    filename: 'index.md',
    path: 'notes/部署/index.md',
    text: '# 部署\n\n安装依赖。<script>alert(1)</script>',
    section: '查重',
    index: 0,
    score: 1,
  }
  await mount({
    id: 'comparison',
    role: 'assistant',
    mode: 'search',
    content: '发现 1 对候选',
    sources: [],
    comparisons: [
      {
        left: source,
        right: { ...source, document_id: 'right', path: 'archive/部署/index.md' },
        score: 1,
        exact: true,
      },
    ],
  })
  expect(root.querySelectorAll('.duplicate-match-side')).toHaveLength(2)
  expect(root.textContent).toContain('内容一致')
  expect(root.textContent).toContain('notes/部署/index.md')
  expect(root.textContent).toContain('archive/部署/index.md')
  expect(root.querySelector('script')).toBeNull()
  expect(root.querySelector('dialog[open]')).toBeNull()
})

it('limits inline results to four files and reveals the remaining files without losing evidence', async () => {
  await mount({
    id: 'many',
    role: 'assistant',
    mode: 'search',
    content: '找到图片',
    sources: Array.from({ length: 7 }, (_, i) => ({
      ...imageSource,
      document_id: `image-${i}`,
      filename: `chart-${i}.png`,
    })),
    notice: '完整处理说明',
  })
  expect(root.querySelectorAll('.answer-source-result')).toHaveLength(4)
  expect(api.imageAsset).toHaveBeenCalledTimes(4)
  expect(root.querySelector<HTMLDetailsElement>('.answer-processing-note')?.open).toBe(false)
  root.querySelector<HTMLButtonElement>('.source-disclosure')!.click()
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(root.querySelectorAll('.answer-source-result')).toHaveLength(7)
  expect(api.imageAsset).toHaveBeenCalledTimes(7)
})

it('labels statistics correctly and keeps supporting documents folded below the calculated result', async () => {
  await mount({
    id: 'statistics',
    role: 'assistant',
    mode: 'search',
    content: '共 3 份笔记',
    queryPlan: { operation: 'aggregate', metric: 'count' },
    sources: [{ ...imageSource, kind: 'document', filename: 'notes.md' }],
  })
  expect(root.querySelector('.assistant-mode')?.textContent).toContain('本地统计')
  expect(root.querySelector('.source-document-excerpt')).toBeNull()
  expect(root.querySelector('.source-disclosure')?.getAttribute('aria-expanded')).toBe('false')
  expect(root.textContent).toContain('共 3 份笔记')
})

it('shows actionable empty retrieval feedback with the original reference scope', async () => {
  const edit = vi.fn()
  await mount(
    {
      id: 'empty',
      role: 'assistant',
      mode: 'search',
      resultKind: 'retrieval',
      status: 'complete',
      content: '没有找到相关资料',
      sources: [],
    },
    {
      request: {
        id: 'q',
        role: 'user',
        content: '寻找部署步骤',
        sources: [],
        references: [{ id: 'doc', filename: '部署笔记.md' }],
      },
      canRetry: true,
      canEdit: true,
      onEdit: edit,
    },
  )
  expect(root.querySelector('.empty-search-result')).not.toBeNull()
  expect(root.querySelector('.empty-search-scope')?.textContent).toContain(
    '仅引用资料 · 部署笔记.md',
  )
  expect(root.querySelector('.empty-search-actions a')?.getAttribute('href')).toBe('/library')
  root.querySelector<HTMLButtonElement>('.empty-search-actions button')!.click()
  await nextTick()
  expect(edit).toHaveBeenCalledOnce()
})

it('protects existing drafts when editing an empty result question', async () => {
  const edit = vi.fn()
  await mount(
    {
      id: 'empty',
      role: 'assistant',
      resultKind: 'retrieval',
      status: 'complete',
      content: '没有找到相关资料',
      sources: [],
    },
    {
      request: { id: 'q', role: 'user', content: '问题', sources: [] },
      canRetry: true,
      canEdit: false,
      hasDraft: true,
      onEdit: edit,
    },
  )
  const button = root.querySelector<HTMLButtonElement>('.empty-search-actions button')!
  expect(button.disabled).toBe(true)
  button.click()
  expect(edit).not.toHaveBeenCalled()
  expect(root.textContent).toContain('输入框已有草稿')
})

it.each([
  ['catalog', 'complete'],
  ['clarification', 'complete'],
  ['comparison', 'complete'],
  ['answer', 'complete'],
  ['retrieval', 'error'],
  ['retrieval', 'stopped'],
  ['retrieval', 'streaming'],
  [undefined, 'complete'],
] as const)('does not misrepresent %s/%s as an empty retrieval', async (resultKind, status) => {
  await mount({
    id: 'other',
    role: 'assistant',
    mode: 'search',
    resultKind,
    status,
    content: '保留原始说明',
    sources: [],
  })
  expect(root.querySelector('.empty-search-result')).toBeNull()
  expect(root.textContent).toContain('保留原始说明')
})

it('lets users read and copy long document results in place and shows paths for same-name notes', async () => {
  const raw =
    '# 部署步骤\n\n' + '- 先检查配置，随后验证服务。\n'.repeat(120) + '\n最后一步：查看健康状态。'
  const source = {
    document_id: 'doc',
    filename: 'index.md',
    path: '项目/部署/index.md',
    text: raw,
    section: '上线流程',
    index: 0,
    score: 0.9,
    kind: 'document' as const,
  }
  await mount({
    id: 'reading',
    role: 'assistant',
    mode: 'search',
    content: '找到 2 份相关资料',
    sources: [source, { ...source, document_id: 'other', path: '笔记/运维/index.md' }],
  })
  expect(root.querySelector('.answer-source-grid.document-source-grid')).not.toBeNull()
  expect(
    [...root.querySelectorAll('.answer-source-card .source-path')].map((node) => node.textContent),
  ).toEqual(['项目/部署/index.md', '笔记/运维/index.md'])
  expect(root.querySelector('.source-section-label')?.textContent).toBe('上线流程')
  const reading = root.querySelector('.source-excerpt-reading')!
  expect(reading.classList.contains('is-clipped')).toBe(true)
  const toggle = [
    ...root.querySelectorAll<HTMLButtonElement>('.source-reading-actions button'),
  ].find((button) => button.textContent?.includes('展开阅读'))!
  toggle.click()
  await nextTick()
  expect(reading.classList.contains('is-clipped')).toBe(false)
  expect(reading.textContent).toContain('最后一步：查看健康状态。')
  expect(reading.querySelectorAll('li')).toHaveLength(120)
  const copy = [...root.querySelectorAll<HTMLButtonElement>('.source-reading-actions button')].find(
    (button) => button.textContent?.includes('复制片段'),
  )!
  copy.click()
  await nextTick()
  expect(navigator.clipboard.writeText).toHaveBeenCalledWith(raw)
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true,
    value: vi.fn(),
  })
  root.querySelector<HTMLButtonElement>('.answer-source-card')!.click()
  await nextTick()
  expect(root.querySelector('.source-preview-body .source-excerpt-reading')?.textContent).toContain(
    '最后一步：查看健康状态。',
  )
  expect(root.querySelector('.source-preview-body .is-clipped')).toBeNull()
  toggle.click()
  await nextTick()
  expect(reading.classList.contains('is-clipped')).toBe(true)
})

it('labels the full original, expands every section, copies the whole text and offers a summary', async () => {
  const text =
    '---\ntitle: 完整文章\n---\n\n# 完整文章\n\n' +
    '段落内容。'.repeat(260) +
    '\n\n## 最后章节\n末尾完整原文标记'
  const source = {
    document_id: 'note',
    filename: 'index.md',
    text,
    section: '完整文章',
    index: 0,
    score: 0,
    kind: 'document' as const,
    content_scope: 'full_document' as const,
  }
  await mount({
    id: 'read',
    role: 'assistant',
    content: '已打开文章',
    sources: [source],
    mode: 'search',
    status: 'complete',
    resultKind: 'retrieval',
  })
  expect(root.textContent).toContain('文章全文')
  expect(root.textContent).toContain('完整原文')
  expect(root.textContent).toContain('最后章节')
  const expand = [...root.querySelectorAll<HTMLButtonElement>('button')].find((button) =>
    button.textContent?.includes('展开全文'),
  )!
  expect(expand).toBeDefined()
  expand.click()
  await nextTick()
  expect(root.querySelector('.source-excerpt-reading')?.classList.contains('is-clipped')).toBe(
    false,
  )
  const copy = [...root.querySelectorAll<HTMLButtonElement>('button')].find((button) =>
    button.textContent?.includes('复制全文'),
  )!
  copy.click()
  await nextTick()
  expect(navigator.clipboard.writeText).toHaveBeenCalledWith(text)
  expect(root.querySelector('.article-followup-actions')?.textContent).toContain('总结这篇文章')
  expect(root.querySelector('.article-followup-actions')?.textContent).toContain('本地模型')
})

it('offers full article reading for excerpt results while keeping the excerpt label', async () => {
  await mount({
    id: 'search',
    role: 'assistant',
    content: '找到资料',
    sources: [
      {
        document_id: 'doc',
        filename: 'index.md',
        text: '命中片段',
        section: '章节',
        index: 2,
        score: 0.8,
      },
    ],
    mode: 'search',
    status: 'complete',
    resultKind: 'retrieval',
  })
  expect(root.textContent).toContain('阅读全文')
  expect(root.textContent).not.toContain('完整原文')
})
