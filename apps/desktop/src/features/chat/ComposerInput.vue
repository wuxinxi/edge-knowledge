<script setup lang="ts">
import { computed, nextTick, ref, watch, onMounted, onBeforeUnmount } from 'vue'
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
import type { Document } from '../../shared/types/api'
import type { Reference } from './store'
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
})
const input = ref<HTMLTextAreaElement>(),
  documents = ref<Document[]>([]),
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
watch(
  () => props.library,
  async (library) => {
    const current = ++request
    documents.value = []
    trigger.value = ''
    loading.value = true
    error.value = ''
    try {
      const result = await api.documents(library)
      if (current === request) documents.value = result
    } catch (cause) {
      if (current === request)
        error.value = cause instanceof Error ? cause.message : t('无法读取资料')
    } finally {
      if (current === request) loading.value = false
    }
  },
  { immediate: true },
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
    description: t('通过 DeepSeek 总结与解释资料'),
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
const results = computed(() =>
  trigger.value === 'reference'
    ? documents.value
        .filter(
          (item) =>
            !props.references.some((ref) => ref.id === item.id) &&
            item.filename.toLowerCase().includes(query.value.toLowerCase()),
        )
        .slice(0, 8)
        .map((item) => ({
          id: item.id,
          label: item.filename,
          icon: {
            document: FileText,
            image: Image,
            audio: AudioLines,
            video: Film,
            bundle: Layers3,
          }[item.kind],
          description: t(
            (
              {
                document: '文档',
                image: '图片',
                audio: '音频',
                video: '视频',
                bundle: '联合素材',
              } as const
            )[item.kind],
          ),
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
  input.value?.focus()
}
async function pick(index: number) {
  const item = results.value[index]
  if (!item || props.busy) return
  let remaining = props.modelValue.slice(0, start.value) + props.modelValue.slice(end.value)
  if (trigger.value === 'reference') {
    if (props.references.length >= 10) {
      error.value = t('最多引用 10 份资料')
      return
    }
    emit('references', [...props.references, { id: item.id, filename: item.label }])
  } else if (item.id === 'new') {
    emit('new')
    remaining = ''
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
      return
    }
    if (['ArrowDown', 'ArrowUp'].includes(event.key) && results.value.length) {
      event.preventDefault()
      selected.value =
        (selected.value + (event.key === 'ArrowDown' ? 1 : -1) + results.value.length) %
        results.value.length
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
  }
  if (
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
    <span class="reference-scope">{{ t('只检索所选资料') }}</span
    ><span v-for="reference in references" :key="reference.id" class="reference-chip"
      ><FileText :size="12" /><span>{{ reference.filename }}</span
      ><button
        type="button"
        :disabled="busy"
        :aria-label="`${t('移除引用')} ${reference.filename}`"
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
        ><span>{{ results.length }} {{ t('个选项') }}</span>
      </div>
      <div class="picker-list">
        <div v-if="trigger === 'reference' && loading" class="picker-empty">
          <LoaderCircle :size="15" class="spin" />{{ t('正在读取资料…') }}
        </div>
        <button
          v-for="(item, index) in results"
          :key="item.id"
          :id="`composer-option-${index}`"
          role="option"
          :aria-selected="selected === index"
          type="button"
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
          ><CornerDownLeft v-else-if="selected === index" :size="14" />
        </button>
        <p v-if="!loading && !results.length" class="picker-empty">
          {{
            trigger === 'reference' && !documents.length
              ? t('请先在知识库中导入资料')
              : t('没有匹配的资料')
          }}
        </p>
      </div>
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
  <div v-if="error" class="inline-error" role="alert">{{ error }}</div>
</template>
