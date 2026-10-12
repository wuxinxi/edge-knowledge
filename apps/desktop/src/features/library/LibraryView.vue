<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  Check,
  FileText,
  FolderPlus,
  LoaderCircle,
  Trash2,
  RotateCcw,
  Upload,
  X,
  Film,
  AudioLines,
  Layers3,
} from '@lucide/vue'
import { useAppStore } from '../../app/store'
import { useI18n } from '../../shared/i18n'
import { api } from '../../shared/api/client'
import type { Document, OCRExtraction } from '../../shared/types/api'
import MediaPreview from '../../shared/components/MediaPreview.vue'
import ImagePreview from '../../shared/components/ImagePreview.vue'
import FolderSourcesPanel from '../folders/FolderSourcesPanel.vue'
import { toggleVisibleSelection } from './selection'
import './library.css'

const app = useAppStore()
const { t, preferences, libraryName } = useI18n()
const documents = ref<Document[]>([])
const filter = ref(''),
  kind = ref('all'),
  sort = ref('newest')
const visibleDocuments = computed(() =>
  documents.value
    .filter(
      (doc) =>
        doc.filename.toLowerCase().includes(filter.value.toLowerCase()) &&
        (kind.value === 'all' || doc.kind === kind.value),
    )
    .sort((a, b) =>
      sort.value === 'name'
        ? a.filename.localeCompare(b.filename)
        : sort.value === 'size'
          ? b.size - a.size
          : b.created_at.localeCompare(a.created_at),
    ),
)
const archived = ref<Document[]>([])
const selected = ref<string[]>([])
const page = ref(0)
const pagedDocuments = computed(() =>
  visibleDocuments.value.slice(page.value * 50, (page.value + 1) * 50),
)
const allSelected = computed(
  () =>
    !!visibleDocuments.value.length &&
    visibleDocuments.value.every((d) => selected.value.includes(d.id)),
)
const partialSelected = computed(
  () => !allSelected.value && visibleDocuments.value.some((d) => selected.value.includes(d.id)),
)
const bulkDialog = ref<HTMLDialogElement>()
const pendingArchive = ref<{
  library: string
  name: string
  ids: string[]
  all: boolean
  count: number
}>()
const lastArchive = ref<{ library: string; ids: string[]; count: number }>()
const actionNotice = ref('')
const archiveView = ref(false)
const restoring = ref('')
const input = ref<HTMLInputElement>()
const loading = ref(false)
const busy = ref(false)
const importing = ref('')
const deleting = ref('')
const error = ref('')
const results = ref<{ filename: string; message: string; success: boolean }[]>([])
const newLibraryName = ref('')
const creating = ref(false)
const dragOver = ref(false)
const totalSize = computed(() => documents.value.reduce((sum, doc) => sum + doc.size, 0))
let generation = 0
const ocrInput = ref<HTMLInputElement>()
const ocrBusy = ref(false)
const extraction = ref<OCRExtraction>()
const extractionPreview = ref('')
const extractionName = ref('')
const ocrError = ref('')
const copied = ref(false)
let ocrController: AbortController | undefined
function clearExtraction() {
  if (extractionPreview.value) URL.revokeObjectURL(extractionPreview.value)
  extractionPreview.value = ''
  extraction.value = undefined
  extractionName.value = ''
  copied.value = false
}
async function extractImageText(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file || ocrBusy.value) return
  clearExtraction()
  ocrError.value = ''
  ocrBusy.value = true
  const controller = (ocrController = new AbortController())
  try {
    if (file.size > 20 * 1024 * 1024) throw new Error(t('单张图片不能超过 20 MB。'))
    const result = await api.extractImageText(file, controller.signal)
    if (controller.signal.aborted) return
    extraction.value = result
    extractionName.value = file.name
    extractionPreview.value = URL.createObjectURL(file)
  } catch (cause) {
    if (!controller.signal.aborted)
      ocrError.value = cause instanceof Error ? cause.message : t('文字提取失败。')
  } finally {
    ocrBusy.value = false
  }
}
async function copyText() {
  try {
    await navigator.clipboard.writeText(extraction.value?.text ?? '')
    copied.value = true
  } catch {
    ocrError.value = t('无法复制，请直接选择下方文字复制。')
  }
}
onBeforeUnmount(() => {
  ocrController?.abort()
  clearExtraction()
})

async function load() {
  const current = ++generation
  loading.value = true
  error.value = ''
  try {
    const [items, trash] = await Promise.all([
      api.documents(app.activeLibrary),
      api.archived(app.activeLibrary),
    ])
    if (current === generation) {
      documents.value = items
      archived.value = trash
      selected.value = selected.value.filter((id) => items.some((item) => item.id === id))
      page.value = Math.min(
        page.value,
        Math.max(0, Math.ceil(visibleDocuments.value.length / 50) - 1),
      )
    }
  } catch (cause) {
    if (current === generation) error.value = String(cause instanceof Error ? cause.message : cause)
  } finally {
    if (current === generation) loading.value = false
  }
}
async function upload(files: FileList | File[]) {
  if (busy.value || !app.health) return
  if (app.capabilities?.embedding.ready === false) {
    error.value = t('本地检索模型尚未准备，请先完成模型下载。图片识字可以独立使用。')
    return
  }
  const library = app.activeLibrary
  busy.value = true
  results.value = []
  for (const file of Array.from(files)) {
    importing.value = file.name
    try {
      if (
        file.size >
        (/\.(wav|mp3|m4a|aac|flac|ogg|mp4|mov|mkv|webm)$/i.test(file.name) ? 200 : 20) * 1024 * 1024
      )
        throw new Error(t('文档和图片上限 20 MB，音视频上限 200 MB。'))
      if (
        !/\.(txt|md|pdf|docx|png|jpe?g|webp|wav|mp3|m4a|aac|flac|ogg|mp4|mov|mkv|webm)$/i.test(
          file.name,
        )
      )
        throw new Error(t('不支持此文件格式。'))
      const result = await api.ingest(library, file)
      results.value.push({
        filename: file.name,
        message: result.duplicate
          ? t('已存在，跳过重复导入')
          : result.document.kind === 'image'
            ? `${t('图片已索引')} · ${ocrLabel(result.document.ocr_status)}${result.document.ocr_message ? '：' + result.document.ocr_message : ''}`
            : preferences.values.language === 'en-US'
              ? `Imported ${result.document.chunks} excerpts`
              : `已导入 ${result.document.chunks} 个片段`,
        success: true,
      })
    } catch (cause) {
      results.value.push({
        filename: file.name,
        message: cause instanceof Error ? cause.message : t('导入失败'),
        success: false,
      })
    }
  }
  busy.value = false
  importing.value = ''
  try {
    await app.refreshLibraries()
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t('无法刷新知识库。')
  }
}
function selectFiles(event: Event) {
  const target = event.target as HTMLInputElement
  if (target.files) void upload(target.files)
  target.value = ''
}
async function refreshFromFolders() {
  try {
    await app.refreshLibraries()
    if (!busy.value) await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t('无法刷新知识库。')
  }
}
function toggleAll() {
  selected.value = toggleVisibleSelection(
    selected.value,
    visibleDocuments.value.map((d) => d.id),
  )
}
function requestArchive(all = false) {
  if (busy.value || loading.value) return
  const ids = [...selected.value]
  if (!all && !ids.length) return
  pendingArchive.value = {
    library: app.activeLibrary,
    name: app.currentLibrary?.name ?? t('我的知识库'),
    ids: all ? [] : ids,
    all,
    count: all ? documents.value.length : ids.length,
  }
  bulkDialog.value?.showModal()
}
async function confirmArchive() {
  const pending = pendingArchive.value
  if (!pending || busy.value) return
  busy.value = true
  error.value = ''
  actionNotice.value = ''
  try {
    if (pending.all) await api.pauseFolderSources(pending.library)
    const result = await api.archiveDocuments(pending.library, pending.ids, pending.all)
    if (app.activeLibrary === pending.library) {
      lastArchive.value = {
        library: pending.library,
        ids: result.document_ids,
        count: result.archived,
      }
      selected.value = []
      actionNotice.value =
        preferences.values.language === 'en-US'
          ? `Moved ${result.archived} files to Trash`
          : `已将 ${result.archived} 份资料移入回收站`
    }
    bulkDialog.value?.close()
    await app.refreshLibraries()
    await load()
  } catch (cause) {
    if (app.activeLibrary === pending.library)
      error.value = cause instanceof Error ? cause.message : t('批量移入失败。')
  } finally {
    busy.value = false
  }
}
async function undoArchive() {
  const previous = lastArchive.value
  if (!previous || busy.value || previous.library !== app.activeLibrary) return
  busy.value = true
  error.value = ''
  try {
    await api.restoreDocuments(previous.library, previous.ids)
    if (app.activeLibrary === previous.library) {
      lastArchive.value = undefined
      actionNotice.value = t('已恢复本次移入的资料。')
    }
    await app.refreshLibraries()
    await load()
  } catch (cause) {
    if (app.activeLibrary === previous.library)
      error.value = cause instanceof Error ? cause.message : t('恢复失败。')
  } finally {
    busy.value = false
  }
}
function drop(event: DragEvent) {
  dragOver.value = false
  if (event.dataTransfer?.files) void upload(event.dataTransfer.files)
}
async function remove(document: Document) {
  busy.value = true
  try {
    await api.archiveDocument(app.activeLibrary, document.id)
    await app.refreshLibraries()
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t('删除失败。')
  } finally {
    busy.value = false
    deleting.value = ''
  }
}
async function restore(document: Document) {
  if (busy.value) return
  busy.value = true
  restoring.value = document.id
  try {
    await api.restoreDocument(app.activeLibrary, document.id)
    await app.refreshLibraries()
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t('恢复失败。')
  } finally {
    busy.value = false
    restoring.value = ''
  }
}
async function createLibrary() {
  if (!newLibraryName.value.trim()) return
  busy.value = true
  try {
    const library = await api.createLibrary(newLibraryName.value.trim())
    await app.refreshLibraries()
    app.activeLibrary = library.id
    creating.value = false
    newLibraryName.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t('创建失败。')
  } finally {
    busy.value = false
  }
}
function formatSize(size: number) {
  return size < 1024 * 1024
    ? `${(size / 1024).toFixed(1)} KB`
    : `${(size / 1024 / 1024).toFixed(1)} MB`
}
function ocrLabel(status: string) {
  return (
    (
      {
        ready: t('文字已提取'),
        empty: t('没有识别到文字'),
        unavailable: t('本地 OCR 不可用'),
        error: t('文字提取失败'),
      } as Record<string, string>
    )[status] || t('图片已索引')
  )
}
onMounted(() => {
  if (app.health) void load()
})
watch([filter, kind, sort], () => {
  page.value = 0
})
watch(archiveView, () => {
  selected.value = []
})
watch(
  () => app.activeLibrary,
  () => {
    selected.value = []
    page.value = 0
    lastArchive.value = undefined
    actionNotice.value = ''
    bulkDialog.value?.close()
    pendingArchive.value = undefined
    documents.value = []
    archived.value = []
    deleting.value = ''
    results.value = []
    archiveView.value = false
    if (app.health) void load()
  },
)
</script>

<template>
  <section class="standard-page">
    <header class="page-header">
      <div>
        <h1>{{ t('我的知识库') }}</h1>
        <p class="page-subtitle">{{ t('收集、检索和管理你的本地资料') }}</p>
      </div>
      <button
        class="button secondary small"
        :disabled="busy || !app.health"
        @click="creating = !creating"
      >
        <FolderPlus :size="16" />{{ t('新建知识库') }}
      </button>
    </header>
    <div class="page-content">
      <form v-if="creating" class="inline-form" @submit.prevent="createLibrary">
        <input
          v-model="newLibraryName"
          :aria-label="t('新知识库名称')"
          :placeholder="t('为新知识库起个名字')"
          maxlength="60"
          autofocus
        /><button class="button primary" :disabled="busy || !newLibraryName.trim()">
          {{ t('创建') }}</button
        ><button
          type="button"
          class="icon-button"
          :aria-label="t('取消创建')"
          @click="creating = false"
        >
          <X :size="18" />
        </button>
      </form>
      <div class="section-intro">
        <div>
          <h2>{{ libraryName(app.activeLibrary, app.currentLibrary?.name ?? t('我的知识库')) }}</h2>
          <p>{{ t('把资料收集在这里，答案就有了依据。') }}</p>
        </div>
        <div class="library-stats">
          <div>
            <strong>{{ documents.length }}</strong
            ><span>{{ t('份资料') }}</span>
          </div>
          <div>
            <strong>{{ app.currentLibrary?.chunks ?? 0 }}</strong
            ><span>{{ t('个片段') }}</span>
          </div>
          <div>
            <strong>{{ formatSize(totalSize) }}</strong
            ><span>{{ t('原文大小') }}</span>
          </div>
        </div>
      </div>

      <FolderSourcesPanel @changed="refreshFromFolders" />

      <div
        class="upload-zone"
        :class="{ dragging: dragOver, 'is-busy': busy }"
        @dragover.prevent="dragOver = true"
        @dragleave.prevent="dragOver = false"
        @drop.prevent="drop"
      >
        <div class="upload-icon">
          <LoaderCircle v-if="busy" class="spin" :size="25" /><Upload v-else :size="25" />
        </div>
        <h3>
          {{
            importing
              ? preferences.values.language === 'en-US'
                ? `Processing ${importing}`
                : `正在处理 ${importing}`
              : t('拖入文档、图片、音频或视频')
          }}
        </h3>
        <p>
          {{
            importing
              ? t('模型加载与资料处理在本机进行，请稍候。')
              : t('文档和图片上限 20 MB；音视频上限 200 MB / 60 分钟')
          }}
        </p>
        <button class="button primary" :disabled="busy || !app.health" @click="input?.click()">
          <Upload :size="16" />{{ t('选择文件') }}</button
        ><input
          ref="input"
          class="hidden"
          type="file"
          accept=".txt,.md,.pdf,.docx,.png,.jpg,.jpeg,.webp,.wav,.mp3,.m4a,.aac,.flac,.ogg,.mp4,.mov,.mkv,.webm"
          multiple
          @change="selectFiles"
        /><span class="upload-footnote">{{ t('解析、切片与嵌入均在本地完成') }}</span>
      </div>

      <div v-if="app.capabilities?.embedding.ready === false" class="model-preparation-note">
        <span>{{ t('本地检索模型尚未准备，暂时无法入库。可以先使用下方的图片识字。') }}</span
        ><button class="text-button" @click="app.refreshCapabilities">
          {{ t('检查准备状态') }}
        </button>
      </div>
      <div v-if="error" role="alert" class="inline-error">{{ error }}</div>
      <div class="ocr-tool">
        <div>
          <strong>{{ t('提取图片文字') }}</strong>
          <p>{{ t('在本机读取截图和票据，不需要等待嵌入模型。') }}</p>
        </div>
        <button
          class="button secondary small"
          :disabled="ocrBusy || !app.health || !app.capabilities?.ocr.available"
          @click="ocrInput?.click()"
        >
          <LoaderCircle v-if="ocrBusy" class="spin" :size="16" />{{
            ocrBusy ? t('正在提取…') : t('选择图片识字')
          }}</button
        ><input
          ref="ocrInput"
          class="hidden"
          type="file"
          accept=".png,.jpg,.jpeg,.webp"
          @change="extractImageText"
        />
      </div>
      <div v-if="ocrError" class="inline-error" role="alert">{{ ocrError }}</div>
      <section v-if="extraction" class="ocr-extraction">
        <div class="ocr-extraction-header">
          <strong>{{ extractionName }} · {{ ocrLabel(extraction.status) }}</strong
          ><button
            class="icon-button"
            type="button"
            :aria-label="t('关闭识字结果')"
            @click="clearExtraction"
          >
            <X :size="16" />
          </button>
        </div>
        <div class="ocr-extraction-body">
          <img :src="extractionPreview" :alt="extractionName" />
          <div>
            <textarea
              v-if="extraction.text"
              :value="extraction.text"
              rows="6"
              :aria-label="t('图片识别文字')"
              readonly
            ></textarea>
            <p v-else>
              {{ extraction.message || t('没有识别到可用文字。照片可通过视觉模型进一步解读。') }}
            </p>
            <button v-if="extraction.text" class="text-button" @click="copyText">
              {{ copied ? t('已复制') : t('复制文字') }}
            </button>
          </div>
        </div>
      </section>
      <div v-if="results.length" class="import-results">
        <div v-for="(result, i) in results" :key="i" :class="{ failed: !result.success }">
          <Check v-if="result.success" :size="16" /><X v-else :size="16" /><strong>{{
            result.filename
          }}</strong
          ><span>{{ result.message }}</span>
        </div>
      </div>
      <div class="table-heading">
        <h3>
          <button
            type="button"
            class="library-view-tab"
            :class="{ active: !archiveView }"
            :aria-pressed="!archiveView"
            @click="archiveView = false"
          >
            {{ t('已导入资料') }}<span>{{ documents.length }}</span></button
          ><button
            type="button"
            class="library-view-tab"
            :class="{ active: archiveView }"
            :aria-pressed="archiveView"
            @click="archiveView = true"
          >
            <Trash2 :size="14" />{{ t('回收站与暂存') }}<span>{{ archived.length }}</span>
          </button>
        </h3>
        <button class="text-button" :disabled="busy || !app.health" @click="load">
          {{ t('刷新列表') }}
        </button>
      </div>
      <div v-if="!archiveView" class="library-filters">
        <input
          v-model="filter"
          :aria-label="t('搜索资料')"
          :placeholder="t('按名称搜索资料…')"
        /><select v-model="kind" :aria-label="t('资料类型')">
          <option value="all">{{ t('全部资料') }}</option>
          <option value="document">{{ t('文档') }}</option>
          <option value="image">{{ t('图片') }}</option>
          <option value="audio">{{ t('音频') }}</option>
          <option value="video">{{ t('视频') }}</option>
          <option value="bundle">{{ t('联合素材') }}</option></select
        ><select v-model="sort" :aria-label="t('排序方式')">
          <option value="newest">{{ t('最近导入') }}</option>
          <option value="name">{{ t('名称排序') }}</option>
          <option value="size">{{ t('大小排序') }}</option>
        </select>
      </div>
      <div v-if="!archiveView && documents.length" class="library-bulk-bar">
        <label
          ><input
            type="checkbox"
            :checked="allSelected"
            :indeterminate="partialSelected"
            :disabled="busy || loading"
            @change="toggleAll"
          />{{ t('全选筛选结果') }} <span>{{ visibleDocuments.length }}</span></label
        >
        <span class="library-selected-count">{{ t('已选择') }} {{ selected.length }}</span>
        <button v-if="selected.length" class="text-button" :disabled="busy" @click="selected = []">
          {{ t('取消选择') }}
        </button>
        <div>
          <button
            class="button secondary small"
            :disabled="!selected.length || busy || loading"
            @click="requestArchive(false)"
          >
            <Trash2 :size="14" />{{ t('删除所选') }}</button
          ><button
            class="button secondary small danger"
            :disabled="busy || loading || !app.health"
            @click="requestArchive(true)"
          >
            {{ t('清空全部资料') }}
          </button>
        </div>
      </div>
      <div v-if="actionNotice" role="status" class="library-action-notice">
        <Check :size="15" /><span>{{ actionNotice }}</span
        ><button
          v-if="lastArchive?.ids.length"
          class="text-button"
          :disabled="busy"
          @click="undoArchive"
        >
          {{ t('撤销本次操作') }}
        </button>
      </div>
      <div v-if="loading" class="empty-state">
        <LoaderCircle class="spin" :size="22" />{{ t('正在读取资料…') }}
      </div>
      <template v-else-if="archiveView">
        <p class="settings-note">
          {{ t('这里的资料不参与检索，恢复后重新可用。原文件不受影响。') }}
        </p>
        <div v-if="!archived.length" class="empty-state">
          <Trash2 :size="26" /><strong>{{ t('回收站是空的') }}</strong>
        </div>
        <div v-else class="library-archive-list">
          <article v-for="item in archived" :key="item.id">
            <span class="file-icon"><FileText :size="19" /></span>
            <div>
              <strong>{{ item.filename }}</strong
              ><small>{{ formatSize(item.size) }} · {{ item.chunks }} {{ t('个片段') }}</small>
            </div>
            <button class="button secondary small" :disabled="busy" @click="restore(item)">
              <LoaderCircle v-if="restoring === item.id" class="spin" :size="15" /><RotateCcw
                v-else
                :size="15"
              />{{ t('恢复资料') }}
            </button>
          </article>
        </div>
      </template>
      <div v-else-if="!documents.length" class="empty-state">
        <FileText :size="28" /><strong>{{ t('这里还没有资料') }}</strong>
        <p>{{ t('导入文档或图片后，可以在本地助手中查找和引用。') }}</p>
      </div>
      <div v-else-if="!visibleDocuments.length" class="empty-state">
        <FileText :size="26" /><strong>{{ t('没有匹配的资料') }}</strong>
      </div>
      <div v-else class="document-table">
        <div class="document-table-head">
          <span>{{ t('资料名称') }}</span
          ><span>{{ t('片段') }}</span
          ><span>{{ t('导入时间') }}</span
          ><span></span>
        </div>
        <div
          v-for="document in pagedDocuments"
          :key="document.id"
          class="document-row"
          :class="{ selected: selected.includes(document.id) }"
        >
          <div class="document-name">
            <input
              v-model="selected"
              class="document-checkbox"
              type="checkbox"
              :value="document.id"
              :disabled="busy"
              :aria-label="t('选择资料') + ' ' + document.filename"
            />
            <ImagePreview
              v-if="document.kind === 'image'"
              :library="app.activeLibrary"
              :document="document.id"
              :filename="document.filename"
              compact
            />
            <span v-else class="file-icon"
              ><component
                :is="
                  document.kind === 'video'
                    ? Film
                    : document.kind === 'audio'
                      ? AudioLines
                      : document.kind === 'bundle'
                        ? Layers3
                        : FileText
                "
                :size="20"
            /></span>
            <div>
              <strong>{{ document.filename }}</strong
              ><span
                >{{ formatSize(document.size)
                }}<template v-if="document.kind === 'image'">
                  · {{ document.width }} × {{ document.height }} ·
                  {{ ocrLabel(document.ocr_status) }}</template
                ></span
              >
              <span v-if="document.duration"
                >{{ document.duration.toFixed(1) }} {{ t('秒') }} ·
                {{ t(document.kind === 'audio' ? '音频' : '视频') }}</span
              >
              <MediaPreview
                v-if="['audio', 'video', 'bundle'].includes(document.kind)"
                :library="app.activeLibrary"
                :document="document.id"
              />
            </div>
          </div>
          <span class="chunk-count">{{ document.chunks }}</span
          ><span class="document-date">{{
            new Date(document.created_at).toLocaleDateString(preferences.values.language)
          }}</span>
          <div class="document-actions">
            <template v-if="deleting === document.id"
              ><button class="text-button danger" :disabled="busy" @click="remove(document)">
                {{ t('确认移入') }}</button
              ><button class="icon-button" :aria-label="t('取消移入')" @click="deleting = ''">
                <X :size="16" /></button></template
            ><button
              v-else
              class="icon-button danger"
              :disabled="busy"
              :aria-label="`${t('移入回收站')} ${document.filename}`"
              @click="deleting = document.id"
            >
              <Trash2 :size="16" />
            </button>
          </div>
        </div>
      </div>
      <nav
        v-if="!archiveView && visibleDocuments.length > 50"
        class="library-pagination"
        :aria-label="t('资料列表分页')"
      >
        <span>{{ t('共') }} {{ visibleDocuments.length }} {{ t('份资料') }}</span
        ><button class="button secondary small" :disabled="page === 0" @click="page--">
          {{ t('上一页') }}</button
        ><span>{{ page + 1 }} / {{ Math.ceil(visibleDocuments.length / 50) }}</span
        ><button
          class="button secondary small"
          :disabled="(page + 1) * 50 >= visibleDocuments.length"
          @click="page++"
        >
          {{ t('下一页') }}
        </button>
      </nav>
    </div>
    <dialog
      ref="bulkDialog"
      class="action-dialog library-bulk-dialog"
      :aria-label="t(pendingArchive?.all ? '清空知识库资料？' : '删除所选资料？')"
    >
      <h2>{{ t(pendingArchive?.all ? '清空知识库资料？' : '删除所选资料？') }}</h2>
      <p class="library-bulk-scope">
        <strong>{{ pendingArchive?.name }}</strong> · {{ pendingArchive?.count }} {{ t('份资料') }}
      </p>
      <p>
        {{
          t(
            pendingArchive?.all
              ? '将此知识库全部资料移入回收站，并暂停文件夹同步。原文件、对话和其他知识库不受影响。'
              : '所选资料将移入回收站，可随时恢复。目录中的文件以后发生修改时仍会同步新版本。',
          )
        }}
      </p>
      <p v-if="pendingArchive?.all && (filter || kind !== 'all')" class="library-bulk-warning">
        {{ t('清空全部不受当前搜索与类型筛选限制。') }}
      </p>
      <div class="dialog-actions">
        <button class="button secondary" :disabled="busy" @click="bulkDialog?.close()">
          {{ t('取消') }}</button
        ><button class="button primary destructive" :disabled="busy" @click="confirmArchive">
          <LoaderCircle v-if="busy" class="spin" :size="14" />{{
            t(busy ? '正在处理…' : '确认移入回收站')
          }}
        </button>
      </div>
    </dialog>
  </section>
</template>
