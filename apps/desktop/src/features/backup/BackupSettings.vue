<script setup lang="ts">
import { ref, onBeforeUnmount } from 'vue'
import { Download, FolderInput, ShieldCheck, LoaderCircle, Check, X } from '@lucide/vue'
import { api } from '../../shared/api/client'
import { useI18n } from '../../shared/i18n'
import { useChatStore } from '../chat/store'
import { useAppStore } from '../../app/store'
import { validatePreferences } from '../../shared/preferences/store'
import { portableFrontend, validateChatBackup, restoredChats } from './frontend'
import type { BackupInspection } from '../../shared/types/api'
const { t, preferences } = useI18n(),
  chat = useChatStore(),
  app = useAppStore()
const input = ref<HTMLInputElement>(),
  file = ref<File>(),
  inspected = ref<BackupInspection>()
const busy = ref(''),
  error = ref(''),
  notice = ref(''),
  restorePreferences = ref(false)
const restoreChats = ref(true)
let controller: AbortController | undefined
onBeforeUnmount(() => controller?.abort())
async function run(label: string, action: (signal: AbortSignal) => Promise<void>) {
  if (busy.value) return
  busy.value = label
  error.value = ''
  notice.value = ''
  const pending = (controller = new AbortController())
  try {
    await action(pending.signal)
  } catch (cause) {
    if (!pending.signal.aborted)
      error.value = cause instanceof Error ? cause.message : t('备份操作失败。')
  } finally {
    if (controller === pending) {
      controller = undefined
      busy.value = ''
    }
  }
}
function clearPreview() {
  inspected.value = undefined
  file.value = undefined
}
function exportBackup() {
  void run('正在创建备份…', async (signal) => {
    if (chat.busy) throw new Error(t('请等待当前对话完成后再创建备份。'))
    const data = await api.exportBackup(portableFrontend(chat.sessions, preferences.values), signal)
    if (signal.aborted) return
    const url = URL.createObjectURL(data),
      link = document.createElement('a')
    link.href = url
    link.download = `edge-assistant-${new Date().toISOString().slice(0, 10)}.edgebackup`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 10000)
    notice.value = t('备份已生成，请确认文件已保存到本机。')
  })
}
function choose(event: Event) {
  const target = event.target as HTMLInputElement,
    selected = target.files?.[0]
  target.value = ''
  file.value = undefined
  inspected.value = undefined
  if (!selected) return
  void run('正在校验备份…', async (signal) => {
    if (selected.size > 512 * 1024 * 1024) throw new Error(t('备份文件不能超过 512 MB。'))
    const result = await api.inspectBackup(selected, signal)
    validateChatBackup(result.frontend.chats)
    if (signal.aborted) return
    file.value = selected
    inspected.value = result
  })
}
function restore() {
  void run('正在恢复副本…', async (signal) => {
    if (!file.value || !inspected.value?.compatible) return
    if (chat.busy) throw new Error(t('请等待当前对话完成后再恢复备份。'))
    const result = await api.restoreBackup(file.value, signal)
    if (signal.aborted) return
    let localFailure = false
    try {
      if (restoreChats.value)
        await chat.importConversations(restoredChats(result.frontend.chats, result.mapping))
      if (restorePreferences.value && result.frontend.preferences)
        preferences.values = validatePreferences(result.frontend.preferences)
    } catch {
      localFailure = true
    }
    await app.refreshLibraries()
    if (result.libraries[0]) app.activeLibrary = result.libraries[0].id
    file.value = undefined
    inspected.value = undefined
    notice.value = localFailure
      ? t('资料副本已恢复，但对话保存失败。请保留备份文件并重试。')
      : t('已恢复为新知识库，原有资料与对话保留。')
  })
}
</script>
<template>
  <section class="settings-card backup-settings">
    <div class="settings-card-heading">
      <span class="settings-icon"><ShieldCheck :size="20" /></span>
      <div>
        <h2>{{ t('备份与恢复') }}</h2>
        <p>{{ t('把资料、媒体原件、索引和对话保存为本机备份。') }}</p>
      </div>
    </div>
    <div class="backup-info">
      <p>{{ t('不包含 API Key、模型权重或目录授权。恢复创建新副本，不覆盖已有知识库。') }}</p>
      <p>{{ t('备份包含资料正文和媒体，请存放在你信任的位置。文件未加密，单次最多 512 MB。') }}</p>
    </div>
    <div class="backup-actions">
      <button
        class="button primary"
        :disabled="!!busy || chat.busy || !app.health"
        @click="exportBackup"
      >
        <Download :size="16" />{{ t('创建本机备份') }}</button
      ><button
        class="button secondary"
        :disabled="!!busy || chat.busy || !app.health"
        @click="input?.click()"
      >
        <FolderInput :size="16" />{{ t('选择备份文件') }}</button
      ><input ref="input" type="file" class="hidden" accept=".edgebackup,.zip" @change="choose" />
    </div>
    <div v-if="inspected" class="backup-preview">
      <div class="backup-preview-heading">
        <strong>{{ file?.name }}</strong
        ><button
          class="icon-button"
          :disabled="!!busy"
          :aria-label="t('关闭备份预览')"
          @click="clearPreview"
        >
          <X :size="16" />
        </button>
      </div>
      <div class="backup-stats">
        <span>{{ inspected.libraries }} {{ t('个知识库') }}</span
        ><span>{{ inspected.documents }} {{ t('份资料') }}</span
        ><span>{{ inspected.archived }} {{ t('份暂存资料') }}</span>
      </div>
      <p class="settings-note">{{ inspected.model }}</p>
      <p v-if="inspected.missing_originals" class="settings-note">
        {{ t('早期导入的文档未保留原件；这些资料恢复已有文字与索引，不会重建原文件。') }}
        {{ inspected.missing_originals }}
      </p>
      <p v-if="!inspected.compatible" class="inline-error">
        {{ t('备份模型或维度不同，不能恢复到当前应用。') }}
      </p>
      <label
        ><input v-model="restoreChats" type="checkbox" :disabled="!!busy" />{{
          t('同时恢复对话')
        }}</label
      ><label
        ><input v-model="restorePreferences" type="checkbox" :disabled="!!busy" />{{
          t('应用备份中的界面偏好')
        }}</label
      ><button
        class="button primary"
        :disabled="!!busy || !inspected.compatible || chat.busy"
        @click="restore"
      >
        <Check :size="16" />{{ t('恢复为新副本') }}
      </button>
    </div>
    <p v-if="busy" class="semantic-status" role="status">
      <LoaderCircle :size="16" class="spin" />{{ t(busy) }}
    </p>
    <p v-if="notice" class="backup-notice" role="status">{{ notice }}</p>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
  </section>
</template>
<style scoped>
.backup-info {
  font-size: var(--text-caption);
  line-height: 1.8;
  color: var(--text-secondary);
  margin: 18px 0;
}
.backup-info p {
  margin: 8px 0;
}
.backup-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.backup-preview {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 18px;
  margin-top: 20px;
  background: var(--surface-soft);
}
.backup-preview-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.backup-preview-heading strong {
  font-size: var(--text-label);
  overflow-wrap: anywhere;
}
.backup-stats {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin: 14px 0;
  font-size: var(--text-label);
}
.backup-preview label {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: var(--text-label);
  margin: 14px 0;
}
.backup-preview input {
  accent-color: var(--green);
}
.backup-notice {
  font-size: var(--text-label);
  line-height: 1.8;
  color: var(--green);
  background: var(--accent-soft);
  border-radius: 10px;
  padding: 12px 16px;
  margin: 18px 0 0;
}
</style>
