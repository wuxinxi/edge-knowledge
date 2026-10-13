<script setup lang="ts">
import { ref, watch } from 'vue'
import { Copy, Check, RotateCcw, Sparkles, Search, LoaderCircle } from '@lucide/vue'
import type { Message } from './store'
import { useI18n } from '../../shared/i18n'
import MarkdownAnswer from './MarkdownAnswer.vue'
import AnswerSources from './AnswerSources.vue'
import DuplicateMatches from './DuplicateMatches.vue'
import type { TaskRecord } from '../tasks/store'
import TaskFeedback from '../tasks/TaskFeedback.vue'
const props = defineProps<{
  message: Message
  library: string
  task?: TaskRecord
  generating: boolean
  canRetry: boolean
}>()
const emit = defineEmits<{ retry: [] }>()
const { t } = useI18n()
const copied = ref(false)
const copyError = ref('')
const sourcesPanel = ref<InstanceType<typeof AnswerSources>>()
watch(
  () => props.message.content,
  () => {
    copied.value = false
    copyError.value = ''
  },
)
async function copy() {
  try {
    const text =
      props.message.mode === 'search' && props.message.sources.length
        ? props.message.content +
          '\n\n' +
          props.message.sources
            .map((source, i) => `[${i + 1}] ${source.filename}\n${source.text}`)
            .join('\n\n')
        : props.message.content
    const comparisons = props.message.comparisons
      ?.map(
        (pair, index) =>
          `候选 ${index + 1} · 相似度 ${pair.score}\n${pair.left.filename}\n${pair.left.text}\n\n${pair.right.filename}\n${pair.right.text}`,
      )
      .join('\n\n')
    await navigator.clipboard.writeText(text + (comparisons ? '\n\n' + comparisons : ''))
    copied.value = true
    copyError.value = ''
  } catch {
    copyError.value = t('无法复制，请直接选择文字复制。')
  }
}
</script>
<template>
  <article class="chat-turn" :class="message.role">
    <template v-if="message.role === 'user'"
      ><div class="user-prompt">
        <p>{{ message.content }}</p>
        <div v-if="message.references?.length" class="message-reference-list">
          <span v-for="reference in message.references" :key="reference.id"
            >@{{ reference.filename }}</span
          >
        </div>
      </div></template
    >
    <template v-else>
      <div class="assistant-identity">
        <span class="assistant-symbol"
          ><Search v-if="message.mode === 'search'" :size="16" /><Sparkles
            v-else
            :size="16" /></span
        ><strong>Edge Assistant</strong
        ><span class="assistant-mode">{{
          t(
            message.comparisons?.length
              ? message.planner === 'deepseek'
                ? '重复检查 · AI 规划'
                : '本地重复检查'
              : message.planner === 'deepseek' && message.mode === 'search'
                ? '本机结果 · AI 规划'
                : message.planner === 'local_model' && message.mode === 'search'
                  ? '本机结果 · 本地模型规划'
                  : message.mode === 'search' || (generating && task?.phase === '查找资料')
                    ? '本地检索'
                    : message.generator === 'local'
                      ? '本地模型回答'
                      : 'DeepSeek 解读',
          )
        }}</span
        ><span v-if="generating" class="assistant-stream-label"
          ><LoaderCircle :size="12" class="spin" />{{ t('正在回答') }}</span
        >
      </div>
      <div class="assistant-answer">
        <TaskFeedback
          v-if="task && (generating || task.state === 'stopped' || task.state === 'error')"
          :task="task"
          class="chat-task-feedback"
        />
        <MarkdownAnswer
          v-if="message.content"
          :content="message.content"
          :source-count="message.sources.length"
          @source="sourcesPanel?.open($event)"
        />
        <div v-else-if="generating && !task" class="answer-thinking" role="status">
          <span></span><span></span><span></span>{{ t('正在查找资料并整理回答…') }}
        </div>
        <div
          v-if="message.error && message.status !== 'stopped' && task?.detail !== message.error"
          role="alert"
          class="inline-error"
        >
          {{ message.error }}
        </div>
        <p v-if="message.status === 'stopped' && !task" class="answer-evidence-note">
          {{ message.error || t('已停止。') }}
        </p>
        <details v-if="message.notice" class="answer-processing-note">
          <summary>{{ t('处理说明') }}</summary>
          <p>{{ message.notice }}</p>
        </details>
        <DuplicateMatches
          v-if="message.comparisons?.length"
          :pairs="message.comparisons"
          :library="library"
        />
        <AnswerSources
          ref="sourcesPanel"
          :sources="message.sources"
          :library="library"
          :inline="message.mode === 'search'"
        />
        <details v-if="message.versions?.length" class="answer-history">
          <summary>{{ t('历史回答') }} · {{ message.versions.length }}</summary>
          <details v-for="(version, index) in message.versions" :key="index">
            <summary>
              {{ t('重试前的回答') }} {{ index + 1 }} ·
              {{ new Date(version.savedAt).toLocaleString() }}
            </summary>
            <MarkdownAnswer :content="version.content" :source-count="0" />
            <p v-if="version.error" class="inline-error">{{ version.error }}</p>
            <DuplicateMatches
              v-if="version.comparisons?.length"
              :pairs="version.comparisons"
              :library="library"
            />
            <AnswerSources
              :sources="version.sources"
              :library="library"
              :inline="message.mode === 'search'"
            />
          </details>
        </details>
        <div class="answer-actions">
          <button class="answer-action" :disabled="!message.content || generating" @click="copy">
            <Check v-if="copied" :size="13" /><Copy v-else :size="13" />{{
              t(copied ? '已复制' : message.mode === 'search' ? '复制结果' : '复制回答')
            }}</button
          ><button
            v-if="canRetry"
            class="answer-action"
            :disabled="generating"
            @click="emit('retry')"
          >
            <RotateCcw :size="13" />{{
              t(message.mode === 'search' ? '重新检索' : '重新生成')
            }}</button
          ><span v-if="copyError" class="message-copy-status" role="alert">{{ copyError }}</span>
        </div>
      </div>
    </template>
  </article>
</template>
