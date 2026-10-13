import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../../shared/api/client'
import { useAppStore } from '../../app/store'
import { useI18n } from '../../shared/i18n'
import { useTaskStore } from '../tasks/store'

export interface ImportRow {
  name: string
  state: 'pending' | 'running' | 'success' | 'error'
  message: string
  file?: File
}
export const useImportStore = defineStore('library-imports', () => {
  const tasks = useTaskStore(),
    app = useAppStore(),
    { t } = useI18n()
  const job = ref<{ library: string; taskId: string; rows: ImportRow[] }>()
  const running = ref(false),
    stopRequested = ref(false),
    revision = ref(0)
  const remaining = computed(
    () => job.value?.rows.filter((row) => row.state === 'pending').length ?? 0,
  )
  const failures = computed(
    () => job.value?.rows.filter((row) => row.state === 'error').length ?? 0,
  )
  const completed = computed(
    () => job.value?.rows.filter((row) => ['success', 'error'].includes(row.state)).length ?? 0,
  )
  function stop() {
    if (!running.value || !job.value) return
    stopRequested.value = true
    tasks.update(job.value.taskId, {
      phase: '等待当前文件完成',
      detail: t('当前文件处理结束后停止，尚未提交的文件会保留。'),
    })
    tasks.setActions(job.value.taskId, {})
  }
  async function process() {
    if (!job.value || running.value) return
    const batch = job.value
    tasks.setActions(batch.taskId, {})
    running.value = true
    stopRequested.value = false
    const id = (batch.taskId = tasks.begin('导入资料', batch.library, {
      stop,
      stopLabel: '停止后续文件',
    }))
    tasks.update(id, { total: batch.rows.length, completed: completed.value })
    try {
      for (const row of batch.rows) {
        if (stopRequested.value) break
        if (row.state !== 'pending' || !row.file) continue
        row.state = 'running'
        tasks.update(id, { phase: '导入中', detail: row.name })
        let submitted = false
        try {
          const file = row.file
          const media = /\.(wav|mp3|m4a|aac|flac|ogg|mp4|mov|mkv|webm)$/i.test(file.name)
          if (file.size > (media ? 200 : 20) * 1024 * 1024)
            throw new Error(t('文档和图片上限 20 MB，音视频上限 200 MB。'))
          if (
            !/\.(txt|md|pdf|docx|png|jpe?g|webp|wav|mp3|m4a|aac|flac|ogg|mp4|mov|mkv|webm)$/i.test(
              file.name,
            )
          )
            throw new Error(t('不支持此文件格式。'))
          submitted = true
          const result = await api.ingest(batch.library, file)
          row.state = 'success'
          row.message = result.duplicate ? t('已存在，跳过重复导入') : t('导入成功')
          row.file = undefined
        } catch (cause) {
          row.state = 'error'
          if (!submitted) row.file = undefined
          row.message = cause instanceof Error ? cause.message : t('导入失败')
        }
        tasks.update(id, { completed: completed.value })
        revision.value++
      }
    } finally {
      let refreshError = ''
      tasks.update(id, { phase: '刷新资料列表' })
      try {
        await app.refreshLibraries()
      } catch {
        refreshError = t('资料已处理，但列表刷新失败，请手动刷新。')
      }
      running.value = false
      const success = batch.rows.filter((row) => row.state === 'success').length
      const failed = failures.value,
        pending = remaining.value
      const detail = `${t('成功')} ${success} · ${t('失败')} ${failed} · ${t('待处理')} ${pending}`
      if (batch.rows.some((row) => row.state === 'error' && row.file) || pending)
        tasks.setActions(id, {
          retryLabel: pending ? '继续未完成文件' : '重试失败文件',
          retry: () => {
            if (!running.value && job.value === batch) void retry()
          },
        })
      tasks.finish(
        id,
        pending ? 'stopped' : failed ? (success ? 'partial' : 'error') : 'success',
        refreshError ? `${detail}\n${refreshError}` : detail,
      )
      revision.value++
    }
  }
  async function start(library: string, files: File[]) {
    if (running.value || !files.length) return
    if (job.value) tasks.setActions(job.value.taskId, {})
    job.value = {
      library,
      taskId: '',
      rows: files.map((file) => ({ name: file.name, state: 'pending', message: '', file })),
    }
    await process()
  }
  async function retry() {
    if (running.value || !job.value) return
    // Successful files are never resubmitted; unfinished files retain their original library.
    for (const row of job.value.rows) if (row.state === 'error' && row.file) row.state = 'pending'
    await process()
  }
  return {
    job,
    running,
    stopRequested,
    revision,
    remaining,
    failures,
    completed,
    start,
    stop,
    retry,
  }
})
