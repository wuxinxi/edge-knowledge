<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Check, ChevronDown, LoaderCircle, CirclePause, CircleAlert } from '@lucide/vue'
import type { ChatProcessing } from '../../shared/types/processing'
import { stageLabels } from '../../shared/types/processing'
import { useI18n } from '../../shared/i18n'
const props = defineProps<{
  processing: ChatProcessing
  running: boolean
  hasContent: boolean
  status?: string
}>()
const { t } = useI18n()
const now = ref(Date.now())
const expanded = ref(props.running && !props.hasContent)
let timer: ReturnType<typeof setInterval> | undefined
watch(
  () => props.running,
  (running) => {
    if (timer) clearInterval(timer)
    now.value = Date.now()
    if (running)
      timer = setInterval(() => {
        now.value = Date.now()
      }, 250)
  },
  { immediate: true },
)
watch(
  () => props.hasContent,
  (hasContent, previous) => {
    if (hasContent && !previous) expanded.value = false
  },
)
watch(
  () => props.running,
  (running) => {
    if (!running) expanded.value = false
  },
)
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
const end = computed(
  () =>
    props.processing.finishedAt ??
    (props.running
      ? now.value
      : (props.processing.steps.at(-1)?.startedAt ?? props.processing.startedAt)),
)
const duration = computed(() =>
  Math.max(0, (end.value - props.processing.startedAt) / 1000).toFixed(1),
)
const current = computed(() => props.processing.steps.at(-1))
const label = computed(() =>
  props.running
    ? t(current.value ? stageLabels[current.value.stage] : '处理中')
    : t(props.status === 'error' ? '处理失败' : props.status === 'stopped' ? '已停止' : '处理完成'),
)
function stepSeconds(index: number) {
  return Math.max(
    0,
    ((props.processing.steps[index + 1]?.startedAt ?? end.value) -
      props.processing.steps[index]!.startedAt) /
      1000,
  ).toFixed(1)
}
</script>
<template>
  <details
    class="chat-activity"
    :open="expanded"
    @toggle="expanded = ($event.target as HTMLDetailsElement).open"
  >
    <summary>
      <LoaderCircle v-if="running" :size="13" class="spin" />
      <CircleAlert v-else-if="status === 'error'" :size="13" />
      <CirclePause v-else-if="status === 'stopped'" :size="13" />
      <Check v-else :size="13" />
      <span role="status">{{ label }}</span>
      <span class="activity-elapsed" aria-hidden="true">{{ duration }}s</span>
      <ChevronDown :size="12" class="activity-chevron" />
    </summary>
    <ol class="activity-steps" :aria-label="t('处理过程')">
      <li
        v-for="(step, index) in processing.steps"
        :key="index"
        :class="{ active: running && index === processing.steps.length - 1 }"
      >
        <span class="activity-step-dot"></span><span>{{ t(stageLabels[step.stage]) }}</span
        ><time>{{ stepSeconds(index) }}s</time>
      </li>
    </ol>
  </details>
</template>
<style>
.chat-activity {
  margin: 0 0 14px;
  color: var(--muted);
  font-size: 12px;
}
.chat-activity > summary {
  display: flex;
  align-items: center;
  gap: 7px;
  width: fit-content;
  cursor: pointer;
  padding: 3px 0;
  list-style: none;
}
.chat-activity > summary::-webkit-details-marker {
  display: none;
}
.activity-elapsed {
  font-variant-numeric: tabular-nums;
  font-size: 11px;
  opacity: 0.75;
}
.activity-chevron {
  margin-left: 3px;
  transition: transform 0.15s;
}
.chat-activity[open] .activity-chevron {
  transform: rotate(180deg);
}
.activity-steps {
  list-style: none;
  margin: 8px 0 0 6px;
  padding: 0 0 0 14px;
  border-left: 1px solid var(--line);
  display: grid;
  gap: 8px;
  max-width: 330px;
}
.activity-steps > li {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
}
.activity-steps time {
  margin-left: auto;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.activity-step-dot {
  position: absolute;
  left: -18px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--line-strong);
  outline: 3px solid var(--canvas);
}
.activity-steps .active {
  color: var(--text-secondary);
}
.activity-steps .active .activity-step-dot {
  background: var(--green);
}
</style>
