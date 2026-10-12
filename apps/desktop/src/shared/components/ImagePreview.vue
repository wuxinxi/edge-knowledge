<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Image as ImageIcon, LoaderCircle, X } from '@lucide/vue'
import { api } from '../api/client'

const props = defineProps<{
  library: string
  document: string
  filename: string
  compact?: boolean
}>()
const thumbnail = ref('')
const full = ref('')
const error = ref('')
const loading = ref(false)
const dialog = ref<HTMLDialogElement>()
let thumbController: AbortController | undefined
let fullController: AbortController | undefined

function release(url: string) {
  if (url) URL.revokeObjectURL(url)
}
function close() {
  dialog.value?.close()
  fullController?.abort()
  release(full.value)
  full.value = ''
  loading.value = false
}
watch(
  () => [props.library, props.document],
  async () => {
    thumbController?.abort()
    close()
    release(thumbnail.value)
    thumbnail.value = ''
    error.value = ''
    const controller = (thumbController = new AbortController())
    try {
      const blob = await api.imageAsset(props.library, props.document, true, controller.signal)
      if (!controller.signal.aborted) thumbnail.value = URL.createObjectURL(blob)
    } catch (cause) {
      if (!controller.signal.aborted)
        error.value = cause instanceof Error ? cause.message : '图片预览失败。'
    }
  },
  { immediate: true },
)

async function open() {
  fullController?.abort()
  release(full.value)
  full.value = ''
  error.value = ''
  loading.value = true
  await nextTick()
  dialog.value?.showModal()
  const controller = (fullController = new AbortController())
  try {
    const blob = await api.imageAsset(props.library, props.document, false, controller.signal)
    if (!controller.signal.aborted) full.value = URL.createObjectURL(blob)
  } catch (cause) {
    if (!controller.signal.aborted)
      error.value = cause instanceof Error ? cause.message : '图片读取失败。'
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}
onBeforeUnmount(() => {
  thumbController?.abort()
  close()
  release(thumbnail.value)
})
</script>

<template>
  <button
    class="image-preview"
    :class="{ compact }"
    type="button"
    :aria-label="`查看图片 ${filename}`"
    :title="error || filename"
    @click="open"
  >
    <img v-if="thumbnail" :src="thumbnail" :alt="filename" />
    <ImageIcon v-else :size="compact ? 20 : 30" />
  </button>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="image-viewer"
      :aria-label="`图片预览：${filename}`"
      @cancel.prevent="close"
      @close="close"
    >
      <div class="image-viewer-header">
        <strong>{{ filename }}</strong
        ><button type="button" class="icon-button" aria-label="关闭图片预览" @click="close">
          <X :size="20" />
        </button>
      </div>
      <div v-if="loading" class="empty-state">
        <LoaderCircle :size="24" class="spin" />正在读取本地图片…
      </div>
      <div v-else-if="error" class="inline-error" role="alert">{{ error }}</div>
      <img v-else-if="full" :src="full" :alt="filename" />
      <p>当前预览从本机读取，不会发送至云端。</p>
    </dialog>
  </Teleport>
</template>
