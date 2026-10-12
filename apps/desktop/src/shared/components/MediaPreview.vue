<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { LoaderCircle, Play, X } from '@lucide/vue'
import { api } from '../api/client'
import type { MediaAsset } from '../types/api'
import { useI18n } from '../i18n'
const props = defineProps<{ library: string; document: string; start?: number }>()
const { t } = useI18n()
const assets = ref<MediaAsset[]>([]),
  selected = ref<MediaAsset>(),
  url = ref(''),
  error = ref(''),
  busy = ref(false),
  opened = ref(false)
let controller: AbortController | undefined
function clear() {
  controller?.abort()
  if (url.value) URL.revokeObjectURL(url.value)
  url.value = ''
  selected.value = undefined
  opened.value = false
  error.value = ''
  busy.value = false
}
async function select(asset: MediaAsset) {
  controller?.abort()
  const current = (controller = new AbortController())
  if (url.value) URL.revokeObjectURL(url.value)
  url.value = ''
  selected.value = asset
  busy.value = true
  error.value = ''
  try {
    const blob = await api.mediaAsset(props.library, props.document, asset.index, current.signal)
    if (!current.signal.aborted) url.value = URL.createObjectURL(blob)
  } catch (cause) {
    if (!current.signal.aborted)
      error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (!current.signal.aborted) busy.value = false
  }
}
async function open() {
  const current = (controller = new AbortController())
  busy.value = true
  opened.value = true
  error.value = ''
  try {
    assets.value = await api.mediaManifest(props.library, props.document, current.signal)
    if (!current.signal.aborted && assets.value[0]) await select(assets.value[0])
  } catch (cause) {
    if (!current.signal.aborted)
      error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (!current.signal.aborted) busy.value = false
  }
}
function seek(event: Event) {
  const media = event.target as HTMLMediaElement
  if (!props.start) return
  if (props.start >= media.duration) {
    error.value = t('浏览器无法定位到此片段，请导出素材后用本地播放器打开。')
    return
  }
  media.currentTime = props.start
}
watch(() => [props.library, props.document], clear)
onBeforeUnmount(clear)
</script>
<template>
  <div class="media-preview">
    <button v-if="!opened" type="button" class="text-button media-open" @click="open">
      <Play :size="14" />{{ t('查看本地素材') }}
    </button>
    <template v-else>
      <div class="media-preview-heading">
        <span>{{ t('本地素材') }}</span
        ><button type="button" class="icon-button" :aria-label="t('关闭素材预览')" @click="clear">
          <X :size="16" />
        </button>
      </div>
      <div v-if="assets.length > 1" class="media-asset-tabs">
        <button
          v-for="asset in assets"
          :key="asset.index"
          class="text-button"
          :class="{ active: selected?.index === asset.index }"
          @click="select(asset)"
        >
          {{ asset.filename }}
        </button>
      </div>
      <LoaderCircle v-if="busy" class="spin" :size="18" />
      <p v-if="error" role="alert" class="inline-error">{{ error }}</p>
      <img v-if="url && selected?.kind === 'image'" :src="url" :alt="selected.filename" />
      <audio
        v-else-if="url && selected?.kind === 'audio'"
        :src="url"
        controls
        preload="metadata"
        @loadedmetadata="seek"
        @error="error = t('当前浏览器无法播放此格式，请导出素材后用本地播放器打开。')"
      />
      <video
        v-else-if="url && selected?.kind === 'video'"
        :src="url"
        controls
        preload="metadata"
        @loadedmetadata="seek"
        @error="error = t('当前浏览器无法播放此格式，请导出素材后用本地播放器打开。')"
      />
      <a
        v-if="url && selected"
        :href="url"
        :download="
          selected.kind === 'image'
            ? selected.filename.replace(/\.[^.]+$/, '') + '.png'
            : selected.filename
        "
        class="text-button media-download"
        >{{ t('导出素材') }}</a
      >
      <small v-if="selected">{{ selected.filename }}</small>
    </template>
  </div>
</template>
