<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import {
  ShieldCheck,
  FolderOpen,
  FilePlus2,
  ScanSearch,
  X,
  Check,
  HardDrive,
  LockKeyhole,
  LoaderCircle,
} from '@lucide/vue'
import { api } from '../../shared/api/client'
import { useAppStore } from '../../app/store'
import { useI18n } from '../../shared/i18n'
import type { AccessGrant, AccessScan, AccessImport } from '../../shared/types/access'
import './access.css'
const { t } = useI18n(),
  app = useAppStore()
const available = api.desktopAvailable()
const revoking = ref('')
let generation = 0
onBeforeUnmount(() => {
  generation++
})
watch(
  () => app.activeLibrary,
  () => {
    generation++
    result.value = undefined
    selected.value = []
  },
)
const grants = ref<AccessGrant[]>([]),
  busy = ref(false),
  error = ref('')
const active = ref(''),
  scan = ref<AccessScan>(),
  selected = ref<string[]>([]),
  result = ref<AccessImport>()
const total = computed(
  () =>
    scan.value?.files
      .filter((file) => selected.value.includes(file.id))
      .reduce((sum, file) => sum + file.size, 0) ?? 0,
)
async function run(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await action()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t('无法访问此位置，请检查系统权限。')
  } finally {
    busy.value = false
  }
}
function choose(kind: 'file' | 'directory') {
  void run(async () => {
    grants.value = await api.accessChoose(kind)
  })
}
async function revoke(id: string) {
  if (revoking.value) return
  revoking.value = id
  error.value = ''
  try {
    await api.accessRevoke(id)
    grants.value = await api.accessList()
    if (active.value === id) {
      generation++
      active.value = ''
      scan.value = undefined
      selected.value = []
      result.value = undefined
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t('无法访问此位置，请检查系统权限。')
  } finally {
    revoking.value = ''
  }
}
function preview(id: string) {
  void run(async () => {
    active.value = id
    scan.value = undefined
    result.value = undefined
    selected.value = []
    const current = generation
    const scanned = await api.accessScan(id)
    if (current === generation) scan.value = scanned
  })
}
function importFiles() {
  void run(async () => {
    const library = app.activeLibrary
    const current = generation
    const imported = await api.accessImport(active.value, selected.value, library)
    if (current === generation) result.value = imported
    selected.value = []
    await app.refreshLibraries()
  })
}
onMounted(() => {
  if (available)
    void run(async () => {
      grants.value = await api.accessList()
    })
})
</script>
<template>
  <section class="settings-card access-card">
    <div class="settings-card-heading">
      <span class="settings-icon"><ShieldCheck :size="20" /></span>
      <div>
        <h2>{{ t('本地访问与隐私') }}</h2>
        <p>{{ t('由你决定助手可以读取哪些位置。') }}</p>
      </div>
    </div>
    <div class="privacy-overview">
      <LockKeyhole :size="22" />
      <div>
        <strong>{{ t('访问范围由你控制') }}</strong>
        <p>{{ t('只读访问 · 本地处理 · 可随时撤销') }}</p>
      </div>
      <span class="permission-badge">{{ t('最小权限') }}</span>
    </div>
    <div v-if="!available" class="access-browser-note">
      <HardDrive :size="20" />
      <div>
        <strong>{{ t('请在桌面应用中管理目录授权') }}</strong>
        <p>{{ t('浏览器仅能读取你主动选择的文件，无法持续访问本机目录。') }}</p>
        <RouterLink to="/library" class="text-button">{{ t('前往知识库选择文件') }} →</RouterLink>
      </div>
    </div>
    <div class="access-toolbar">
      <h3>
        {{ t('已授权位置') }} <span>{{ grants.length }}</span>
      </h3>
      <div>
        <button
          class="button secondary small"
          :disabled="!available || busy"
          @click="choose('file')"
        >
          <FilePlus2 :size="15" />{{ t('添加文件') }}</button
        ><button
          class="button primary small"
          :disabled="!available || busy"
          @click="choose('directory')"
        >
          <FolderOpen :size="15" />{{ t('授权目录') }}
        </button>
      </div>
    </div>
    <div v-if="available && !grants.length" class="access-empty">
      <FolderOpen :size="28" /><strong>{{ t('尚未授权任何位置') }}</strong>
      <p>{{ t('选择工作目录后，先预览资料，再决定导入哪些文件。') }}</p>
    </div>
    <article v-for="grant in grants" :key="grant.id" class="access-location">
      <span class="access-folder-icon"><FolderOpen :size="20" /></span>
      <div>
        <strong>{{ grant.name }}</strong
        ><small>{{ grant.path }}</small
        ><span class="access-scope"
          >{{ t('只读授权') }} · {{ t(grant.kind === 'directory' ? '目录' : '文件') }}</span
        >
      </div>
      <div class="access-location-actions">
        <button class="button secondary small" :disabled="busy" @click="preview(grant.id)">
          <ScanSearch :size="14" />{{ t('扫描预览') }}</button
        ><button
          class="icon-button danger"
          :disabled="!!revoking"
          :aria-label="t('撤销授权') + ' ' + grant.name"
          @click="revoke(grant.id)"
        >
          <X :size="16" />
        </button>
      </div>
    </article>
    <div v-if="scan" class="access-preview">
      <div class="access-toolbar">
        <h3>{{ t('扫描结果') }} · {{ scan.files.length }}</h3>
        <label
          ><input
            type="checkbox"
            :disabled="busy || !scan.files.length"
            :checked="selected.length === scan.files.length && !!selected.length"
            @change="
              selected = ($event.target as HTMLInputElement).checked
                ? scan.files.map((file) => file.id)
                : []
            "
          />{{ t('全选') }}</label
        >
      </div>
      <p class="settings-note">
        {{ t('跳过隐藏文件、符号链接、不支持的格式和超限文件。扫描不会读取正文或修改原件。') }}
        {{ scan.limited ? t('已达到扫描上限，请选择更小的目录。') : '' }} {{ t('已跳过') }}
        {{ scan.skipped }}
      </p>
      <div class="access-files">
        <label v-for="file in scan.files" :key="file.id"
          ><input v-model="selected" type="checkbox" :value="file.id" :disabled="busy" /><span>{{
            file.name
          }}</span
          ><small>{{ (file.size / 1024).toFixed(1) }} KB</small></label
        >
      </div>
      <div class="access-import-footer">
        <small
          >{{ t('导入到') }} {{ app.currentLibrary?.name }} · {{ selected.length }}
          {{ t('份资料') }} · {{ (total / 1024 / 1024).toFixed(1) }} MB</small
        ><button
          class="button primary"
          :disabled="busy || !selected.length || total > 512 * 1024 ** 2"
          @click="importFiles"
        >
          <Check :size="16" />{{ t('导入所选资料') }}
        </button>
      </div>
    </div>
    <p v-if="busy" class="semantic-status" role="status">
      <LoaderCircle class="spin" :size="17" />{{ t('正在处理，请稍候…') }}
    </p>
    <div v-if="result" class="access-result" role="status">
      {{ t('导入完成') }} · {{ result.imported }} {{ t('新增') }} · {{ result.duplicates }}
      {{ t('重复') }} · {{ result.failed.length }} {{ t('失败') }}
      <p v-for="item in result.failed" :key="item.name">{{ item.name }}：{{ item.message }}</p>
    </div>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    <div class="permission-details">
      <h3>{{ t('权限边界') }}</h3>
      <p>
        {{ t('应用授权不等于 macOS 完全磁盘访问。受保护目录需要系统允许；访问失败时会明确提示。') }}
      </p>
      <p>{{ t('撤销授权停止后续读取，已入库副本仍保留，可在知识库中管理。') }}</p>
      <p>{{ t('麦克风、摄像头、屏幕录制和通知默认禁用。云端图片仍需每次提问单独授权。') }}</p>
    </div>
  </section>
</template>
