<script setup lang="ts">
import { computed, nextTick, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import type { Component } from 'vue'
import {
  AtSign,
  FileText,
  LoaderCircle,
  X,
  Search,
  Sparkles,
  ListChecks,
  SquarePen,
  Shapes,
  Database,
  ShieldCheck,
  CornerDownLeft,
  Image,
  AudioLines,
  Film,
  Layers3,
} from '@lucide/vue'
import { useRouter } from 'vue-router'
import { api } from '../../shared/api/client'
import { useI18n } from '../../shared/i18n'
import type { ReferenceChoice } from '../../shared/types/api'
import type { Reference } from './store'
import { referenceLabel, referenceLocation, referenceDescription } from './references'
const props = defineProps<{
  modelValue: string
  library: string
  references: Reference[]
  mode: 'search' | 'chat'
  disabled: boolean
  busy: boolean
  canCreateConversation: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  references: [items: Reference[]]
  mode: [value: 'search' | 'chat']
  send: []
  new: []
}>()
const router = useRouter()
const { t, preferences } = useI18n()
const pickerWrap = ref<HTMLElement>()
function dismiss(event: PointerEvent) {
  if (trigger.value && !pickerWrap.value?.contains(event.target as Node)) trigger.value = ''
}
onMounted(() => {
  document.addEventListener('pointerdown', dismiss)
  window.addEventListener('resize', fitInput)
  fitInput()
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', dismiss)
  window.removeEventListener('resize', fitInput)
  request++
  clearTimeout(searchTimer)
  pending?.abort()
})
const input = ref<HTMLTextAreaElement>(),
  referenceSearch = ref<HTMLInputElement>(),
  choices = ref<ReferenceChoice[]>([]),
  total = ref(0),
  offset = ref(0),
  loading = ref(false),
  error = ref('')
const trigger = ref<'reference' | 'command' | ''>(''),
  query = ref(''),
  start = ref(0),
  end = ref(0),
  selected = ref(0)
function fitInput() {
  const node = input.value
  if (!node) return
  node.style.height = 'auto'
  const minimum = parseFloat(getComputedStyle(node).minHeight) || 36
  node.style.height = Math.min(160, Math.max(minimum, node.scrollHeight)) + 'px'
  node.style.overflowY = node.scrollHeight > 160 ? 'auto' : 'hidden'
}
watch(
  () => [props.modelValue, props.busy, preferences.values.fontSize],
  async () => {
    await nextTick()
    fitInput()
  },
)
function focus() {
  input.value?.focus()
}
defineExpose({ focus })
let request = 0
let searchTimer: ReturnType<typeof setTimeout> | undefined
let pending: AbortController | undefined
async function loadChoices(append = false) {
  if (trigger.value !== 'reference') return
  pending?.abort()
  const controller = (pending = new AbortController())
  const current = ++request
  loading.value = true
  error.value = ''
  try {
    const result = await api.referenceChoices(
      props.library,
      query.value.trim(),
      append ? offset.value : 0,
      controller.signal,
    )
    if (current !== request) return
    const items = append ? [...choices.value, ...result.items] : result.items
    choices.value = [...new Map(items.map((item) => [item.document_id, item])).values()]
    total.value = result.total
    offset.value = result.offset + result.items.length
    if (!append)
      selected.value = Math.max(
        0,
        choices.value.findIndex(
          (item) => !props.references.some((reference) => reference.id === item.document_id),
        ),
      )
  } catch (cause) {
    if (current === request && !controller.signal.aborted)
      error.value = cause instanceof Error ? cause.message : t('无法读取资料')
  } finally {
    if (current === request) loading.value = false
  }
}
watch(
  () => [props.library, trigger.value, query.value],
  () => {
    ++request
    pending?.abort()
    clearTimeout(searchTimer)
    choices.value = []
    total.value = offset.value = selected.value = 0
    error.value = ''
    loading.value = trigger.value === 'reference'
    if (trigger.value === 'reference') searchTimer = setTimeout(() => void loadChoices(), 160)
  },
)
watch(
  () => props.library,
  () => {
    trigger.value = ''
  },
)
watch(
  () => props.busy,
  (busy) => {
    if (busy) trigger.value = ''
  },
)
const commands = computed(() => [
  {
    id: 'search',
    alias: '搜索',
    label: t('搜索资料'),
    description: t('在本机查找相关资料'),
    icon: Search,
  },
  {
    id: 'ask',
    alias: '问答',
    label: t('AI 解读'),
    description: t('使用所选模型总结与解释资料'),
    icon: Sparkles,
  },
  {
    id: 'reference',
    alias: '引用',
    label: t('引用指定资料'),
    description: t('指定本次检索的资料范围'),
    icon: AtSign,
  },
  {
    id: 'summarize',
    alias: '总结',
    label: t('总结资料'),
    description: t('提炼核心观点与关键结论'),
    icon: ListChecks,
  },
  {
    id: 'new',
    alias: '新建',
    label: t('新对话'),
    description: t('开始一个独立的话题'),
    icon: SquarePen,
  },
  {
    id: 'library',
    alias: '资料',
    label: t('管理资料'),
    description: t('导入、筛选和查看本地资料'),
    icon: Database,
  },
  {
    id: 'workspace',
    alias: '工作台',
    label: t('多模态工作台'),
    description: t('图文检索、分类、聚类与查重'),
    icon: Shapes,
  },
  {
    id: 'permissions',
    alias: '权限',
    label: t('本地权限'),
    description: t('管理可访问的文件与目录'),
    icon: ShieldCheck,
  },
])
interface PickerOption {
  id: string
  label: string
  description: string
  icon: Component
  reference?: Reference
  chosen?: boolean
}
const results = computed<PickerOption[]>(() =>
  trigger.value === 'reference'
    ? choices.value.map((item) => ({
        id: item.document_id,
        label: item.title || item.filename,
        description: item.path || item.filename,
        reference: {
          id: item.document_id,
          filename: item.filename,
          title: item.title,
          path: item.path,
        },
        chosen: props.references.some((ref) => ref.id === item.document_id),
        icon: {
          document: FileText,
          image: Image,
          audio: AudioLines,
          video: Film,
          bundle: Layers3,
        }[item.kind],
      }))
    : commands.value.filter(
        (item) =>
          (item.id !== 'new' || props.canCreateConversation) &&
          `${item.id} ${item.alias} ${item.label}`
            .toLowerCase()
            .includes(query.value.toLowerCase()),
      ),
)
function detect() {
  if (!input.value) return
  const caret = input.value.selectionStart
  const prefix = input.value.value.slice(0, caret)
  const match = prefix.match(/(?:^|\s)(@([^@\n]*)|\/([\w\u4e00-\u9fff-]*))$/u)
  if (!match) {
    trigger.value = ''
    return
  }
  trigger.value = match[1]!.startsWith('@') ? 'reference' : 'command'
  query.value = match[2] ?? match[3] ?? ''
  start.value = caret - match[1]!.length
  end.value = caret
  selected.value = 0
}
function changed(event: Event) {
  emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
  detect()
}
async function openReferences() {
  trigger.value = 'reference'
  query.value = ''
  selected.value = 0
  start.value = end.value = input.value?.selectionStart ?? props.modelValue.length
  await nextTick()
  referenceSearch.value?.focus()
}
async function pick(index: number) {
  const item = results.value[index]
  if (!item || item.chosen || props.disabled || props.busy) return
  let remaining = props.modelValue.slice(0, start.value) + props.modelValue.slice(end.value)
  if (trigger.value === 'reference') {
    if (props.references.length >= 10) {
      error.value = t('最多引用 10 份资料')
      return
    }
    if (!item.reference) return
    emit('references', [...props.references, item.reference])
  } else if (item.id === 'new') {
    // Remove the command from its original draft before navigation. A reused
    // empty conversation may already have an unfinished question of its own.
    emit('update:modelValue', remaining)
    emit('new')
    trigger.value = ''
    error.value = ''
    await nextTick()
    input.value?.focus()
    return
  } else if (item.id === 'reference') {
    emit('update:modelValue', remaining)
    trigger.value = ''
    await nextTick()
    await openReferences()
    return
  } else if (['library', 'workspace', 'permissions'].includes(item.id)) {
    void router.push(
      (
        { library: '/library', workspace: '/semantic', permissions: '/access' } as Record<
          string,
          string
        >
      )[item.id]!,
    )
  } else if (item.id === 'summarize') {
    emit('mode', 'chat')
    remaining = t('请总结资料中的核心观点，并标注出处。')
  } else emit('mode', item.id === 'search' ? 'search' : 'chat')
  emit('update:modelValue', remaining)
  trigger.value = ''
  error.value = ''
  await nextTick()
  input.value?.focus()
  input.value?.setSelectionRange(start.value, start.value)
}
function keydown(event: KeyboardEvent) {
  if (event.isComposing) return
  if (trigger.value) {
    if (event.key === 'Escape') {
      event.preventDefault()
      trigger.value = ''
      void nextTick(() => input.value?.focus())
      return
    }
    if (['ArrowDown', 'ArrowUp'].includes(event.key) && results.value.length) {
      event.preventDefault()
      const direction = event.key === 'ArrowDown' ? 1 : -1
      for (let step = 1; step <= results.value.length; step++) {
        const index =
          (selected.value + direction * step + results.value.length) % results.value.length
        if (!results.value[index]?.chosen) {
          selected.value = index
          break
        }
      }
      void nextTick(() =>
        document
          .getElementById(`composer-option-${selected.value}`)
          ?.scrollIntoView({ block: 'nearest' }),
      )
      return
    }
    if (['Enter', 'Tab'].includes(event.key) && results.value.length) {
      event.preventDefault()
      void pick(selected.value)
      return
    }
    if (trigger.value === 'reference' && event.key === 'Enter') {
      event.preventDefault()
      return
    }
  }
  if (
    event.target === input.value &&
    event.key === 'Enter' &&
    !event.shiftKey &&
    (preferences.values.sendKey === 'enter'
      ? !event.ctrlKey && !event.metaKey && !event.altKey
      : event.ctrlKey || event.metaKey)
  ) {
    event.preventDefault()
    trigger.value = ''
    emit('send')
  }
}
watch(
  () => props.modelValue,
  (value) => {
    if (!value) trigger.value = ''
  },
)
</script>
<template>
  <div class="reference-chips" v-if="references.length">
    <div class="reference-scope-heading">
      <span class="reference-scope">{{ t('当前资料范围') }} · {{ references.length }}</span>
      <button
        type="button"
        class="text-button"
        :disabled="busy || disabled"
        @click="emit('references', [])"
      >
        {{ t('清除引用') }}
      </button>
    </div>
    <div class="reference-chip-list">
      <span
        v-for="reference in references"
        :key="reference.id"
        class="reference-chip"
        :title="referenceDescription(reference)"
        ><FileText :size="13" /><span class="reference-chip-copy"
          ><strong>{{ referenceLabel(reference) }}</strong
          ><small v-if="referenceLocation(reference) !== referenceLabel(reference)">{{
            referenceLocation(reference)
          }}</small></span
        ><button
          type="button"
          :disabled="busy || disabled"
          :aria-label="`${t('移除引用')} ${referenceLabel(reference)}`"
          @click="
            emit(
              'references',
              references.filter((item) => item.id !== reference.id),
            )
          "
        >
          <X :size="12" /></button
      ></span>
    </div>
    <p class="reference-scope-note">{{ t('查找和回答仅使用这些资料；清除后可查找其他资料。') }}</p>
  </div>
  <div ref="pickerWrap" class="composer-input-wrap">
    <textarea
      ref="input"
      :value="modelValue"
      :disabled="disabled"
      maxlength="4000"
      :aria-label="t('描述想查找的资料或问题')"
      :placeholder="mode === 'search' ? t('描述你想查找的资料…') : t('根据你的资料，问一个问题…')"
      rows="1"
      :aria-expanded="!!trigger"
      :aria-controls="trigger ? 'composer-options' : undefined"
      :aria-activedescendant="trigger && results.length ? `composer-option-${selected}` : undefined"
      @input="changed"
      @click="detect"
      @keydown="keydown"
    />
    <div
      v-if="trigger"
      class="composer-picker"
      id="composer-options"
      role="listbox"
      :aria-label="trigger === 'reference' ? t('引用资料') : t('快捷命令')"
    >
      <div class="picker-heading">
        <span>{{ trigger === 'reference' ? t('引用资料') : t('快捷命令') }}</span
        ><span>{{ trigger === 'reference' ? total : results.length }} {{ t('个选项') }}</span>
      </div>
      <div v-if="trigger === 'reference'" class="reference-picker-search">
        <Search :size="14" />
        <input
          ref="referenceSearch"
          v-model="query"
          :disabled="disabled || busy"
          maxlength="400"
          :aria-label="t('搜索资料标题、文件名或路径')"
          :placeholder="t('搜索标题、文件名或路径…')"
          @keydown="keydown"
        />
      </div>
      <div class="picker-list">
        <div
          v-if="trigger === 'reference' && loading && !results.length"
          class="picker-empty"
          role="status"
        >
          <LoaderCircle :size="15" class="spin" />{{ t('正在读取资料…') }}
        </div>
        <button
          v-for="(item, index) in results"
          :key="item.id"
          :id="`composer-option-${index}`"
          role="option"
          :aria-selected="selected === index"
          type="button"
          :title="item.description"
          :disabled="
            disabled || busy || item.chosen || (trigger === 'reference' && references.length >= 10)
          "
          :class="{ selected: selected === index }"
          @mousedown.prevent
          @click="pick(index)"
        >
          <span class="command-icon"
            ><component :is="item.icon" :size="17" :stroke-width="1.7" /></span
          ><span class="command-copy"
            ><strong>{{ item.label }}</strong
            ><small>{{ item.description }}</small></span
          ><span v-if="trigger === 'command'" class="command-name">/{{ item.id }}</span
          ><span v-if="item.chosen" class="reference-selected">{{ t('已引用') }}</span
          ><CornerDownLeft v-else-if="selected === index" :size="14" />
        </button>
        <p v-if="!loading && !error && !results.length" class="picker-empty">
          {{
            trigger === 'reference' && !query.trim()
              ? t('请先在知识库中导入资料')
              : t('没有匹配的资料')
          }}
        </p>
        <div v-if="error && trigger === 'reference'" class="reference-picker-error" role="alert">
          <span>{{ error }}</span
          ><button
            type="button"
            class="text-button"
            :disabled="loading"
            @click="loadChoices(choices.length > 0)"
          >
            {{ t('重试') }}
          </button>
        </div>
        <button
          v-if="trigger === 'reference' && offset < total && !error"
          type="button"
          class="reference-load-more"
          :disabled="loading"
          @mousedown.prevent
          @click="loadChoices(true)"
        >
          {{ t(loading ? '正在读取资料…' : '加载更多') }} · {{ choices.length }} / {{ total }}
        </button>
      </div>
      <p v-if="trigger === 'reference' && references.length >= 10" class="picker-empty">
        {{ t('最多引用 10 份资料') }}
      </p>
      <div class="picker-footer">
        <span><kbd>↑</kbd> <kbd>↓</kbd> {{ t('选择') }}</span
        ><span><kbd>↵</kbd> {{ t('确认') }}</span
        ><span><kbd>esc</kbd> {{ t('关闭') }}</span>
      </div>
    </div>
  </div>
  <div class="composer-reference-toolbar">
    <button type="button" class="text-button" :disabled="disabled || busy" @click="openReferences">
      <AtSign :size="14" />{{ t('引用资料') }}</button
    ><span>{{ t('输入 @ 引用资料，/ 使用快捷命令') }}</span>
  </div>
  <div v-if="error && trigger !== 'reference'" class="inline-error" role="alert">{{ error }}</div>
</template>
