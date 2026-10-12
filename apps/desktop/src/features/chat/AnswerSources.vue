<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  FileText,
  ChevronRight,
  X,
  Image,
  AudioLines,
  Film,
  Layers3,
  ExternalLink,
} from '@lucide/vue'
import type { Source } from '../../shared/types/api'
import { useI18n } from '../../shared/i18n'
import ImagePreview from '../../shared/components/ImagePreview.vue'
import MediaPreview from '../../shared/components/MediaPreview.vue'
const props = defineProps<{ sources: Source[]; library: string }>()
const { t } = useI18n()
const expanded = ref(false)
const active = ref(0)
const dialog = ref<HTMLDialogElement>()
const selected = computed(() => props.sources[active.value])
const groups = computed(() => {
  const result = new Map<string, { filename: string; kind: string; indices: number[] }>()
  props.sources.forEach((source, index) => {
    const key = source.document_id
    if (!result.has(key))
      result.set(key, { filename: source.filename, kind: source.kind ?? 'document', indices: [] })
    result.get(key)!.indices.push(index)
  })
  return [...result.values()]
})
const visible = computed(() => (expanded.value ? groups.value : groups.value.slice(0, 3)))
function icon(kind: string) {
  return { image: Image, audio: AudioLines, video: Film, bundle: Layers3 }[kind] ?? FileText
}
function open(index: number) {
  if (!props.sources[index]) return
  active.value = index
  dialog.value?.showModal()
}
defineExpose({ open })
watch(
  () => props.library,
  () => {
    dialog.value?.close()
    expanded.value = false
  },
)
</script>
<template>
  <section v-if="sources.length" class="answer-sources" :aria-label="t('参考资料')">
    <div class="answer-sources-heading">
      <span>{{ t('参考资料') }}</span
      ><span>{{ groups.length }} {{ t('份资料') }} · {{ sources.length }} {{ t('个片段') }}</span
      ><button v-if="groups.length > 3" class="text-button" @click="expanded = !expanded">
        {{ t(expanded ? '收起' : '查看全部') }}
      </button>
    </div>
    <div class="answer-source-grid">
      <button
        v-for="group in visible"
        :key="group.indices[0]"
        class="answer-source-card"
        @click="open(group.indices[0]!)"
      >
        <span class="answer-source-icon"><component :is="icon(group.kind)" :size="16" /></span
        ><span class="answer-source-info"
          ><strong :title="group.filename">{{ group.filename }}</strong
          ><small
            >{{ group.indices.map((i) => '[' + (i + 1) + ']').join(' ') }} ·
            {{ group.indices.length }} {{ t('个片段') }}</small
          ></span
        ><ChevronRight :size="14" />
      </button>
    </div>
  </section>
  <dialog ref="dialog" class="action-dialog source-preview-dialog" :aria-label="t('来源片段')">
    <template v-if="selected"
      ><div class="source-preview-heading">
        <span class="answer-source-icon"
          ><component :is="icon(selected.kind ?? 'document')" :size="18"
        /></span>
        <div>
          <h2>{{ selected.filename }}</h2>
          <p>
            {{ t('来源片段') }} [{{ active + 1 }}]
            <template v-if="selected.section">· {{ selected.section }}</template>
          </p>
        </div>
        <button class="icon-button" :aria-label="t('关闭来源预览')" @click="dialog?.close()">
          <X :size="18" />
        </button>
      </div>
      <nav class="source-preview-tabs" :aria-label="t('选择来源片段')">
        <button
          v-for="(source, i) in sources"
          :key="i"
          class="source-preview-tab"
          :class="{ active: i === active }"
          :aria-pressed="i === active"
          @click="active = i"
        >
          [{{ i + 1 }}]
        </button>
      </nav>
      <div class="source-preview-body">
        <ImagePreview
          v-if="selected.kind === 'image'"
          :library="library"
          :document="selected.document_id"
          :filename="selected.filename"
        /><MediaPreview
          v-if="['audio', 'video', 'bundle'].includes(selected.kind ?? '')"
          :library="library"
          :document="selected.document_id"
          :start="selected.start"
        />
        <p class="source-preview-text">
          {{ selected.text || t('媒体语义检索结果，请查看本地原件。') }}
        </p>
      </div>
      <p class="source-preview-note">
        <ExternalLink :size="12" />{{ t('原文证据来自本次检索，编号与回答引用对应。') }}
      </p></template
    >
  </dialog>
</template>
