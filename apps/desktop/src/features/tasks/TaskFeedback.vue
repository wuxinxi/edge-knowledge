<script setup lang="ts">
import { computed } from 'vue'
import { CheckCircle2, AlertCircle, LoaderCircle, PauseCircle, RotateCcw } from '@lucide/vue'
import { useI18n } from '../../shared/i18n'
import { useTaskStore, type TaskRecord } from './store'
import './tasks.css'
const props = defineProps<{ task: TaskRecord }>()
const { t } = useI18n()
const tasks = useTaskStore()
const label = computed(() =>
  t(
    {
      running: props.task.phase,
      success: '已完成',
      partial: '部分完成',
      error: '处理失败',
      stopped: '已停止',
    }[props.task.state],
  ),
)
const controls = computed(() => tasks.controls(props.task.id))
</script>
<template>
  <section
    class="task-feedback"
    :class="task.state"
    :role="task.state === 'error' ? 'alert' : undefined"
    :aria-label="t(task.title)"
  >
    <div class="task-feedback-heading">
      <LoaderCircle v-if="task.state === 'running'" class="spin" :size="16" />
      <CheckCircle2 v-else-if="task.state === 'success'" :size="16" />
      <PauseCircle v-else-if="task.state === 'stopped'" :size="16" />
      <AlertCircle v-else :size="16" />
      <strong>{{ t(task.title) }}</strong
      ><span role="status">{{ label }}</span>
    </div>
    <p v-if="task.detail" class="task-detail">{{ t(task.detail) }}</p>
    <div v-if="task.total !== undefined && task.state !== 'success'" class="task-progress">
      <progress
        :value="task.completed ?? 0"
        :max="Math.max(task.total, 1)"
        :aria-label="t('已处理文件')"
      ></progress>
      <span>{{ task.completed ?? 0 }} / {{ task.total }}</span>
    </div>
    <div
      v-if="
        (task.state === 'running' && controls.stop) || (task.state !== 'running' && controls.retry)
      "
      class="task-feedback-actions"
    >
      <button
        v-if="task.state === 'running' && controls.stop"
        type="button"
        class="text-button"
        @click="tasks.stop(task.id)"
      >
        {{ t(controls.stopLabel || '停止等待') }}
      </button>
      <button
        v-else-if="controls.retry"
        type="button"
        class="text-button"
        @click="tasks.retry(task.id)"
      >
        <RotateCcw :size="12" />{{ t(controls.retryLabel || '重试') }}
      </button>
    </div>
  </section>
</template>
