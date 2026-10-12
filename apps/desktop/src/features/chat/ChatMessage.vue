<script setup lang="ts">
import { ref, watch } from 'vue'
import { Copy, Check, RotateCcw, Sparkles, Search, LoaderCircle } from '@lucide/vue'
import type { Message } from './store'
import { useI18n } from '../../shared/i18n'
import MarkdownAnswer from './MarkdownAnswer.vue'
import AnswerSources from './AnswerSources.vue'
const props = defineProps<{
  message: Message
  library: string
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
    await navigator.clipboard.writeText(props.message.content)
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
          t(message.mode === 'search' ? '本地检索' : '资料问答')
        }}</span
        ><span v-if="generating" class="assistant-stream-label"
          ><LoaderCircle :size="12" class="spin" />{{ t('正在回答') }}</span
        >
      </div>
      <div class="assistant-answer">
        <MarkdownAnswer
          v-if="message.content"
          :content="message.content"
          :source-count="message.sources.length"
          @source="sourcesPanel?.open($event)"
        />
        <div v-else-if="generating" class="answer-thinking" role="status">
          <span></span><span></span><span></span>{{ t('正在查找资料并整理回答…') }}
        </div>
        <div v-if="message.error" role="alert" class="inline-error">{{ message.error }}</div>
        <p v-if="message.notice" class="answer-evidence-note">{{ message.notice }}</p>
        <AnswerSources ref="sourcesPanel" :sources="message.sources" :library="library" />
        <div class="answer-actions">
          <button class="answer-action" :disabled="!message.content || generating" @click="copy">
            <Check v-if="copied" :size="13" /><Copy v-else :size="13" />{{
              t(copied ? '已复制' : '复制回答')
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
