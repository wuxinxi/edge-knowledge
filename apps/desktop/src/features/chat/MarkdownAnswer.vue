<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from '../../shared/i18n'
import { renderAnswer } from './markdown'
const props = defineProps<{ content: string; sourceCount: number }>()
const emit = defineEmits<{ source: [index: number] }>()
const { t } = useI18n()
const copied = ref(false)
const copyError = ref('')
watch(
  () => props.content,
  () => {
    copied.value = false
    copyError.value = ''
  },
)
const html = computed(() =>
  renderAnswer(props.content, props.sourceCount, t('复制代码'), t('查看引用')),
)
async function handleClick(event: MouseEvent) {
  const target = (event.target as HTMLElement).closest<HTMLButtonElement>('button')
  if (!target || !(event.currentTarget as HTMLElement).contains(target)) return
  if (target.dataset.sourceIndex !== undefined) {
    emit('source', Number(target.dataset.sourceIndex))
    return
  }
  if (!target.hasAttribute('data-copy-code')) return
  const code = target.closest('.answer-code')?.querySelector('code')?.textContent ?? ''
  try {
    await navigator.clipboard.writeText(code)
    copied.value = true
    copyError.value = ''
  } catch {
    copyError.value = t('无法复制，请直接选择文字复制。')
  }
}
</script>
<template>
  <div class="markdown-answer" @click="handleClick" v-html="html"></div>
  <span v-if="copied" role="status" class="message-copy-status">{{ t('代码已复制') }}</span
  ><span v-if="copyError" role="alert" class="message-copy-status">{{ copyError }}</span>
</template>
