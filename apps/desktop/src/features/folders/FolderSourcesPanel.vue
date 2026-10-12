<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import {
  FolderOpen,
  FolderPlus,
  RefreshCw,
  Pause,
  Play,
  Unplug,
  LoaderCircle,
  FileText,
  ChevronDown,
} from '@lucide/vue'
import { api } from '../../shared/api/client'
import { useAppStore } from '../../app/store'
import { useI18n } from '../../shared/i18n'
import type { FolderSource, FolderIndexedFile } from '../../shared/types/access'
import './folders.css'

const app = useAppStore()
const { t, preferences } = useI18n()
const emit = defineEmits<{ changed: [] }>()
const available = api.foldersAvailable()
const sources = ref<FolderSource[]>([])
const action = ref('')
const error = ref('')
const disconnecting = ref<FolderSource>()
const dialog = ref<HTMLDialogElement>()
const expanded = ref('')
const entries = ref<FolderIndexedFile[]>([])
const filesBusy = ref(false)
const filter = ref('')
const page = ref(0)
const filtered = computed(() =>
  entries.value.filter((e) => e.path.toLowerCase().includes(filter.value.toLowerCase())),
)
const visible = computed(() => filtered.value.slice(page.value * 50, (page.value + 1) * 50))
let generation = 0
let timer: ReturnType<typeof setInterval> | undefined
let polling = false
let lastLibraryRefresh = 0
const running = (source: FolderSource) => ['queued', 'scanning', 'syncing'].includes(source.state)
function status(source: FolderSource) {
  if (source.state === 'idle' && !source.lastSynced) return t('等待同步')
  return t(
    {
      idle: '已同步',
      queued: '等待同步',
      scanning: '扫描中',
      syncing: '同步中',
      paused: '已暂停',
      error: '需要处理',
      revoked: '授权已撤销',
    }[source.state],
  )
}
async function refresh() {
  if (!available || polling) return
  polling = true
  const current = generation
  try {
    const next = await api.folderSources(app.activeLibrary)
    if (current !== generation) return
    const changed = next.some((s) => {
      const old = sources.value.find((o) => o.id === s.id)
      return (
        !running(s) &&
        old &&
        (old.lastSynced !== s.lastSynced || old.completed !== s.completed || running(old))
      )
    })
    sources.value = next
    const progressChanged = next.some((s) => running(s) && s.completed > 0)
    if (changed || (progressChanged && Date.now() - lastLibraryRefresh > 10_000)) {
      lastLibraryRefresh = Date.now()
      emit('changed')
      if (changed && expanded.value) void loadFiles(expanded.value)
    }
  } catch (cause) {
    if (current === generation)
      error.value = cause instanceof Error ? cause.message : t('无法读取文件夹来源。')
  } finally {
    polling = false
  }
}
async function run(id: string, operation: () => Promise<unknown>) {
  if (action.value) return
  const current = generation
  action.value = id
  error.value = ''
  try {
    await operation()
    if (current === generation) await refresh()
  } catch (cause) {
    if (current === generation)
      error.value = cause instanceof Error ? cause.message : t('文件夹操作失败。')
  } finally {
    action.value = ''
  }
}
function chooseFolder() {
  void run('choose', () => api.folderChoose(app.activeLibrary))
}
function syncFolder(source: FolderSource) {
  void run(source.id, () => api.folderSync(source.id))
}
function toggleAutomatic(source: FolderSource) {
  void run(source.id, () =>
    source.automatic ? api.folderPause(source.id) : api.folderResume(source.id),
  )
}
async function loadFiles(id: string) {
  const current = generation
  filesBusy.value = true
  try {
    const result = await api.folderIndexedFiles(app.activeLibrary, id)
    if (current === generation && expanded.value === id) entries.value = result
  } catch (cause) {
    if (current === generation)
      error.value = cause instanceof Error ? cause.message : t('无法读取文件夹来源。')
  } finally {
    if (current === generation) filesBusy.value = false
  }
}
function toggleFiles(id: string) {
  expanded.value = expanded.value === id ? '' : id
  entries.value = []
  filter.value = ''
  page.value = 0
  if (expanded.value) void loadFiles(id)
}
function requestDisconnect(source: FolderSource) {
  disconnecting.value = source
  dialog.value?.showModal()
}
async function confirmDisconnect() {
  const source = disconnecting.value
  if (!source) return
  await run(source.id, () => api.folderDisconnect(source.id))
  dialog.value?.close()
  disconnecting.value = undefined
}
function syncTime(source: FolderSource) {
  if (!source.lastSynced) return t('尚未完成首次同步')
  return new Date(source.lastSynced).toLocaleString(preferences.values.language)
}
watch(filter, () => {
  page.value = 0
})
watch(
  () => app.activeLibrary,
  () => {
    generation++
    sources.value = []
    error.value = ''
    expanded.value = ''
    entries.value = []
    dialog.value?.close()
    disconnecting.value = undefined
    void refresh()
  },
)
onMounted(() => {
  void refresh()
  if (available) timer = setInterval(() => void refresh(), 1500)
})
onBeforeUnmount(() => {
  generation++
  clearInterval(timer)
})
</script>

<template>
  <section class="folder-sources" :aria-label="t('文件夹来源')">
    <div class="folder-sources-heading">
      <div class="folder-sources-title">
        <span class="folder-source-emblem"><FolderOpen :size="19" /></span>
        <div>
          <h3>{{ t('文件夹来源') }}</h3>
          <p>{{ t('连接笔记目录，新增与修改自动同步。') }}</p>
        </div>
      </div>
      <button
        class="button secondary small"
        :disabled="!available || !!action || !app.health"
        @click="chooseFolder"
      >
        <FolderPlus :size="15" />{{ t('添加文件夹') }}
      </button>
    </div>
    <div v-if="!sources.length" class="folder-sources-empty">
      <FolderOpen :size="22" />
      <div>
        <strong>{{ t(available ? '把笔记文件夹连接到这里' : '请在桌面应用中连接文件夹') }}</strong>
        <p>
          {{
            t(
              available
                ? '支持子目录中的文档、图片、音频与视频，无需逐个选择文件。'
                : '浏览器预览支持文件导入；文件夹持续同步需要桌面应用。',
            )
          }}
        </p>
      </div>
    </div>
    <article v-for="source in sources" :key="source.id" class="folder-source-card">
      <div class="folder-source-row">
        <FolderOpen :size="18" />
        <div class="folder-source-name">
          <strong>{{ source.name }}</strong
          ><small :title="source.path">{{ source.path }}</small>
        </div>
        <span class="folder-source-status" :class="source.state"
          ><LoaderCircle v-if="running(source)" class="spin" :size="12" />{{ status(source) }}</span
        >
      </div>
      <div v-if="running(source)" class="folder-source-progress">
        <span>{{ t('已处理') }} {{ source.completed }} / {{ source.total || '—' }}</span
        ><progress v-if="source.total" :value="source.completed" :max="source.total" />
      </div>
      <div class="folder-source-footer">
        <span
          >{{ source.indexed }} {{ t('个文件') }} ·
          {{ t(source.automatic ? '每分钟检查更新' : '自动同步已暂停') }} · {{ t('已跳过') }}
          {{ source.skipped }}</span
        ><span>{{ syncTime(source) }}</span>
      </div>
      <div class="folder-source-actions">
        <button
          class="text-button"
          :disabled="!!action || running(source) || source.state === 'revoked'"
          @click="syncFolder(source)"
        >
          <RefreshCw :size="13" />{{ t('立即同步') }}</button
        ><button
          v-if="source.state !== 'revoked'"
          class="text-button"
          :disabled="!!action"
          @click="toggleAutomatic(source)"
        >
          <Pause v-if="source.automatic" :size="13" /><Play v-else :size="13" />{{
            t(source.automatic ? '暂停同步' : '开启自动同步')
          }}</button
        ><button class="text-button" @click="toggleFiles(source.id)">
          <ChevronDown :size="13" />{{
            t(expanded === source.id ? '收起文件清单' : '查看文件清单')
          }}</button
        ><button
          class="text-button folder-source-disconnect"
          :disabled="!!action"
          @click="requestDisconnect(source)"
        >
          <Unplug :size="13" />{{ t('移除来源') }}
        </button>
      </div>
      <p v-if="source.message" class="folder-source-notice">{{ t(source.message) }}</p>
      <details v-if="source.failures.length" class="folder-source-failures">
        <summary>{{ t('查看失败文件') }} · {{ source.failures.length }}</summary>
        <p v-for="file in source.failures" :key="file.name">
          <strong>{{ file.name }}</strong> · {{ file.message }}
        </p>
      </details>
      <div v-if="expanded === source.id" class="folder-source-files">
        <input
          v-model="filter"
          :aria-label="t('搜索文件夹内的资料')"
          :placeholder="t('按相对路径搜索…')"
        />
        <p v-if="filesBusy">{{ t('正在读取资料…') }}</p>
        <p v-else-if="!filtered.length">{{ t('没有匹配的已索引文件') }}</p>
        <div v-for="file in visible" :key="file.path">
          <FileText :size="13" /><span>{{ file.path }}</span>
        </div>
        <nav v-if="filtered.length > 50" :aria-label="t('文件清单分页')">
          <button class="text-button" :disabled="page === 0" @click="page--">
            {{ t('上一页') }}</button
          ><span>{{ page + 1 }} / {{ Math.ceil(filtered.length / 50) }}</span
          ><button
            class="text-button"
            :disabled="(page + 1) * 50 >= filtered.length"
            @click="page++"
          >
            {{ t('下一页') }}
          </button>
        </nav>
      </div>
    </article>
    <p class="folder-source-policy">
      {{
        t('自动同步在桌面应用运行时进行。旧版本和已删除文件的索引移入回收站，原文件不会被修改。')
      }}
    </p>
    <p v-if="sources.length" class="folder-source-policy">
      {{ t('暂停或撤销后停止后续读取，已提交的单文件任务可能完成。目录访问可在本地权限中撤销。') }}
    </p>
    <div v-if="error" class="inline-error" role="alert">{{ error }}</div>
    <dialog ref="dialog" class="action-dialog" :aria-label="t('移除文件夹来源？')">
      <h2>{{ t('移除文件夹来源？') }}</h2>
      <p>{{ t('停止此文件夹的同步，已入库资料和原文件保留。目录授权可在本地权限中另行撤销。') }}</p>
      <div class="dialog-actions">
        <button class="button secondary" :disabled="!!action" @click="dialog?.close()">
          {{ t('取消') }}</button
        ><button class="button primary" :disabled="!!action" @click="confirmDisconnect">
          {{ t('移除来源') }}
        </button>
      </div>
    </dialog>
  </section>
</template>
