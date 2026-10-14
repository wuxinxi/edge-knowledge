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
  ChevronDown,
} from '@lucide/vue'
import type { Source } from '../../shared/types/api'
import { useI18n } from '../../shared/i18n'
import SourceContent from './SourceContent.vue'
const props = defineProps<{ sources: Source[]; library: string; inline?: boolean }>()
const { t } = useI18n()
const expanded = ref(false)
const extraSnippets = ref(new Set<string>())
const dialogOpen = ref(false)
const active = ref(0)
const dialog = ref<HTMLDialogElement>()
const selected = computed(() => props.sources[active.value])
const groups = computed(() => {
  const result = new Map<
    string,
    { filename: string; path?: string; kind: string; indices: number[] }
  >()
  props.sources.forEach((source, index) => {
    const key = source.document_id
    if (!result.has(key))
      result.set(key, {
        filename: source.filename,
        path: source.path,
        kind: source.kind ?? 'document',
        indices: [],
      })
    result.get(key)!.indices.push(index)
  })
  return [...result.values()]
})
const visible = computed(() => (expanded.value ? groups.value : groups.value.slice(0, 4)))
function toggleSnippets(id: string) {
  const next = new Set(extraSnippets.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  extraSnippets.value = next
}
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
  () => [props.library, props.sources],
  () => {
    dialog.value?.close()
    dialogOpen.value = false
    expanded.value = false
    extraSnippets.value = new Set()
  },
)
</script>
<template>
  <section v-if="sources.length" class="answer-sources" :aria-label="t('参考资料')">
    <div class="answer-sources-heading">
      <span>{{ t(inline ? '检索结果' : '参考资料') }}</span
      ><span>{{ groups.length }} {{ t('份资料') }} · {{ sources.length }} {{ t('个片段') }}</span
      ><button
        v-if="!inline || groups.length > 4"
        class="text-button source-disclosure"
        :aria-expanded="expanded"
        @click="expanded = !expanded"
      >
        {{ t(expanded ? '收起' : inline ? '查看全部' : '展开来源') }}
        <ChevronDown :size="13" :class="{ rotated: expanded }" />
      </button>
    </div>
    <p v-if="!inline && !expanded" class="source-summary-names">
      {{
        groups
          .slice(0, 3)
          .map((group) => group.filename)
          .join(' · ')
      }}
      <span v-if="groups.length > 3"> · +{{ groups.length - 3 }}</span>
    </p>
    <div
      v-if="inline || expanded"
      class="answer-source-grid"
      :class="{
        'inline-source-grid': inline,
        'single-source-grid': inline && visible.length === 1,
        'document-source-grid': inline && visible.every((group) => group.kind === 'document'),
      }"
    >
      <article
        v-for="group in visible"
        :key="group.indices[0]"
        class="answer-source-result"
        :class="{ 'source-document-result': group.kind === 'document' }"
      >
        <button class="answer-source-card" @click="open(group.indices[0]!)">
          <span class="answer-source-icon"><component :is="icon(group.kind)" :size="16" /></span
          ><span class="answer-source-info"
            ><strong :title="group.filename">{{ group.filename }}</strong
            ><small
              >{{ group.indices.map((i) => '[' + (i + 1) + ']').join(' ') }} ·
              {{ group.indices.length }} {{ t('个片段') }}</small
            ><small
              v-if="group.path && group.path !== group.filename"
              class="source-path"
              :title="group.path"
              >{{ group.path }}</small
            ></span
          ><ChevronRight :size="14" />
        </button>
        <template v-if="inline">
          <SourceContent
            v-for="index in extraSnippets.has(sources[group.indices[0]!]!.document_id) &&
            group.kind !== 'image'
              ? group.indices
              : [group.indices[0]!]"
            :key="index"
            :source="sources[index]!"
            :library="library"
            compact
          />
          <button
            v-if="group.kind !== 'image' && group.indices.length > 1"
            class="text-button source-snippet-toggle"
            :aria-expanded="extraSnippets.has(sources[group.indices[0]!]!.document_id)"
            @click="toggleSnippets(sources[group.indices[0]!]!.document_id)"
          >
            {{
              t(
                extraSnippets.has(sources[group.indices[0]!]!.document_id)
                  ? '收起其余片段'
                  : '展开其余片段',
              )
            }}
            · {{ group.indices.length - 1 }}
          </button>
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
          <p v-if="selected.path && selected.path !== selected.filename" class="source-path">
            {{ selected.path }}
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
