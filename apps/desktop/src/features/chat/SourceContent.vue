<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { Copy, Check, ChevronDown } from '@lucide/vue'
import type { Source } from '../../shared/types/api'
import { useI18n } from '../../shared/i18n'
import ImagePreview from '../../shared/components/ImagePreview.vue'
import MediaPreview from '../../shared/components/MediaPreview.vue'
import MarkdownAnswer from './MarkdownAnswer.vue'
import { sourcePreview } from './source-preview'
const props = defineProps<{ source: Source; library: string; compact?: boolean }>()
const { t } = useI18n()
const copied = ref(false),
  error = ref('')
const media = computed(() => ['audio', 'video', 'bundle'].includes(props.source.kind ?? ''))
const image = computed(() => props.source.kind === 'image')
const preview = computed(() => sourcePreview(props.source.text))
const expanded = ref(false),
  overflowed = ref(false),
  excerptElement = ref<HTMLElement>()
const hasMore = computed(
  () => props.compact && (overflowed.value || preview.value.body.length > 1200),
)
let observer: ResizeObserver | undefined
function measure() {
  const body = excerptElement.value?.querySelector<HTMLElement>('.markdown-answer')
  overflowed.value = !!body && body.scrollHeight > 240
}
function observe() {
  observer?.disconnect()
  const body = excerptElement.value?.querySelector<HTMLElement>('.markdown-answer')
  if (body && props.compact) observer?.observe(body)
  measure()
}
onMounted(() => {
  if (typeof ResizeObserver !== 'undefined') observer = new ResizeObserver(measure)
  observe()
})
onBeforeUnmount(() => observer?.disconnect())
watch(
  () => [props.source.text, props.compact],
  async () => {
    expanded.value = false
    copied.value = false
    error.value = ''
    await nextTick()
    observe()
  },
)
async function copy() {
  try {
    await navigator.clipboard.writeText(props.source.text)
    copied.value = true
    error.value = ''
  } catch {
    error.value = t('无法复制，请直接选择文字复制。')
  }
}
</script>
<template>
  <div class="source-content" :class="{ 'source-content-image': image }">
    <ImagePreview
      v-if="image"
      :library="library"
      :document="source.document_id"
      :filename="source.filename"
    />
    <MediaPreview
      v-if="media"
      :library="library"
      :document="source.document_id"
      :start="source.start"
    />
    <div v-if="!image && source.text" class="source-document-excerpt">
      <dl v-if="preview.metadata.length" class="source-metadata">
        <div v-for="(field, index) in preview.metadata" :key="index">
          <dt>{{ t(field.label) }}</dt>
          <dd>{{ field.value }}</dd>
        </div>
      </dl>
      <p v-if="source.section" class="source-section-label">{{ source.section }}</p>
      <div
        ref="excerptElement"
        class="source-excerpt-reading"
        :class="{ 'is-clipped': hasMore && !expanded }"
        @focusin="expanded = true"
      >
        <MarkdownAnswer v-if="preview.body" :content="preview.body" :source-count="0" />
      </div>
      <div class="source-reading-actions">
        <button
          v-if="hasMore"
          type="button"
          class="answer-action"
          :aria-expanded="expanded"
          @click="expanded = !expanded"
        >
          {{
            t(
              expanded
                ? '收起阅读'
                : source.content_scope === 'full_document'
                  ? '展开全文'
                  : '展开阅读',
            )
          }}<ChevronDown :size="13" :class="{ rotated: expanded }" />
        </button>
        <button type="button" class="answer-action" @click="copy">
          <Check v-if="copied" :size="13" /><Copy v-else :size="13" />{{
            t(
              copied
                ? '已复制'
                : source.content_scope === 'full_document'
                  ? '复制全文'
                  : '复制片段',
            )
          }}
        </button>
        <span v-if="error" class="message-copy-status" role="alert">{{ error }}</span>
      </div>
    </div>
    <p v-if="image" class="source-content-caption">
      {{ t('本地图片') }} ·
      {{ t(source.ocr_status === 'ready' ? '已提取图片文字' : '暂无可用图片文字') }}
    </p>
    <details
      v-if="source.text && (!image || source.ocr_status === 'ready')"
      class="source-original-text"
    >
      <summary>
        {{
          t(
            image
              ? '识别文字 · 本地 OCR'
              : source.content_scope === 'full_document'
                ? '原始全文'
                : '原始片段',
          )
        }}
      </summary>
      <p v-if="image" class="source-content-caption">
        {{ t('图表的坐标、图例和标签会被识别为文字，请结合原图阅读。') }}
      </p>
      <pre>{{ source.text }}</pre>
      <button v-if="image" class="answer-action" type="button" @click="copy">
        <Check v-if="copied" :size="13" /><Copy v-else :size="13" />{{
          t(copied ? '已复制' : '复制原文')
        }}
      </button>
      <span v-if="image && error" class="message-copy-status" role="alert">{{ error }}</span>
    </details>
    <p v-else-if="!image && !source.text" class="source-content-caption">
      {{
        t(
          source.kind === 'document' || !source.kind
            ? '选择这篇文章以阅读全文。'
            : '媒体语义检索结果，请查看本地原件。',
        )
      }}
    </p>
  </div>
</template>
