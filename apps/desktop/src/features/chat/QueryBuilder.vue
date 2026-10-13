<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import {
  SlidersHorizontal,
  Plus,
  X,
  ArrowRight,
  ShieldCheck,
  Search,
  ChartNoAxesCombined,
  Copy,
  RotateCcw,
  CalendarDays,
  ChevronDown,
} from '@lucide/vue'
import {
  applyQueryPreset,
  buildQuery,
  defaultQueryDraft,
  operatorLabel,
  operatorsFor,
  queryFields,
  queryLabel,
  type FilterDraft,
} from './query-builder'
import type { QuerySpec } from '../../shared/types/query'
import { useI18n } from '../../shared/i18n'
import './query-builder.css'
const props = defineProps<{ disabled?: boolean; scopeLabel?: string }>()
const emit = defineEmits<{ execute: [plan: QuerySpec, label: string] }>()
const { t } = useI18n()
const dialog = ref<HTMLDialogElement>()
const error = ref('')
const numericChoice = ref('size')
const draft = reactive(defaultQueryDraft())
const tasks = [
  { id: 'list' as const, label: '找资料', description: '按条件列出文件', icon: Search },
  {
    id: 'aggregate' as const,
    label: '做统计',
    description: '计算数量或汇总数值',
    icon: ChartNoAxesCombined,
  },
  { id: 'duplicates' as const, label: '检查重复', description: '并排比较相似笔记', icon: Copy },
]
const presets = [
  ['month', '按月份统计笔记'],
  ['tags', '按标签看数量'],
  ['undated', '找未标日期的笔记'],
] as const
const action = computed(
  () => ({ list: '查找资料', aggregate: '开始统计', duplicates: '比较笔记' })[draft.operation],
)
const preview = computed(() => {
  try {
    buildQuery(draft)
    return queryLabel(draft, t)
  } catch {
    return t('补齐条件后，这里会显示将要执行的查询。')
  }
})
const grouped = computed(() => draft.operation === 'aggregate' && !!draft.group)
const sortFields = computed(() =>
  grouped.value
    ? [
        ['key', '分组名称'],
        ['value', '统计结果'],
        ['count', '组内资料数量'],
      ]
    : queryFields.filter(([key]) => !['metadata', 'text', 'tags'].includes(key)),
)
watch(numericChoice, (value) => {
  draft.metricField = value === 'custom' ? '' : value
})
watch(grouped, (value) => {
  draft.order = value ? 'value' : 'title'
})
watch(
  () => draft.operation,
  (operation) => {
    error.value = ''
    if (operation === 'duplicates')
      for (const filter of draft.filters) {
        if (filter.field === 'kind') {
          filter.value = 'document'
          filter.op = 'eq'
        }
      }
  },
)
function preset(id: 'month' | 'tags' | 'undated') {
  const now = new Date()
  applyQueryPreset(draft, id, `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`)
  numericChoice.value = 'size'
  error.value = ''
}
function reset() {
  Object.assign(draft, defaultQueryDraft(), { period: undefined, threshold: undefined })
  numericChoice.value = 'size'
  error.value = ''
}
function fieldChanged(filter: FilterDraft) {
  if (!operatorsFor(filter.field).some(([op]) => op === filter.op)) filter.op = 'eq'
  filter.value = filter.field === 'kind' ? 'document' : ''
  filter.custom = ''
}
function inputType(filter: FilterDraft) {
  if (filter.op === 'in') return 'text'
  if (filter.field.endsWith('_date')) return 'date'
  if (filter.field === 'folder_month') return 'month'
  return ['size', 'duration', 'chunks'].includes(filter.field) ? 'number' : 'text'
}
function placeholder(filter: FilterDraft) {
  if (filter.op === 'in') return t('多个值用逗号分隔')
  return t(
    (
      {
        filename: '输入文件名关键词',
        tags: '例如 工作',
        path: '例如 notes/工作',
        extension: '例如 .md',
        metadata: '输入属性值',
      } as Record<string, string>
    )[filter.field] ?? '输入条件值',
  )
}
function open() {
  error.value = ''
  dialog.value?.showModal()
}
function execute() {
  try {
    const plan = buildQuery(draft)
    error.value = ''
    dialog.value?.close()
    emit('execute', plan, queryLabel(draft, t))
  } catch (cause) {
    error.value = t(cause instanceof Error ? cause.message : '请检查筛选条件。')
  }
}
</script>
<template>
  <button
    class="query-builder-trigger text-button"
    type="button"
    :disabled="props.disabled"
    @click="open"
  >
    <SlidersHorizontal :size="14" />{{ t('筛选与统计') }}
  </button>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="action-dialog query-builder-dialog"
      :aria-label="t('筛选与统计')"
      aria-describedby="query-builder-intro"
    >
      <header class="qb-heading">
        <span class="qb-emblem"><SlidersHorizontal :size="19" /></span>
        <div>
          <h2>{{ t('筛选与统计') }}</h2>
          <p id="query-builder-intro">{{ t('选择要做的事，结果直接显示在聊天里。') }}</p>
        </div>
        <button
          type="button"
          class="icon-button"
          :aria-label="t('关闭筛选与统计')"
          @click="dialog?.close()"
        >
          <X :size="18" />
        </button>
      </header>
      <form @submit.stop.prevent="execute">
        <div class="qb-body">
          <div class="qb-tasks" role="group" :aria-label="t('选择查询用途')">
            <button
              v-for="task in tasks"
              :key="task.id"
              type="button"
              :aria-pressed="draft.operation === task.id"
              :class="{ active: draft.operation === task.id }"
              @click="draft.operation = task.id"
            >
              <component :is="task.icon" :size="17" /><span
                ><strong>{{ t(task.label) }}</strong
                ><small>{{ t(task.description) }}</small></span
              >
            </button>
          </div>
          <div class="qb-presets">
            <span>{{ t('快速开始') }}</span
            ><button v-for="[id, label] in presets" :key="id" type="button" @click="preset(id)">
              {{ t(label) }}
            </button>
          </div>
          <section class="qb-section" :aria-label="t('资料范围')">
            <div class="qb-section-heading">
              <h3>{{ t('资料范围') }}</h3>
              <span class="qb-scope">{{ props.scopeLabel || t('当前知识库') }}</span
              ><button
                type="button"
                class="text-button"
                :disabled="draft.filters.length >= 16"
                @click="
                  draft.filters.push({ field: 'filename', op: 'contains', value: '', custom: '' })
                "
              >
                <Plus :size="13" />{{ t('添加条件') }}
              </button>
            </div>
            <div v-if="draft.period" class="qb-period">
              <CalendarDays :size="16" /><label
                >{{ t('月份') }}<input v-model="draft.period.month" type="month" required
              /></label>
              <label
                >{{ t('依据日期')
                }}<select v-model="draft.period.field">
                  <option value="created_date">{{ t('创建日期') }}</option>
                  <option value="authored_date">{{ t('写作 / 发布日期') }}</option>
                  <option value="published_date">{{ t('发布日期') }}</option>
                </select></label
              >
              <button
                type="button"
                class="icon-button"
                :aria-label="t('移除月份限制')"
                @click="draft.period = undefined"
              >
                <X :size="14" />
              </button>
            </div>
            <div v-if="draft.filters.length > 1" class="qb-logic">
              <span>{{ t('这些条件') }}</span
              ><select v-model="draft.logic" :aria-label="t('条件关系')">
                <option value="all">{{ t('需要全部符合') }}</option>
                <option value="any">{{ t('符合其中任一项') }}</option>
              </select>
            </div>
            <div v-if="!draft.filters.length" class="qb-empty">
              {{ t('没有额外条件，将查询当前范围内的全部资料。') }}
            </div>
            <div v-for="(filter, i) in draft.filters" :key="i" class="qb-condition">
              <label
                ><span>{{ t('按什么筛选') }}</span
                ><select
                  v-model="filter.field"
                  :aria-label="t('筛选字段') + ' ' + (i + 1)"
                  @change="fieldChanged(filter)"
                >
                  <option v-for="[key, label] in queryFields" :key="key" :value="key">
                    {{ t(label) }}
                  </option></select
                ><input
                  v-if="filter.field === 'metadata'"
                  v-model="filter.custom"
                  :aria-label="t('自定义字段名称')"
                  :placeholder="t('例如 hours 或工时')"
                  maxlength="64"
              /></label>
              <label
                ><span>{{ t('匹配方式') }}</span
                ><select v-model="filter.op" :aria-label="t('筛选关系') + ' ' + (i + 1)">
                  <option v-for="[op] in operatorsFor(filter.field)" :key="op" :value="op">
                    {{ t(operatorLabel(filter.field, op)) }}
                  </option>
                </select></label
              >
              <label
                ><span>{{ t('条件值') }}</span>
                <select
                  v-if="filter.field === 'kind' && !['missing', 'exists', 'in'].includes(filter.op)"
                  v-model="filter.value"
                  :aria-label="t('筛选值') + ' ' + (i + 1)"
                >
                  <option value="document">{{ t('文档') }}</option>
                  <template v-if="draft.operation !== 'duplicates'"
                    ><option value="image">{{ t('图片') }}</option>
                    <option value="audio">{{ t('音频') }}</option>
                    <option value="video">{{ t('视频') }}</option>
                    <option value="bundle">{{ t('联合素材') }}</option></template
                  >
                </select>
                <input
                  v-else-if="!['missing', 'exists'].includes(filter.op)"
                  v-model="filter.value"
                  :type="inputType(filter)"
                  :aria-label="t('筛选值') + ' ' + (i + 1)"
                  :placeholder="placeholder(filter)"
                  :step="inputType(filter) === 'number' ? 'any' : undefined"
                />
                <span v-else class="qb-value-note">{{
                  t(filter.op === 'missing' ? '查找没有这个属性的资料' : '查找已填写这个属性的资料')
                }}</span>
              </label>
              <button
                type="button"
                class="icon-button qb-remove"
                :aria-label="t('移除条件') + ' ' + (i + 1)"
                @click="draft.filters.splice(i, 1)"
              >
                <X :size="14" />
              </button>
            </div>
            <p
              v-if="
                draft.period ||
                draft.filters.some((f) => f.field.endsWith('_date') || f.field === 'folder_month')
              "
              class="qb-help"
            >
              {{ t('创建、写作、修改和导入日期各有含义，请选择笔记实际标注的日期。') }}
            </p>
          </section>
          <section
            v-if="draft.operation === 'aggregate'"
            class="qb-section"
            :aria-label="t('怎么统计')"
          >
            <div class="qb-section-heading">
              <h3>{{ t('怎么统计') }}</h3>
              <span>{{ t('覆盖全部匹配资料') }}</span>
            </div>
            <div class="qb-fields">
              <label
                >{{ t('计算什么')
                }}<select v-model="draft.metric">
                  <option value="count">{{ t('资料数量') }}</option>
                  <option value="sum">{{ t('数值合计') }}</option>
                  <option value="avg">{{ t('数值平均') }}</option>
                  <option value="min">{{ t('最小数值') }}</option>
                  <option value="max">{{ t('最大数值') }}</option>
                </select></label
              >
              <label v-if="draft.metric !== 'count'"
                >{{ t('数值来源')
                }}<select v-model="numericChoice">
                  <option value="size">{{ t('文件大小（字节）') }}</option>
                  <option value="duration">{{ t('时长（秒）') }}</option>
                  <option value="chunks">{{ t('片段数') }}</option>
                  <option value="custom">{{ t('笔记里的数值字段') }}</option>
                </select></label
              >
              <label v-if="draft.metric !== 'count' && numericChoice === 'custom'"
                >{{ t('字段名称')
                }}<input
                  v-model="draft.metricField"
                  :placeholder="t('例如 hours 或工时')"
                  maxlength="64"
              /></label>
              <label
                >{{ t('分别统计')
                }}<select v-model="draft.group">
                  <option value="">{{ t('只看总计') }}</option>
                  <option value="tags">{{ t('每个标签') }}</option>
                  <option value="month">{{ t('每个月') }}</option>
                  <option value="year">{{ t('每一年') }}</option>
                  <option value="kind">{{ t('每种资料') }}</option>
                  <option value="extension">{{ t('每种文件类型') }}</option>
                  <option value="folder">{{ t('每个文件夹') }}</option>
                </select></label
              >
              <label v-if="['month', 'year'].includes(draft.group)"
                >{{ t('分组依据日期')
                }}<select v-model="draft.date">
                  <option
                    v-for="[key, label] in queryFields.filter(
                      ([key]) => key.endsWith('_date') || key === 'folder_month',
                    )"
                    :key="key"
                    :value="key"
                  >
                    {{ t(label) }}
                  </option>
                </select></label
              >
            </div>
            <p v-if="draft.group === 'tags'" class="qb-help">
              {{ t('一份笔记可以有多个标签，各标签数量相加可能超过资料总数。') }}
            </p>
          </section>
          <section v-if="draft.operation === 'duplicates'" class="qb-section">
            <div class="qb-section-heading">
              <h3>{{ t('比较方式') }}</h3>
              <span>{{ t('仅比较文档笔记') }}</span>
            </div>
            <div class="qb-fields">
              <label
                >{{ t('相似度阈值')
                }}<input
                  v-model.number="draft.threshold"
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  :placeholder="'0.9'"
              /></label>
              <p class="qb-help">
                {{ t('默认 0.9。越高越严格，正文一致的候选仍会保留。不会自动删除资料。') }}
              </p>
            </div>
          </section>
          <details class="qb-options">
            <summary>
              {{ t('更多选项') }}<span>{{ t('排序与展示数量') }}</span
              ><ChevronDown :size="13" />
            </summary>
            <div class="qb-fields">
              <label v-if="draft.operation !== 'duplicates'"
                >{{ t('排序依据')
                }}<select v-model="draft.order">
                  <option v-for="[key, label] in sortFields" :key="key" :value="key">
                    {{ t(label) }}
                  </option>
                </select></label
              >
              <label v-if="draft.operation !== 'duplicates'"
                >{{ t('排列方向')
                }}<select v-model="draft.descending">
                  <option :value="false">{{ t('从小到大') }}</option>
                  <option :value="true">{{ t('从大到小') }}</option>
                </select></label
              >
              <label
                >{{ t('展示前几项')
                }}<input v-model.number="draft.limit" type="number" min="1" max="50"
              /></label>
              <label
                >{{ t('跳过前几项')
                }}<input v-model.number="draft.offset" type="number" min="0" max="10000"
              /></label>
            </div>
            <p class="qb-help">{{ t('展示数量只影响预览，不会缩小统计或比较范围。') }}</p>
          </details>
        </div>
        <footer class="qb-footer">
          <div class="qb-preview" aria-live="polite">
            <span>{{ t('将要执行') }}</span>
            <p>
              <strong>{{ props.scopeLabel || t('当前知识库') }}</strong> · {{ preview }}
            </p>
          </div>
          <p v-if="error" class="inline-error" role="alert">{{ error }}</p>

          <span><ShieldCheck :size="13" />{{ t('本机执行，不调用 API') }}</span
          ><button type="button" class="text-button qb-reset" @click="reset">
            <RotateCcw :size="12" />{{ t('重置') }}</button
          ><button type="button" class="button secondary" @click="dialog?.close()">
            {{ t('取消') }}</button
          ><button class="button primary" :disabled="props.disabled">
            {{ t(action) }}<ArrowRight :size="14" />
          </button>
        </footer>
      </form>
    </dialog>
  </Teleport>
</template>
