<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { SlidersHorizontal, Plus, X, ArrowRight, ShieldCheck } from '@lucide/vue'
import { buildQuery, queryFields, queryLabel, type QueryDraft } from './query-builder'
import type { QuerySpec } from '../../shared/types/query'
import { useI18n } from '../../shared/i18n'
const props = defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ execute: [plan: QuerySpec, label: string] }>()
const { t } = useI18n()
const dialog = ref<HTMLDialogElement>()
const error = ref('')
const numericChoice = ref('size')
const draft = reactive<QueryDraft>({
  operation: 'aggregate',
  logic: 'all',
  filters: [{ field: 'kind', op: 'eq', value: 'document', custom: '' }],
  metric: 'count',
  metricField: 'size',
  group: '',
  date: 'authored_date',
  order: 'title',
  descending: false,
  limit: 20,
  offset: 0,
})
watch(numericChoice, (value) => {
  draft.metricField = value === 'custom' ? '' : value
})
const operators = [
  ['eq', '等于'],
  ['ne', '不等于'],
  ['contains', '包含'],
  ['in', '属于任一'],
  ['gte', '大于或等于'],
  ['gt', '大于'],
  ['lte', '小于或等于'],
  ['lt', '小于'],
  ['exists', '已标注'],
  ['missing', '未标注'],
] as const
function execute() {
  try {
    const plan = buildQuery(draft)
    error.value = ''
    dialog.value?.close()
    emit('execute', plan, queryLabel(draft))
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t('请检查筛选条件。')
  }
}
</script>
<template>
  <button
    class="query-builder-trigger text-button"
    type="button"
    :disabled="props.disabled"
    @click="dialog?.showModal()"
  >
    <SlidersHorizontal :size="13" />{{ t('筛选与统计') }}
  </button>
  <Teleport to="body"
    ><dialog ref="dialog" class="action-dialog query-builder-dialog" :aria-label="t('筛选与统计')">
      <header class="query-builder-heading">
        <div>
          <h2>{{ t('筛选与统计') }}</h2>
          <p>{{ t('组合条件，从本地资料中获得准确结果。') }}</p>
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
        <div class="query-builder-row">
          <label
            >{{ t('操作')
            }}<select v-model="draft.operation">
              <option value="list">{{ t('筛选资料') }}</option>
              <option value="aggregate">{{ t('统计与计算') }}</option>
            </select></label
          >
          <label
            >{{ t('条件关系')
            }}<select v-model="draft.logic">
              <option value="all">{{ t('同时符合全部条件') }}</option>
              <option value="any">{{ t('符合任一条件') }}</option>
            </select></label
          >
        </div>
        <div class="query-builder-filters">
          <div v-for="(filter, i) in draft.filters" :key="i" class="query-filter-row">
            <select v-model="filter.field" :aria-label="t('筛选字段') + ' ' + (i + 1)">
              <option v-for="[key, label] in queryFields" :key="key" :value="key">
                {{ t(label) }}
              </option>
            </select>
            <input
              v-if="filter.field === 'metadata'"
              v-model="filter.custom"
              :aria-label="t('自定义字段名称')"
              :placeholder="t('例如 hours')"
              maxlength="64"
            />
            <select v-model="filter.op" :aria-label="t('筛选关系') + ' ' + (i + 1)">
              <option v-for="[key, label] in operators" :key="key" :value="key">
                {{ t(label) }}
              </option>
            </select>
            <select
              v-if="filter.field === 'kind' && !['missing', 'exists'].includes(filter.op)"
              v-model="filter.value"
              :aria-label="t('筛选值') + ' ' + (i + 1)"
            >
              <option value="document">{{ t('文档') }}</option>
              <option value="image">{{ t('图片') }}</option>
              <option value="audio">{{ t('音频') }}</option>
              <option value="video">{{ t('视频') }}</option>
              <option value="bundle">{{ t('联合素材') }}</option>
            </select>
            <input
              v-else-if="!['missing', 'exists'].includes(filter.op)"
              v-model="filter.value"
              :type="
                filter.field.endsWith('_date')
                  ? 'date'
                  : filter.field === 'folder_month'
                    ? 'month'
                    : 'text'
              "
              :aria-label="t('筛选值') + ' ' + (i + 1)"
              :placeholder="filter.op === 'in' ? t('多个值用逗号分隔') : t('输入条件值')"
            />
            <button
              type="button"
              class="icon-button"
              :aria-label="t('移除条件') + ' ' + (i + 1)"
              @click="draft.filters.splice(i, 1)"
            >
              <X :size="14" />
            </button>
          </div>
          <button
            type="button"
            class="text-button"
            :disabled="draft.filters.length >= 16"
            @click="
              draft.filters.push({ field: 'authored_date', op: 'gte', value: '', custom: '' })
            "
          >
            <Plus :size="13" />{{ t('添加条件') }}
          </button>
        </div>
        <div v-if="draft.operation === 'aggregate'" class="query-builder-row">
          <label
            >{{ t('统计方式')
            }}<select v-model="draft.metric">
              <option value="count">{{ t('文档数量') }}</option>
              <option value="sum">{{ t('合计') }}</option>
              <option value="avg">{{ t('平均值') }}</option>
              <option value="min">{{ t('最小值') }}</option>
              <option value="max">{{ t('最大值') }}</option>
            </select></label
          >
          <label v-if="draft.metric !== 'count'"
            >{{ t('数值字段')
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
            >{{ t('分组')
            }}<select v-model="draft.group">
              <option value="">{{ t('不分组') }}</option>
              <option value="month">{{ t('按月') }}</option>
              <option value="year">{{ t('按年') }}</option>
              <option value="kind">{{ t('资料类型') }}</option>
              <option value="extension">{{ t('文件类型') }}</option>
              <option value="tags">{{ t('标签') }}</option>
              <option value="folder">{{ t('文件夹') }}</option>
            </select></label
          >
          <label v-if="['month', 'year'].includes(draft.group)"
            >{{ t('日期口径')
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
        <details class="query-builder-options">
          <summary>{{ t('排序与展示') }}</summary>
          <div class="query-builder-row">
            <label
              >{{ t('排序')
              }}<select v-model="draft.order">
                <option
                  v-for="[key, label] in queryFields.filter(
                    ([key]) => !['metadata', 'text', 'tags'].includes(key),
                  )"
                  :key="key"
                  :value="key"
                >
                  {{ t(label) }}
                </option>
              </select></label
            ><label
              >{{ t('方向')
              }}<select v-model="draft.descending">
                <option :value="false">{{ t('从小到大') }}</option>
                <option :value="true">{{ t('从大到小') }}</option>
              </select></label
            ><label
              >{{ t('每次展示')
              }}<input v-model.number="draft.limit" type="number" min="1" max="50" /></label
            ><label
              >{{ t('跳过前几项')
              }}<input v-model.number="draft.offset" type="number" min="0" max="10000"
            /></label>
          </div>
        </details>
        <p class="query-builder-note">
          <ShieldCheck :size="14" />{{
            t('本机执行，不调用 API。修改日期、导入日期和目录月份不代表写作日期。')
          }}
        </p>
        <p v-if="error" class="inline-error" role="alert">{{ t(error) }}</p>
        <footer class="query-builder-actions">
          <button type="button" class="secondary" @click="dialog?.close()">{{ t('取消') }}</button
          ><button class="primary" :disabled="props.disabled">
            {{ t('查看结果') }}<ArrowRight :size="14" />
          </button>
        </footer>
      </form></dialog
  ></Teleport>
</template>
