<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch, nextTick } from 'vue'
import {
  ImagePlus,
  LoaderCircle,
  Search,
  Shapes,
  Upload,
  X,
  Download,
  Image as ImageIcon,
  Play,
  FolderPlus,
  Layers3,
  ShieldCheck,
  FileText,
} from '@lucide/vue'
import { useAppStore } from '../../app/store'
import { useI18n } from '../../shared/i18n'
import { api } from '../../shared/api/client'
import type {
  Document,
  EmbeddingBudget,
  MediaKind,
  OrganizationResult,
  SemanticResult,
} from '../../shared/types/api'
import ImagePreview from '../../shared/components/ImagePreview.vue'
import MediaPreview from '../../shared/components/MediaPreview.vue'
import './semantic.css'
import { useTaskStore } from '../tasks/store'
import TaskFeedback from '../tasks/TaskFeedback.vue'
import { workflows, inputIssue, targetKinds, type Workflow } from './workflows'
const app = useAppStore(),
  { t } = useI18n()
const tasks = useTaskStore(),
  feedbackId = ref('')
const operationTask = computed(() => tasks.get(feedbackId.value))
function beginFeedback(title: string, library: string) {
  if (feedbackId.value) tasks.setActions(feedbackId.value, {})
  feedbackId.value = tasks.begin(title, library, { stop: cancel, stopLabel: '停止等待' })
  return feedbackId.value
}
function failFeedback(id: string, message: string) {
  tasks.finish(id, 'error', message)
  tasks.setActions(id, { retry: () => void run() })
}
const workflow = ref<Workflow>('images')
const tab = computed(() =>
  workflow.value === 'collect' ? 'ingest' : workflow.value === 'organize' ? 'organize' : 'search',
)
const currentWorkflow = computed(() => workflows.find((item) => item.id === workflow.value)!)
const icons = {
  images: ImageIcon,
  media: Play,
  mixed: Layers3,
  collect: FolderPlus,
  organize: Shapes,
}
const text = ref(''),
  name = ref(''),
  files = ref<File[]>([])
const resultSection = ref<HTMLElement>()
const input = ref<HTMLInputElement>(),
  previews = ref<string[]>([]),
  dimension = ref(768),
  topK = ref(10)
const task = ref<'search' | 'code' | 'qa' | 'fact'>('search'),
  kind = ref<MediaKind | ''>('image')
const matchMode = ref<'auto' | 'image_text' | 'broad'>('auto'),
  minScore = ref(0.55)
const canMatchImageText = computed(
  () => targetKinds(workflow.value, kind.value).join(',') === 'image' && !files.value.length,
)
const effectiveMatchMode = computed(() =>
  matchMode.value === 'image_text' && !canMatchImageText.value ? 'auto' : matchMode.value,
)
watch(canMatchImageText, (available) => {
  if (!available && matchMode.value === 'image_text') matchMode.value = 'auto'
})
const archived = ref<Document[]>([]),
  documents = ref<Document[]>([]),
  scope = ref<string[]>([]),
  busy = ref(false),
  error = ref(''),
  notice = ref('')
const searchResult = ref<SemanticResult>(),
  organization = ref<OrganizationResult>(),
  budget = ref<EmbeddingBudget>()
const organizeTask = ref<'classification' | 'clustering' | 'similarity'>('classification'),
  labels = ref('技术文档, 生活资料, 工作票据'),
  clusters = ref(3),
  threshold = ref(0.92),
  sameKindOnly = ref(true),
  classificationThreshold = ref(0.2)
const advanced = ref(false),
  scopeSearch = ref(''),
  labelDraft = ref(''),
  dragOver = ref(false),
  galleryOpen = ref(false),
  gallerySearch = ref(''),
  galleryPage = ref(1)
const labelItems = computed(() =>
  labels.value
    .split(/[,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean),
)
const scopeDocuments = computed(() =>
  documents.value.filter((item) =>
    item.filename.toLowerCase().includes(scopeSearch.value.toLowerCase()),
  ),
)
const issue = computed(() => inputIssue(workflow.value, files.value))
const duplicatePairs = computed(() =>
  (organization.value?.pairs ?? []).filter((pair) => {
    if (!sameKindOnly.value || pair.exact) return true
    const docs = organization.value?.documents ?? []
    return (
      docs.find((doc) => doc.id === pair.left)?.kind ===
      docs.find((doc) => doc.id === pair.right)?.kind
    )
  }),
)
const valid = computed(
  () =>
    Boolean(text.value.trim() || files.value.length) &&
    !issue.value &&
    (tab.value === 'ingest' || matchingDocuments.value.length > 0),
)
const matchingDocuments = computed(() =>
  documents.value.filter((doc) =>
    workflow.value === 'images'
      ? doc.kind === 'image'
      : workflow.value === 'media'
        ? ['audio', 'video'].includes(doc.kind)
        : true,
  ),
)
const galleryItems = computed(() =>
  matchingDocuments.value.filter((doc) =>
    doc.filename.toLowerCase().includes(gallerySearch.value.toLowerCase()),
  ),
)
const galleryPages = computed(() => Math.max(1, Math.ceil(galleryItems.value.length / 24)))
const galleryVisible = computed(() =>
  galleryItems.value.slice((galleryPage.value - 1) * 24, galleryPage.value * 24),
)
watch(gallerySearch, () => {
  galleryPage.value = 1
})
watch(galleryPages, (count) => {
  if (galleryPage.value > count) galleryPage.value = count
})
const effectiveCount = computed(() => scope.value.length || documents.value.length)
const canOrganize = computed(
  () =>
    effectiveCount.value > 0 &&
    effectiveCount.value <= 200 &&
    (organizeTask.value !== 'classification' || labelItems.value.length > 0),
)
function setWorkflow(value: Workflow) {
  if (busy.value || workflow.value === value) return
  cancel()
  workflow.value = value
  kind.value = value === 'images' ? 'image' : ''
  task.value = 'search'
  advanced.value = false
  budget.value = undefined
  searchResult.value = undefined
  organization.value = undefined
  error.value = ''
  notice.value = ''
}
function addLabel() {
  const value = labelDraft.value.trim()
  if (value && !labelItems.value.includes(value) && labelItems.value.length < 30)
    labels.value = [...labelItems.value, value].join(', ')
  labelDraft.value = ''
}
function removeLabel(label: string) {
  labels.value = labelItems.value.filter((item) => item !== label).join(', ')
}
function selectVisibleScope() {
  const ids = [...new Set([...scope.value, ...scopeDocuments.value.map((item) => item.id)])]
  if (ids.length > 200) {
    error.value = t('一次最多选择 200 份资料，请缩小筛选范围。')
    return
  }
  scope.value = ids
}
function dropFiles(event: DragEvent) {
  dragOver.value = false
  if (!busy.value && event.dataTransfer) addFiles(Array.from(event.dataTransfer.files))
}
function fileSize(size: number) {
  return size >= 1024 * 1024
    ? `${(size / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(size / 1024))} KB`
}

let controller: AbortController | undefined,
  loadGeneration = 0
function clearFiles() {
  error.value = ''
  previews.value.forEach((url) => {
    if (url) URL.revokeObjectURL(url)
  })
  previews.value = []
  files.value = []
}
function choose(event: Event) {
  const target = event.target as HTMLInputElement
  addFiles(Array.from(target.files ?? []))
  target.value = ''
}
function addFiles(chosen: File[]) {
  const message = inputIssue(workflow.value, [...files.value, ...chosen])
  if (message) {
    error.value = t(message)
    return
  }
  error.value = ''
  for (const file of chosen) {
    files.value.push(file)
    previews.value.push(/\.(png|jpe?g|webp)$/i.test(file.name) ? URL.createObjectURL(file) : '')
  }
}
function removeFile(index: number) {
  error.value = ''
  if (previews.value[index]) URL.revokeObjectURL(previews.value[index]!)
  files.value.splice(index, 1)
  previews.value.splice(index, 1)
}
async function useLibraryImage(doc: Document) {
  if (busy.value) return
  const library = app.activeLibrary,
    pending = (controller = new AbortController())
  busy.value = true
  error.value = ''
  try {
    const data = await api.imageAsset(library, doc.id, false, pending.signal)
    if (!pending.signal.aborted && library === app.activeLibrary) {
      galleryOpen.value = false
      addFiles([new File([data], doc.filename.replace(/\.[^.]+$/, '.png'), { type: 'image/png' })])
    }
  } catch (cause) {
    if (!pending.signal.aborted)
      error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (controller === pending) busy.value = false
  }
}
async function load() {
  const generation = ++loadGeneration,
    library = app.activeLibrary
  try {
    const [result, trash] = await Promise.all([api.documents(library), api.archived(library)])
    if (generation === loadGeneration) {
      documents.value = result
      archived.value = trash
    }
  } catch (cause) {
    if (generation === loadGeneration)
      error.value = cause instanceof Error ? cause.message : String(cause)
  }
}
async function run() {
  if (busy.value || !app.health || (tab.value === 'organize' ? !canOrganize.value : !valid.value))
    return
  controller?.abort()
  const current = (controller = new AbortController()),
    library = app.activeLibrary
  const feedback = beginFeedback(currentWorkflow.value.action, library)
  busy.value = true
  error.value = ''
  notice.value = ''
  searchResult.value = undefined
  organization.value = undefined
  budget.value = undefined
  try {
    if (tab.value !== 'organize') {
      tasks.update(feedback, { phase: '检查输入容量' })
      const check = await api.semanticBudget(
        {
          library_id: library,
          text: text.value,
          task: tab.value === 'ingest' ? 'document' : task.value,
        },
        files.value,
        current.signal,
      )
      if (current.signal.aborted) return
      budget.value = check
      if (!check.fits) {
        error.value = t('这组素材太大，请减少图片或缩短说明后重试。')
        failFeedback(feedback, error.value)
        return
      }
    }
    if (tab.value === 'organize') {
      tasks.update(feedback, {
        phase: '分析资料',
        detail: t('正在本地分析选定资料，首次加载模型可能较慢。'),
      })
      const result = await api.organize(
        {
          library_id: library,
          document_ids: scope.value,
          task: organizeTask.value,
          dimension: dimension.value,
          labels: labels.value
            .split(/[,，\n]/)
            .map((label) => label.trim())
            .filter(Boolean),
          clusters: clusters.value,
          threshold:
            organizeTask.value === 'classification'
              ? classificationThreshold.value
              : threshold.value,
        },
        current.signal,
      )
      if (!current.signal.aborted) organization.value = result
    } else if (tab.value === 'ingest') {
      tasks.update(feedback, { phase: '导入中', detail: t('素材正在本机编码与保存。') })
      const result = await api.semanticIngest(
        {
          library_id: library,
          text: text.value,
          name:
            name.value.trim() ||
            files.value
              .map((file) => file.name)
              .join(' + ')
              .slice(0, 255) ||
            t('联合素材'),
        },
        files.value,
        current.signal,
      )
      if (!current.signal.aborted) {
        if (result.budget) budget.value = { ...budget.value, ...result.budget }
        notice.value = result.duplicate ? t('已存在，跳过重复导入') : t('联合素材已入库')
        try {
          await app.refreshLibraries()
          await load()
        } catch {
          notice.value += `\n${t('资料已保存，但列表刷新失败，请手动刷新。')}`
        }
      }
    } else {
      tasks.update(feedback, {
        phase: '查找资料',
        detail: t('正在本地匹配资料，首次加载模型可能较慢。'),
      })
      const result = await api.semanticSearch(
        {
          library_id: library,
          text: text.value,
          dimension: dimension.value,
          top_k: topK.value,
          match_mode: effectiveMatchMode.value,
          min_score: minScore.value,
          task: task.value,
          document_ids: scope.value,
          kinds: targetKinds(workflow.value, kind.value),
        },
        files.value,
        current.signal,
      )
      if (!current.signal.aborted) {
        searchResult.value = result
        budget.value = { ...budget.value, ...result.budget }
      }
    }
    if (!current.signal.aborted) {
      tasks.finish(
        feedback,
        'success',
        notice.value ||
          (searchResult.value
            ? `${t('检索结果')} · ${searchResult.value.sources.length}`
            : t('整理结果已生成')),
      )
      await nextTick()
      resultSection.value?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
    }
  } catch (cause) {
    if (!current.signal.aborted) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      failFeedback(feedback, error.value)
    }
  } finally {
    if (!current.signal.aborted) busy.value = false
  }
}
async function previewBudget() {
  controller?.abort()
  const current = (controller = new AbortController())
  const feedback = beginFeedback('检查输入容量', app.activeLibrary)
  busy.value = true
  error.value = ''
  budget.value = undefined
  try {
    const result = await api.semanticBudget(
      {
        library_id: app.activeLibrary,
        text: text.value,
        task: tab.value === 'ingest' ? 'document' : task.value,
      },
      files.value,
      current.signal,
    )
    if (!current.signal.aborted) {
      budget.value = result
      tasks.finish(
        feedback,
        result.fits ? 'success' : 'error',
        t(result.fits ? '输入检查通过' : '输入超过预算，请减少文字或图片。'),
      )
    }
  } catch (cause) {
    if (!current.signal.aborted) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      tasks.finish(feedback, 'error', error.value)
    }
  } finally {
    if (!current.signal.aborted) busy.value = false
  }
}
async function archiveDuplicate(id: string) {
  if (busy.value) return
  const library = app.activeLibrary,
    current = (controller = new AbortController())
  const feedback = beginFeedback('移入回收站', library)
  tasks.update(feedback, { phase: '处理资料' })
  busy.value = true
  error.value = ''
  try {
    await api.archiveDocument(library, id, current.signal)
    if (current.signal.aborted || library !== app.activeLibrary) return
    scope.value = scope.value.filter((value) => value !== id)
    if (organization.value)
      organization.value.pairs = organization.value.pairs?.filter(
        (pair) => pair.left !== id && pair.right !== id,
      )
    await app.refreshLibraries()
    await load()
    if (!current.signal.aborted) {
      notice.value = t('资料已移入暂存区，可随时恢复。')
      tasks.finish(feedback, 'success', notice.value)
    }
  } catch (cause) {
    if (!current.signal.aborted) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      tasks.finish(feedback, 'error', error.value)
    }
  } finally {
    if (!current.signal.aborted) busy.value = false
  }
}
async function restore(id: string) {
  if (busy.value) return
  const library = app.activeLibrary,
    current = (controller = new AbortController())
  const feedback = beginFeedback('恢复资料', library)
  tasks.update(feedback, { phase: '处理资料' })
  busy.value = true
  error.value = ''
  try {
    await api.restoreDocument(library, id, current.signal)
    if (current.signal.aborted || library !== app.activeLibrary) return
    organization.value = undefined
    await app.refreshLibraries()
    await load()
    if (!current.signal.aborted) {
      notice.value = t('资料已恢复，重新整理可更新结果。')
      tasks.finish(feedback, 'success', notice.value)
    }
  } catch (cause) {
    if (!current.signal.aborted) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      tasks.finish(feedback, 'error', error.value)
    }
  } finally {
    if (!current.signal.aborted) busy.value = false
  }
}
function cancel() {
  if (busy.value && feedbackId.value) {
    tasks.finish(
      feedbackId.value,
      'stopped',
      t('已停止等待，已提交的请求可能仍在处理。导入任务请刷新知识库核对结果。'),
    )
  }
  tasks.setActions(feedbackId.value, {})
  controller?.abort()
  busy.value = false
  notice.value = t('已停止等待；正在处理的本地任务会安全结束。')
}
function exportResults() {
  const data = organization.value
    ? {
        ...organization.value,
        ...(organization.value.pairs ? { pairs: duplicatePairs.value } : {}),
      }
    : searchResult.value
  if (!data) return
  const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }),
    ),
    link = document.createElement('a')
  link.href = url
  link.download = 'edge-results.json'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function fileName(id: string) {
  return organization.value?.documents.find((doc) => doc.id === id)?.filename ?? id
}
function time(value: number) {
  return `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`
}
watch(
  () => app.activeLibrary,
  () => {
    cancel()
    feedbackId.value = ''
    scope.value = []
    galleryPage.value = 1
    gallerySearch.value = ''
    galleryOpen.value = false
    searchResult.value = undefined
    organization.value = undefined
    budget.value = undefined
    notice.value = ''
    void load()
  },
)
watch(tab, () => {
  cancel()
  tasks.setActions(feedbackId.value, {})
  feedbackId.value = ''
  error.value = ''
  notice.value = ''
  searchResult.value = undefined
  organization.value = undefined
  budget.value = undefined
})
watch(
  () => [
    text.value,
    files.value.map((file) => `${file.name}:${file.size}`).join('|'),
    task.value,
    kind.value,
    topK.value,
    effectiveMatchMode.value,
    minScore.value,
    dimension.value,
    scope.value.join(','),
  ],
  () => {
    budget.value = undefined
    notice.value = ''
    searchResult.value = undefined
    if (operationTask.value?.state !== 'running') tasks.setActions(feedbackId.value, {})
  },
)
watch(
  () => [
    organizeTask.value,
    dimension.value,
    labels.value,
    clusters.value,
    classificationThreshold.value,
    threshold.value,
    scope.value.join(','),
  ],
  () => {
    organization.value = undefined
    searchResult.value = undefined
    if (operationTask.value?.state !== 'running') tasks.setActions(feedbackId.value, {})
  },
)
onMounted(load)
onBeforeUnmount(() => {
  cancel()
  tasks.setActions(feedbackId.value, {})
  loadGeneration++
  clearFiles()
})
</script>
<template>
  <section class="standard-page semantic-page">
    <header class="page-header">
      <div>
        <h1>{{ t('多模态工作台') }}</h1>
        <p class="page-subtitle">{{ t('找图片、定位音视频、整理本地素材') }}</p>
      </div>
      <button
        v-if="organization || searchResult"
        class="button secondary small"
        @click="exportResults"
      >
        <Download :size="15" />{{ t('导出结果') }}
      </button>
    </header>
    <div class="page-content semantic-content">
      <nav class="workflow-picker" :aria-label="t('选择工作任务')">
        <button
          v-for="option in workflows"
          :key="option.id"
          type="button"
          :disabled="busy"
          :aria-pressed="workflow === option.id"
          :class="{ active: workflow === option.id }"
          @click="setWorkflow(option.id)"
        >
          <span class="workflow-icon"><component :is="icons[option.id]" :size="19" /></span>
          <strong>{{ t(option.title) }}</strong
          ><small>{{ t(option.description) }}</small>
        </button>
      </nav>
      <div v-if="tab === 'search' && !matchingDocuments.length" class="workflow-empty-library">
        <FileText :size="17" /><span>{{
          t(
            workflow === 'images'
              ? '当前知识库还没有图片。'
              : workflow === 'media'
                ? '当前知识库还没有音视频。'
                : '当前知识库还没有资料。',
          )
        }}</span
        ><RouterLink to="/library">{{ t('导入资料') }} →</RouterLink>
      </div>
      <TaskFeedback v-if="operationTask" :task="operationTask" class="semantic-task-feedback" />
      <form class="semantic-form" @submit.prevent="run">
        <fieldset class="semantic-fields" :disabled="busy">
          <template v-if="tab !== 'organize'">
            <div class="workflow-heading">
              <span class="workflow-step">1</span>
              <div>
                <h2>{{ t(currentWorkflow.heading) }}</h2>
              </div>
            </div>
            <label v-if="tab === 'ingest'" class="semantic-field"
              >{{ t('素材名称')
              }}<input
                v-model="name"
                :aria-label="t('素材名称')"
                maxlength="255"
                :placeholder="t('例如：产品设计资料')"
            /></label>
            <textarea
              v-model="text"
              :aria-label="t('补充文字')"
              :placeholder="t(currentWorkflow.placeholder)"
              rows="2"
              maxlength="32000"
            ></textarea>
            <div
              class="workflow-dropzone"
              :class="{ dragging: dragOver }"
              @dragover.prevent="!busy && (dragOver = true)"
              @dragleave.prevent="dragOver = false"
              @drop.prevent="dropFiles"
            >
              <div v-if="!files.length" class="dropzone-intro">
                <component :is="icons[workflow]" :size="26" /><strong>{{
                  t(
                    workflow === 'images'
                      ? '拖入参考图片'
                      : workflow === 'media'
                        ? '拖入一段音视频'
                        : '把相关文件拖到这里',
                  )
                }}</strong
                ><span>{{ t('也可以只输入描述，不必添加文件') }}</span>
              </div>
              <div v-if="files.length" class="semantic-files">
                <div v-for="(file, index) in files" :key="index" class="semantic-file">
                  <img v-if="previews[index]" :src="previews[index]" :alt="file.name" /><span>{{
                    file.name
                  }}</span
                  ><small>{{ fileSize(file.size) }}</small>
                  <button
                    type="button"
                    class="icon-button"
                    :aria-label="`${t('移除素材')} ${file.name}`"
                    @click="removeFile(index)"
                  >
                    <X :size="14" />
                  </button>
                </div>
              </div>
              <button
                type="button"
                class="button secondary small"
                :disabled="busy"
                @click="input?.click()"
              >
                <ImagePlus :size="16" />{{
                  t(
                    workflow === 'images'
                      ? '选择参考图片'
                      : workflow === 'media'
                        ? '选择音视频'
                        : '选择文件',
                  )
                }}</button
              ><button v-if="files.length" type="button" class="text-button" @click="clearFiles">
                {{ t('清空参考素材') }}</button
              ><input
                ref="input"
                type="file"
                class="hidden"
                multiple
                :accept="currentWorkflow.accept"
                @change="choose"
              />
            </div>
            <details
              v-if="workflow === 'images' && matchingDocuments.length"
              class="library-reference"
              :open="galleryOpen"
              @toggle="galleryOpen = ($event.target as HTMLDetailsElement).open"
            >
              <summary>{{ t('从知识库选择参考图') }} · {{ matchingDocuments.length }}</summary>
              <input
                v-if="galleryOpen"
                v-model="gallerySearch"
                :aria-label="t('查找参考图片')"
                :placeholder="t('按图片名称查找…')"
              />
              <div v-if="galleryOpen" class="library-reference-grid">
                <div v-for="doc in galleryVisible" :key="doc.id">
                  <ImagePreview
                    :library="app.activeLibrary"
                    :document="doc.id"
                    :filename="doc.filename"
                  /><strong>{{ doc.filename }}</strong
                  ><button type="button" class="text-button" @click="useLibraryImage(doc)">
                    {{ t('用这张图查找') }}
                  </button>
                </div>
              </div>
              <div v-if="galleryOpen && galleryPages > 1" class="reference-pagination">
                <button
                  type="button"
                  class="text-button"
                  :disabled="galleryPage === 1"
                  @click="galleryPage--"
                >
                  {{ t('上一页') }}</button
                ><span>{{ galleryPage }} / {{ galleryPages }}</span
                ><button
                  type="button"
                  class="text-button"
                  :disabled="galleryPage === galleryPages"
                  @click="galleryPage++"
                >
                  {{ t('下一页') }}
                </button>
              </div>
            </details>
            <p v-if="issue" class="inline-error">{{ t(issue) }}</p>
            <p class="semantic-footnote">
              {{
                t(
                  '文件只在本机处理。文档和图片每份 20 MB，音视频每份 200 MB；最多组合 12 份文件和一段音视频。',
                )
              }}
            </p>
          </template>
          <template v-else>
            <div class="workflow-heading">
              <span class="workflow-step">1</span>
              <div>
                <h2>{{ t(currentWorkflow.heading) }}</h2>
                <p class="semantic-description">
                  {{ t('先选择任务，再确认要处理的资料。原文件保留。') }}
                </p>
              </div>
            </div>
            <div class="organize-choice" :aria-label="t('整理任务')">
              <button
                v-for="option in [
                  { id: 'classification', label: '建议分类' },
                  { id: 'clustering', label: '按内容分组' },
                  { id: 'similarity', label: '找重复资料' },
                ] as const"
                :key="option.id"
                type="button"
                :aria-pressed="organizeTask === option.id"
                @click="organizeTask = option.id"
              >
                {{ t(option.label) }}
              </button>
            </div>
            <div v-if="organizeTask === 'classification'" class="semantic-field">
              <label for="category-label">{{ t('你希望分成哪些类别？') }}</label>
              <div class="category-tags">
                <span v-for="label in labelItems" :key="label"
                  >{{ label
                  }}<button
                    type="button"
                    :aria-label="`${t('移除类别')} ${label}`"
                    @click="removeLabel(label)"
                  >
                    <X :size="12" /></button
                ></span>
              </div>
              <div class="category-input">
                <input
                  id="category-label"
                  v-model="labelDraft"
                  :placeholder="t('输入一个类别，例如会议记录')"
                  @keydown.enter.prevent="addLabel"
                /><button
                  type="button"
                  class="button secondary small"
                  :disabled="!labelDraft.trim() || labelItems.length >= 30"
                  @click="addLabel"
                >
                  {{ t('添加类别') }}
                </button>
              </div>
              <p class="semantic-footnote">
                {{ t('生成分类建议，可导出结果；不会修改文件或自动写入标签。') }}
              </p>
            </div>
            <label v-if="organizeTask === 'clustering'" class="semantic-field"
              >{{ t('期望分组数')
              }}<input
                v-model.number="clusters"
                :aria-label="t('期望分组数')"
                type="number"
                min="1"
                max="20"
                required
            /></label>
          </template>
          <label v-if="tab === 'organize' && organizeTask === 'similarity'" class="duplicate-policy"
            ><input v-model="sameKindOnly" type="checkbox" />{{ t('只比较同类型资料')
            }}<small>{{ t('避免把内容相关的图片、视频和录音混作重复候选') }}</small></label
          >
          <details
            class="workflow-advanced"
            :open="advanced"
            @toggle="advanced = ($event.target as HTMLDetailsElement).open"
          >
            <summary>
              {{ t('高级选项') }}<span>{{ t('默认设置即可开始') }}</span>
            </summary>
            <label v-if="tab === 'organize' && organizeTask === 'similarity'" class="semantic-field"
              >{{ t('相似程度门槛')
              }}<input
                v-model.number="threshold"
                :aria-label="t('相似程度门槛')"
                type="number"
                min="-1"
                max="1"
                step="0.01"
                required
            /></label>
            <label
              v-if="tab === 'organize' && organizeTask === 'classification'"
              class="semantic-field"
              >{{ t('分类最低相似度')
              }}<input
                v-model.number="classificationThreshold"
                :aria-label="t('分类最低相似度')"
                type="number"
                min="-1"
                max="1"
                step="0.01"
                required
            /></label>
            <div v-if="tab !== 'ingest'" class="semantic-options">
              <label class="semantic-field"
                >{{ t('检索精度')
                }}<select v-model.number="dimension" :aria-label="t('检索精度')">
                  <option v-for="dim in [768, 512, 256, 128]" :key="dim" :value="dim">
                    {{
                      t(dim === 768 ? '完整' : dim === 512 ? '均衡' : dim === 256 ? '轻量' : '精简')
                    }}
                    · {{ dim }}
                  </option>
                </select></label
              >
              <template v-if="tab === 'search'"
                ><label class="semantic-field"
                  >{{ t('匹配方式')
                  }}<select v-model="matchMode" :aria-label="t('匹配方式')">
                    <option value="auto">{{ t('智能筛选') }}</option>
                    <option v-if="canMatchImageText" value="image_text">
                      {{ t('图片内文字') }}
                    </option>
                    <option value="broad">{{ t('扩大搜索') }}</option>
                  </select></label
                ><label class="semantic-field"
                  >{{ t('视觉与语义匹配门槛')
                  }}<input
                    v-model.number="minScore"
                    :aria-label="t('视觉与语义匹配门槛')"
                    type="number"
                    min="-1"
                    max="1"
                    step="0.01"
                    required /></label
                ><label class="semantic-field"
                  >{{ t('结果类型')
                  }}<select v-model="kind" :aria-label="t('结果类型')">
                    <option value="">
                      {{ t(workflow === 'media' ? '全部音视频' : '全部资料') }}
                    </option>
                    <option value="image">{{ t('图片') }}</option>
                    <option value="document">{{ t('文档') }}</option>
                    <option value="audio">{{ t('音频') }}</option>
                    <option value="video">{{ t('视频') }}</option>
                    <option value="bundle">{{ t('联合素材') }}</option>
                  </select></label
                ><label class="semantic-field"
                  >{{ t('检索任务')
                  }}<select v-model="task" :aria-label="t('检索任务')">
                    <option value="search">{{ t('通用检索') }}</option>
                    <option value="code">{{ t('代码检索') }}</option>
                    <option value="qa">{{ t('问题检索') }}</option>
                    <option value="fact">{{ t('事实证据检索') }}</option>
                  </select></label
                ><label class="semantic-field"
                  >{{ t('最多显示')
                  }}<input
                    v-model.number="topK"
                    :aria-label="t('结果数量')"
                    type="number"
                    min="1"
                    max="50"
                    required /></label
              ></template>
            </div>
            <p v-if="tab === 'search'" class="semantic-footnote">
              {{
                t(
                  '智能筛选优先匹配明确的图片文字，并筛掉较弱的语义候选。扩大搜索可查看更多相近结果；门槛只作用于视觉与语义匹配。',
                )
              }}
            </p>
            <button
              v-if="tab !== 'organize'"
              type="button"
              class="text-button"
              :disabled="!valid || !app.health"
              @click="previewBudget"
            >
              {{ t('检查输入容量') }}
            </button>
          </details>
          <details
            v-if="tab !== 'ingest'"
            class="semantic-scope"
            :open="tab === 'organize' && documents.length > 200 && !scope.length"
          >
            <summary>
              {{ t('选择资料范围') }} ·
              {{ scope.length ? t('已限定资料') : t('当前知识库全部资料') }}
            </summary>
            <div class="scope-tools">
              <input
                v-model="scopeSearch"
                :aria-label="t('筛选资料范围')"
                :placeholder="t('按名称筛选资料…')"
              /><button type="button" class="text-button" @click="selectVisibleScope">
                {{ t('选择筛选结果') }}</button
              ><button v-if="scope.length" type="button" class="text-button" @click="scope = []">
                {{ t('取消选择') }} · {{ scope.length }}
              </button>
            </div>
            <div class="semantic-scope-list">
              <label v-for="doc in scopeDocuments" :key="doc.id"
                ><input v-model="scope" type="checkbox" :value="doc.id" /><span>{{
                  doc.filename
                }}</span></label
              >
              <p v-if="!documents.length">{{ t('请先导入资料。') }}</p>
            </div>
          </details>
        </fieldset>
        <p v-if="tab === 'organize' && effectiveCount > 200" class="inline-error">
          {{ t('一次最多整理 200 份资料，请先选择资料范围。') }}
        </p>
        <div class="semantic-run">
          <span><ShieldCheck :size="14" />{{ t('本地处理 · 不调用云端模型') }}</span
          ><button
            v-if="busy && operationTask?.state !== 'running'"
            type="button"
            class="button secondary"
            @click="cancel"
          >
            {{ t('停止等待') }}</button
          ><button
            v-else-if="!busy"
            class="button primary"
            :disabled="!app.health || (tab === 'organize' ? !canOrganize : !valid)"
          >
            <Search v-if="tab === 'search'" :size="16" /><Upload
              v-else-if="tab === 'ingest'"
              :size="16"
            /><Shapes v-else :size="16" />{{
              t(
                tab === 'organize'
                  ? organizeTask === 'classification'
                    ? '生成分类建议'
                    : organizeTask === 'clustering'
                      ? '生成内容分组'
                      : '查找重复资料'
                  : currentWorkflow.action,
              )
            }}
          </button>
        </div>
      </form>
      <p v-if="error && operationTask?.detail !== error" class="inline-error" role="alert">
        {{ error }}
      </p>
      <p v-if="notice && operationTask?.detail !== notice" class="semantic-status" role="status">
        {{ notice }}
      </p>
      <details
        v-if="budget"
        class="semantic-budget"
        :open="budget.fits === false || advanced"
        :class="{ overflow: budget.fits === false }"
      >
        <summary>{{ t(budget.fits ? '输入检查通过' : '输入需要缩减') }}</summary>
        <div>
          <strong>{{ t('上下文预算') }}</strong
          ><span
            >{{ budget.max_tokens }} / {{ budget.limit }} tokens · {{ budget.segments }}
            {{ t('个片段') }}</span
          >
        </div>
        <p v-if="budget.fits === false" class="semantic-footnote">
          {{ t('输入超过预算，请减少文字或图片。') }}
        </p>
        <meter :value="budget.max_tokens" :max="budget.limit"></meter
        ><small
          >{{ t('显示单段最大预算，包含文字、视觉、音频与格式预留；实际输入长度在推理前再次校验。')
          }}<template v-if="searchResult?.aggregation === 'mean_of_segments'">{{
            t('长查询分段编码后取归一化均值；不会把超长素材伪装成单段联合输入。')
          }}</template></small
        >
      </details>
      <section v-if="searchResult" ref="resultSection" class="semantic-results">
        <h2>{{ t('检索结果') }} · {{ searchResult.sources.length }}</h2>
        <p v-if="searchResult.relevance" class="semantic-footnote">
          {{
            t(
              searchResult.relevance.strategy === 'image_text'
                ? '按图片内文字匹配'
                : searchResult.relevance.strategy === 'broad'
                  ? '已扩大搜索范围'
                  : '已筛选相关候选',
            )
          }}
          · {{ t('已过滤') }} {{ searchResult.relevance.filtered_count }}
          {{ t('个较弱或不匹配的候选') }}
        </p>
        <p class="semantic-footnote">
          {{ t('向量分数不是命中概率；图片文字匹配以本地 OCR 为依据。') }}
        </p>
        <p v-if="!searchResult.sources.length" class="semantic-description">
          {{ t('没有找到符合当前匹配条件的结果。可以换个描述，或在高级选项中扩大搜索。') }}
        </p>
        <div class="workflow-result-grid">
          <article
            v-for="source in searchResult.sources"
            :key="`${source.document_id}:${source.index}`"
            class="semantic-result"
            :class="{ 'image-result': source.kind === 'image' }"
          >
            <div class="semantic-result-heading">
              <strong>{{ source.filename }}</strong
              ><span>{{ t('向量相似度') }} {{ source.score.toFixed(2) }}</span>
            </div>
            <small
              >{{ source.section
              }}<template v-if="source.end">
                · {{ time(source.start ?? 0) }}–{{ time(source.end) }}</template
              ></small
            ><ImagePreview
              v-if="source.kind === 'image'"
              :library="app.activeLibrary"
              :document="source.document_id"
              :filename="source.filename"
            /><MediaPreview
              v-if="['audio', 'video', 'bundle'].includes(source.kind ?? '')"
              :library="app.activeLibrary"
              :document="source.document_id"
              :start="source.start"
            />
            <details v-if="source.text" class="result-excerpt">
              <summary>{{ t('查看匹配片段') }}</summary>
              <p>{{ source.text }}</p>
            </details>
            <p v-else class="semantic-footnote">
              {{ t('此结果来自媒体语义向量；可播放或查看原件，不代表文字转录。') }}
            </p>
          </article>
        </div>
      </section>
      <section v-if="organization" ref="resultSection" class="semantic-results">
        <h2>{{ t('整理结果') }}</h2>
        <div
          v-for="row in organization.assignments ?? []"
          :key="row.document_id"
          class="organization-row"
        >
          <strong>{{ fileName(row.document_id) }}</strong
          ><span class="organization-label">{{ row.label }}</span
          ><small v-if="advanced">{{ row.scores[0]?.score.toFixed(4) }}</small>
        </div>
        <article
          v-for="(group, index) in organization.groups ?? []"
          :key="index"
          class="semantic-result"
        >
          <strong>{{ t('分组') }} {{ index + 1 }} · {{ group.length }}</strong>
          <ul>
            <li v-for="id in group" :key="id">{{ fileName(id) }}</li>
          </ul>
        </article>
        <article
          v-for="pair in duplicatePairs"
          :key="`${pair.left}:${pair.right}`"
          class="organization-pair"
        >
          <div class="duplicate-compare">
            <div v-for="id in [pair.left, pair.right]" :key="id">
              <ImagePreview
                v-if="organization.documents.find((doc) => doc.id === id)?.kind === 'image'"
                :library="app.activeLibrary"
                :document="id"
                :filename="fileName(id)"
              /><FileText v-else :size="25" /><strong>{{ fileName(id) }}</strong
              ><button
                type="button"
                class="text-button danger"
                :disabled="busy"
                @click="archiveDuplicate(id)"
              >
                {{ t('移入回收站') }}
              </button>
            </div>
          </div>
          <div class="pair-actions">
            <strong
              >{{ pair.score.toFixed(4)
              }}<small>{{ t(pair.exact ? '索引内容相同' : '语义相似') }}</small></strong
            >
          </div>
        </article>
        <p v-if="organization.pairs && duplicatePairs.length === 0" class="semantic-description">
          {{ t('当前阈值下没有相似候选。') }}
        </p>
        <p class="semantic-footnote">
          {{ t('这些是整理建议。相似分数不是正确率；移入回收站只移出索引，原文件保留。') }}
        </p>
      </section>
      <section v-if="tab === 'organize' && archived.length" class="semantic-results">
        <h2>{{ t('重复资料暂存区') }} · {{ archived.length }}</h2>
        <p class="semantic-description">
          {{ t('暂存资料不参与检索，原件与索引快照仍在本机，可随时恢复。') }}
        </p>
        <div v-for="doc in archived" :key="doc.id" class="organization-row">
          <strong>{{ doc.filename }}</strong
          ><button class="button secondary small" :disabled="busy" @click="restore(doc.id)">
            {{ t('恢复资料') }}
          </button>
        </div>
      </section>
    </div>
  </section>
</template>
