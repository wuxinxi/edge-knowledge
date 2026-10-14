<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import {
  ArrowUp,
  Copy,
  ShieldCheck,
  Database,
  FileText,
  Layers3,
  Search,
  Square,
  Sparkles,
} from '@lucide/vue'
import { useAppStore } from '../../app/store'
import { useChatStore } from './store'
import ComposerInput from './ComposerInput.vue'
import { useI18n } from '../../shared/i18n'
import ChatMessage from './ChatMessage.vue'
import QueryBuilder from './QueryBuilder.vue'
import ChatMenu from './ChatMenu.vue'
import { followsLatest } from './scroll'
import type { QuerySpec } from '../../shared/types/query'
import type { Message } from './store'
import { sourceReference } from './references'
import './chat.css'

const app = useAppStore()
const { t, preferences, libraryName } = useI18n()
const chat = useChatStore()
const conversation = computed(() => chat.current(app.activeLibrary))
const fallbackMode = ref<'search' | 'chat'>('chat')
const question = computed<string>({
  get: () => conversation.value?.draft?.content ?? '',
  set: (value: string) => chat.setDraft(app.activeLibrary, value, mode.value),
})
const mode = computed<'search' | 'chat'>({
  get: () => conversation.value?.draft?.mode ?? fallbackMode.value,
  set: (value: 'search' | 'chat') => {
    fallbackMode.value = value
    if (conversation.value?.draft) chat.setDraft(app.activeLibrary, question.value, value)
  },
})
const localModel = computed(() => app.capabilities?.generator.provider !== 'deepseek')
const allowImageUpload = ref(false)
const cloudVision = computed(
  () =>
    mode.value === 'chat' &&
    !localModel.value &&
    app.capabilities?.image_qa_mode === 'cloud_vision',
)
const scroller = ref<HTMLElement>()
const followLatest = ref(true)
let lastScrollTop = 0
function pauseFollowing() {
  followLatest.value = false
}
function scrollWheel(event: WheelEvent) {
  if (event.deltaY < 0) pauseFollowing()
}
function scrollKey(event: KeyboardEvent) {
  const target = event.target as HTMLElement
  if (target.closest('input, textarea, select, [contenteditable="true"]')) return
  if (['ArrowUp', 'PageUp', 'Home'].includes(event.key) || (event.key === ' ' && event.shiftKey))
    pauseFollowing()
}
function localResultAtTop() {
  const last = messages.value.at(-1)
  return last?.mode === 'search' && last.status === 'complete' && last.sources.length > 0
}
function latestResponseTop() {
  const node = scroller.value
  const response = node?.querySelector<HTMLElement>('.chat-turn.assistant:last-child')
  return node && response
    ? response.getBoundingClientRect().top - node.getBoundingClientRect().top
    : undefined
}
function trackScroll() {
  const node = scroller.value
  const top = latestResponseTop()
  if (node) {
    // Position can turn following off, never back on. In particular a queued
    // programmatic scroll must not undo a wheel/drag/key reading gesture.
    if (followLatest.value)
      followLatest.value =
        node.scrollTop >= lastScrollTop - 0.5 &&
        followsLatest(
          node.scrollHeight - node.scrollTop - node.clientHeight,
          localResultAtTop() ? top : undefined,
        )
    lastScrollTop = node.scrollTop
  }
}
function scrollLatest(
  behavior: ScrollBehavior = 'instant',
  alignment: 'bottom' | 'response' = 'bottom',
) {
  followLatest.value = true
  const node = scroller.value,
    responseTop = latestResponseTop()
  if (node) {
    node.scrollTo({
      top:
        alignment === 'response' && localResultAtTop() && responseTop !== undefined
          ? Math.max(0, node.scrollTop + responseTop - 16)
          : node.scrollHeight,
      behavior,
    })
    lastScrollTop = node.scrollTop
  }
}
const composerInput = ref<InstanceType<typeof ComposerInput>>()
const messages = computed(() => conversation.value?.messages ?? [])
const references = computed(() => conversation.value?.references ?? [])
// The /new command remains available without duplicating visible navigation.
function checkDuplicates() {
  followLatest.value = true
  void chat.ask(app.activeLibrary, t('检查当前资料范围的重复笔记'), 'search', false, {
    version: 1,
    operation: 'duplicates',
    threshold: 0.9,
  })
}
function newChat() {
  if (chat.loading) return
  if (conversation.value && !messages.value.length) return
  chat.create(app.activeLibrary)
  allowImageUpload.value = false
}
function exportCompleteChat() {
  if (!conversation.value) return
  const content = JSON.stringify(
    {
      version: 1,
      sessions: [conversation.value],
      active: { [app.activeLibrary]: conversation.value.id },
    },
    null,
    2,
  )
  const url = URL.createObjectURL(new Blob([content], { type: 'application/json;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `conversation-${conversation.value.id}.json`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function exportChat() {
  if (!conversation.value) return
  const content =
    '# ' +
    (conversation.value.title || t('新对话')) +
    '\n\n' +
    messages.value
      .map(
        (message) =>
          '## ' +
          (message.role === 'user' ? t('你') : 'Edge Assistant') +
          '\n\n' +
          message.content +
          (message.sources.length
            ? '\n\n' +
              t('参考资料') +
              ':\n' +
              message.sources
                .map(
                  (source, i) =>
                    `[${i + 1}] ${source.filename}${source.section ? ' · ' + source.section : ''}\n${source.text}`,
                )
                .join('\n\n')
            : ''),
      )
      .join('\n\n')
  const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download =
    (conversation.value.title || 'chat').replace(/[\\/:*?"<>|]/g, '_').slice(0, 60) + '.md'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
const examples = computed(() => [
  {
    icon: Search,
    title: t('查找相关资料'),
    description: t('一句话找到文档、图片和媒体'),
    question: t('项目架构与开发计划'),
    mode: 'search' as const,
  },
  {
    icon: FileText,
    title: t('梳理文档要点'),
    description: t('提炼重点，保留可追溯的出处'),
    question: t('请总结资料中的核心观点，并标注出处。'),
    mode: 'chat' as const,
  },
  {
    icon: Layers3,
    title: t('整理行动步骤'),
    description: t('从现有资料形成清晰的行动清单'),
    question: t('根据资料，整理可以执行的步骤，并说明依据。'),
    mode: 'chat' as const,
  },
])

async function send(value = question.value) {
  if (!value.trim() || chat.busy || chat.loading || !app.health) return
  followLatest.value = true
  const allowed = allowImageUpload.value
  const requestedMode = mode.value
  fallbackMode.value = requestedMode
  allowImageUpload.value = false
  await chat.ask(app.activeLibrary, value, requestedMode, allowed)
}
async function retryMessage(id: string) {
  followLatest.value = true
  const allowed = allowImageUpload.value && cloudVision.value
  allowImageUpload.value = false
  await chat.retry(app.activeLibrary, id, allowed)
}
async function articleAction(source: import('../../shared/types/api').Source, summarize = false) {
  if (chat.busy || chat.loading || !app.health) return
  followLatest.value = true
  await chat.ask(
    app.activeLibrary,
    summarize ? '总结这篇文章' : '查看这篇文章',
    'search',
    false,
    {
      operation: summarize ? 'answer' : 'read',
      ...(summarize ? { source_scope: 'full_document' as const } : {}),
    },
    [sourceReference(source)],
  )
}
function editQuestion(index: number) {
  const request: Message | undefined = messages.value[index - 1]
  if (
    chat.busy ||
    chat.loading ||
    question.value.length ||
    request?.role !== 'user' ||
    request.queryPlan
  )
    return
  mode.value = request.mode ?? 'search'
  question.value = request.content
  allowImageUpload.value = false
  void nextTick(() => composerInput.value?.focus())
}
async function executeLocalQuery(plan: QuerySpec, label: string) {
  if (chat.busy || chat.loading || !app.health) return
  followLatest.value = true
  allowImageUpload.value = false
  await chat.ask(app.activeLibrary, label, 'search', false, plan)
}
function useExample(example: (typeof examples.value)[number]) {
  mode.value = example.mode
  question.value = example.question
  void nextTick(() => composerInput.value?.focus())
}
watch(
  () => [app.activeLibrary, chat.activeByLibrary[app.activeLibrary]],
  () => {
    // The first send creates its own session. Keep that request running; stop only
    // when navigation leaves the conversation that owns the active answer.
    if (!conversation.value?.messages.some((message) => message.id === chat.activeAnswerId))
      chat.stop()
    followLatest.value = true
    fallbackMode.value =
      conversation.value?.draft?.mode ??
      conversation.value?.messages
        .slice()
        .reverse()
        .find((message) => message.role === 'user')?.mode ??
      'chat'
    allowImageUpload.value = false
  },
  { immediate: true },
)
watch(mode, () => {
  allowImageUpload.value = false
})
watch(
  () =>
    messages.value
      .map((message) => message.content + message.error + message.status + message.mode)
      .join(''),
  async () => {
    await nextTick()
    if (followLatest.value && !chat.loading)
      scrollLatest('instant', chat.busy ? 'response' : 'bottom')
  },
)
let restoreRevision = 0
watch(
  () => [app.activeLibrary, conversation.value?.id, chat.loading],
  async () => {
    const revision = ++restoreRevision
    await nextTick()
    // Opening is a view lifecycle event, even if the restored text is identical
    // to the browser cache or another conversation. Do not override a reading gesture.
    if (
      revision === restoreRevision &&
      !chat.loading &&
      followLatest.value &&
      messages.value.length
    )
      scrollLatest('instant', 'bottom')
  },
  { immediate: true },
)
</script>

<template>
  <section class="chat-page" :class="{ 'is-empty': !messages.length }">
    <header class="page-header">
      <div class="chat-header-title">
        <h1>{{ t('本地助手') }}</h1>
        <span v-if="messages.length" class="chat-topic" :title="conversation?.title">{{
          conversation?.title
        }}</span>
      </div>
      <div class="chat-header-actions">
        <span class="local-badge"><ShieldCheck :size="13" />{{ t('本地优先') }}</span>
        <ChatMenu v-if="messages.length" :label="t('导出对话')">
          <button type="button" @click="exportChat">
            <FileText :size="14" />{{ t('导出 Markdown') }}
          </button>
          <button type="button" @click="exportCompleteChat">
            <Database :size="14" />{{ t('导出完整记录') }}
          </button>
        </ChatMenu>
      </div>
    </header>
    <div
      ref="scroller"
      class="chat-scroll"
      role="region"
      tabindex="0"
      :aria-label="t('对话内容')"
      @scroll="trackScroll"
      @wheel.passive="scrollWheel"
      @keydown="scrollKey"
      @pointerdown="pauseFollowing"
      @touchmove.passive="pauseFollowing"
    >
      <div v-if="!messages.length" class="chat-welcome">
        <div class="welcome-emblem"><Sparkles :size="28" :stroke-width="1.5" /></div>
        <div class="welcome-eyebrow">
          EDGE ASSISTANT <span> / </span>{{ t('你的本地智能空间') }}
        </div>
        <h2>{{ t('今天想处理什么资料？') }}</h2>
        <p>{{ t('用自然语言查找本地资料，也可以根据资料提问，获得有出处的回答。') }}</p>
        <div v-if="!app.currentLibrary?.chunks" class="empty-library-note">
          <span>{{ t('还没有导入资料？') }}</span
          ><RouterLink to="/library">{{ t('添加第一份文档') }}<span>→</span></RouterLink>
        </div>
      </div>

      <div v-else class="message-list" aria-live="polite">
        <ChatMessage
          v-for="(message, index) in messages"
          :key="message.id"
          :message="message"
          :library="app.activeLibrary"
          :task="message.id === chat.activeAnswerId ? chat.activeTask : undefined"
          :generating="chat.busy && index === messages.length - 1"
          :can-retry="!chat.busy && index === messages.length - 1"
          :request="messages[index - 1]?.role === 'user' ? messages[index - 1] : undefined"
          :can-edit="!chat.busy && !chat.loading && !question.length"
          :has-draft="!!question.length"
          @retry="retryMessage(message.id)"
          @edit="editQuestion(index)"
          @read="articleAction($event)"
          @summarize="articleAction($event, true)"
        />
      </div>
    </div>

    <div v-if="chat.savingError" class="inline-error" role="alert">{{ chat.savingError }}</div>
    <div class="composer-area">
      <button
        v-if="messages.length && !followLatest"
        type="button"
        class="jump-to-latest"
        @click="scrollLatest()"
      >
        {{ t('回到最新回复') }} ↓
      </button>
      <form class="composer" @submit.prevent="send()">
        <div class="composer-controls">
          <div class="mode-selector" role="group" :aria-label="t('助手模式')">
            <button
              type="button"
              :aria-pressed="mode === 'search'"
              :class="{ selected: mode === 'search' }"
              :disabled="chat.busy || chat.loading"
              @click="mode = 'search'"
            >
              <Search :size="13" />{{ t('查找资料') }}
            </button>
            <button
              type="button"
              :aria-pressed="mode === 'chat'"
              :class="{ selected: mode === 'chat' }"
              :disabled="chat.busy || chat.loading"
              @click="mode = 'chat'"
            >
              <Sparkles :size="13" />{{ t(localModel ? '本地助手' : 'DeepSeek 解读') }}
            </button>
          </div>
          <ChatMenu :label="t('资料工具')" :disabled="chat.busy || chat.loading || !app.health">
            <QueryBuilder
              :disabled="chat.busy || chat.loading || !app.health"
              :scope-label="
                references.length
                  ? `${references.length} ${t('份引用资料')}`
                  : libraryName(app.activeLibrary, app.currentLibrary?.name ?? t('我的知识库'))
              "
              @execute="executeLocalQuery"
            />
            <button
              type="button"
              :disabled="chat.busy || chat.loading || !app.health"
              @click="checkDuplicates"
            >
              <Copy :size="13" />{{ t('检查重复') }}
            </button>
          </ChatMenu>
        </div>
        <ComposerInput
          ref="composerInput"
          v-model="question"
          :library="app.activeLibrary"
          :references="references"
          :mode="mode"
          :disabled="!app.health || chat.loading"
          :busy="chat.busy"
          :can-create-conversation="!!messages.length"
          @references="chat.setReferences(app.activeLibrary, $event)"
          @mode="mode = $event"
          @send="send()"
          @new="newChat"
        />
        <label v-if="cloudVision" class="image-consent"
          ><input v-model="allowImageUpload" type="checkbox" :disabled="chat.busy" />{{
            preferences.values.language === 'en-US'
              ? `Allow up to ${app.capabilities?.max_cloud_images ?? 3} relevant images to be sent to DeepSeek for this request`
              : `本次允许将检索到的最多 ${app.capabilities?.max_cloud_images ?? 3} 张相关图片发送至 DeepSeek`
          }}</label
        >
        <div class="composer-toolbar">
          <span class="context-chip"
            ><Database />{{
              libraryName(app.activeLibrary, app.currentLibrary?.name ?? t('我的知识库'))
            }}</span
          ><span class="composer-hint">{{
            t(
              preferences.values.sendKey === 'enter'
                ? 'Enter 发送 · Shift + Enter 换行'
                : 'Ctrl / ⌘ + Enter 发送',
            )
          }}</span
          ><button
            v-if="chat.busy"
            class="send-button"
            type="button"
            :aria-label="t('停止生成')"
            @click="chat.stop"
          >
            <Square :size="16" fill="currentColor" /></button
          ><button
            v-else
            class="send-button"
            :disabled="!question.trim() || !app.health || chat.loading"
            :aria-label="t('发送问题')"
          >
            <ArrowUp :size="20" />
          </button>
        </div>
      </form>
      <div class="composer-footnote">
        {{
          mode === 'search'
            ? t('文档、图片、音视频在本机检索，不调用 DeepSeek。')
            : localModel
              ? t('本地模型理解问题并回答，资料与对话不上传。统计由本机执行，不调用 DeepSeek。')
              : cloudVision
                ? t('云端看图需要支持图片的模型，并需勾选本次发送图片授权。')
                : t(
                    'AI 模式可向 DeepSeek 发送问题与查询字段进行规划，统计由本机计算；总结和解读会发送相关文字。',
                  ) +
                  ' ' +
                  t('对话历史仅用于理解追问，回答仍以本次检索资料为依据。')
        }}
      </div>
    </div>
    <div v-if="!messages.length" class="starter-actions">
      <button
        v-for="example in examples"
        :key="example.title"
        class="starter-action"
        :disabled="!app.health || chat.busy || chat.loading"
        @click="useExample(example)"
      >
        <span class="starter-icon"><component :is="example.icon" :size="17" /></span
        ><strong>{{ example.title }}</strong
        ><small>{{ example.description }}</small>
      </button>
    </div>
  </section>
</template>
