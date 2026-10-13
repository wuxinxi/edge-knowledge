<script setup lang="ts">
import { ref } from 'vue'
import { ListTodo, X } from '@lucide/vue'
import { useI18n } from '../../shared/i18n'
import { useTaskStore } from './store'
import { useAppStore } from '../../app/store'
import TaskFeedback from './TaskFeedback.vue'
const tasks = useTaskStore(),
  app = useAppStore()
const { t, libraryName, preferences } = useI18n()
const dialog = ref<HTMLDialogElement>()
function library(id: string) {
  return libraryName(id, app.libraries.find((item) => item.id === id)?.name ?? t('知识库'))
}
</script>
<template>
  <button
    type="button"
    class="rail-button task-center-trigger"
    :aria-label="t('任务中心')"
    @click="dialog?.showModal()"
  >
    <ListTodo :size="20" /><span
      v-if="tasks.activeCount || tasks.attentionCount"
      class="task-badge"
      :class="{ attention: !tasks.activeCount }"
      >{{ tasks.activeCount || tasks.attentionCount }}</span
    >
    <span class="rail-tooltip" aria-hidden="true">{{ t('任务中心') }}</span>
  </button>
  <Teleport to="body">
    <dialog ref="dialog" class="action-dialog task-center" :aria-label="t('任务中心')">
      <div class="dialog-heading">
        <div>
          <h2>{{ t('任务中心') }}</h2>
          <p>{{ t('查看本次运行中的处理进度与结果') }}</p>
        </div>
        <button
          type="button"
          class="icon-button"
          :aria-label="t('关闭任务中心')"
          @click="dialog?.close()"
        >
          <X :size="18" />
        </button>
      </div>
      <div class="task-center-toolbar">
        <span>{{ t('进行中') }} {{ tasks.activeCount }}</span
        ><button
          type="button"
          class="text-button"
          :disabled="
            !tasks.items.some((item) => item.state !== 'running' && !tasks.controls(item.id).retry)
          "
          @click="tasks.clearFinished"
        >
          {{ t('清除已结束记录') }}
        </button>
      </div>
      <p v-if="!tasks.items.length" class="task-center-empty">
        {{ t('还没有处理任务，导入或查找资料后会显示在这里。') }}
      </p>
      <div v-else class="task-center-list">
        <article v-for="task in tasks.items" :key="task.id">
          <div class="task-center-context">
            <span>{{ library(task.library) }}</span
            ><time>{{
              new Date(task.updatedAt).toLocaleTimeString(preferences.values.language, {
                hour: '2-digit',
                minute: '2-digit',
              })
            }}</time>
          </div>
          <TaskFeedback :task="task" />
        </article>
      </div>
      <p class="task-center-note">
        {{ t('任务记录保留至刷新或退出应用。停止等待不等于取消后台处理。') }}
      </p>
    </dialog>
  </Teleport>
</template>
