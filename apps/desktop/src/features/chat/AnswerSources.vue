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
import SourceContent from './SourceContent.vue'
const props = defineProps<{ sources: Source[]; library: string; inline?: boolean }>()
const { t } = useI18n()
const expanded = ref(false)
const dialogOpen = ref(false)
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
  dialogOpen.value = true
  dialog.value?.showModal()
}
defineExpose({ open })
watch(
  () => props.library,
  () => {
    dialog.value?.close()
    dialogOpen.value = false
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
    <div
      class="answer-source-grid"
      :class="{ 'inline-source-grid': inline || visible.some((group) => group.kind === 'image') }"
    >
      <article v-for="group in visible" :key="group.indices[0]" class="answer-source-result">
        <button class="answer-source-card" @click="open(group.indices[0]!)">
          <span class="answer-source-icon"><component :is="icon(group.kind)" :size="16" /></span
          ><span class="answer-source-info"
            ><strong :title="group.filename">{{ group.filename }}</strong
            ><small
              >{{ group.indices.map((i) => '[' + (i + 1) + ']').join(' ') }} ·
              {{ group.indices.length }} {{ t('个片段') }}</small
            ></span
          ><ChevronRight :size="14" />
        </button>
        <template v-if="inline || group.kind === 'image'">
          <SourceContent
            v-for="index in inline && group.kind !== 'image' ? group.indices : [group.indices[0]!]"
            :key="index"
            :source="sources[index]!"
            :library="library"
          />
        </template>
      </article>
    </div>
  </section>
  <dialog
    ref="dialog"
    class="action-dialog source-preview-dialog"
    :aria-label="t('来源片段')"
    @close="dialogOpen = false"
  >
    <template v-if="selected && dialogOpen"
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
        <SourceContent
          :key="`${selected.document_id}:${selected.index}`"
          :source="selected"
          :library="library"
        />
      </div>
      <p class="source-preview-note">
        <ExternalLink :size="12" />{{ t('原文证据来自本次检索，编号与回答引用对应。') }}
      </p></template
    >
  </dialog>
</template>
