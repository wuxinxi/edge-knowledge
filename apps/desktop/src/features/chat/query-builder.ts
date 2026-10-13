import type { QueryFilter, QuerySpec } from '../../shared/types/query'
export const queryFields = [
  ['title', '标题'],
  ['filename', '文件名'],
  ['path', '相对路径'],
  ['kind', '资料类型'],
  ['extension', '文件类型'],
  ['tags', '标签'],
  ['text', '全文文字'],
  ['authored_date', '写作 / 发布日期'],
  ['created_date', '创建日期'],
  ['published_date', '发布日期'],
  ['modified_date', '修改日期'],
  ['imported_date', '导入日期'],
  ['folder_month', '目录归档月份'],
  ['size', '文件大小（字节）'],
  ['duration', '时长（秒）'],
  ['chunks', '片段数'],
  ['metadata', '自定义笔记字段'],
] as const
export interface FilterDraft {
  field: string
  op: NonNullable<QueryFilter['op']>
  value: string | number
  custom: string
}
export interface QueryDraft {
  operation: 'list' | 'aggregate' | 'duplicates'
  period?: { month: string; field: string }
  threshold?: number
  logic: 'all' | 'any'
  filters: FilterDraft[]
  metric: NonNullable<QuerySpec['metric']>
  metricField: string
  group: NonNullable<QuerySpec['group_by']>
  date: string
  order: string
  descending: boolean
  limit: number
  offset: number
}
export function monthRange(month: string) {
  if (!/^\d{4}-\d{2}$/.test(month)) throw new Error('请选择有效月份。')
  const [year, number] = month.split('-').map(Number) as [number, number]
  if (year < 1 || number < 1 || number > 12 || (year === 9999 && number === 12))
    throw new Error('请选择有效月份。')
  return [
    `${month}-01`,
    `${String(number === 12 ? year + 1 : year).padStart(4, '0')}-${String(number === 12 ? 1 : number + 1).padStart(2, '0')}-01`,
  ]
}
export function defaultQueryDraft(): QueryDraft {
  return {
    operation: 'aggregate',
    logic: 'all',
    filters: [{ field: 'kind', op: 'eq', value: 'document', custom: '' }],
    metric: 'count',
    metricField: 'size',
    group: '',
    date: 'created_date',
    order: 'title',
    descending: false,
    limit: 20,
    offset: 0,
  }
}
export const queryOperators = [
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
export function operatorsFor(field: string) {
  if (field === 'kind')
    return queryOperators.filter(([op]) => ['eq', 'ne', 'exists', 'missing'].includes(op))
  if (
    field.endsWith('_date') ||
    field === 'folder_month' ||
    ['size', 'duration', 'chunks'].includes(field)
  )
    return queryOperators.filter(([op]) => op !== 'contains')
  if (field === 'metadata') return queryOperators
  return queryOperators.filter(([op]) => !['gte', 'gt', 'lte', 'lt'].includes(op))
}
export function operatorLabel(field: string, op: string) {
  const dates: Record<string, string> = { gte: '不早于', gt: '晚于', lte: '不晚于', lt: '早于' }
  return (
    ((field.endsWith('_date') || field === 'folder_month') && dates[op]) ||
    queryOperators.find(([key]) => key === op)?.[1] ||
    op
  )
}
export function applyQueryPreset(
  draft: QueryDraft,
  preset: 'month' | 'tags' | 'undated' | 'duplicates',
  month: string,
) {
  Object.assign(draft, defaultQueryDraft(), { period: undefined, threshold: undefined })
  if (preset === 'month') draft.period = { field: 'created_date', month }
  if (preset === 'tags') {
    draft.group = 'tags'
    draft.order = 'count'
    draft.descending = true
  }
  if (preset === 'undated') {
    draft.operation = 'list'
    draft.filters.push({ field: 'created_date', op: 'missing', value: '', custom: '' })
  }
  if (preset === 'duplicates') {
    draft.operation = 'duplicates'
    draft.threshold = 0.9
  }
}
export function buildQuery(draft: QueryDraft): QuerySpec {
  if (
    !Number.isInteger(draft.limit) ||
    draft.limit < 1 ||
    draft.limit > 50 ||
    !Number.isInteger(draft.offset) ||
    draft.offset < 0 ||
    draft.offset > 10000
  )
    throw new Error('展示数量需要 1–50，跳过数量需要 0–10000 的整数。')
  if (
    draft.operation === 'duplicates' &&
    (!Number.isFinite(draft.threshold ?? 0.9) ||
      (draft.threshold ?? 0.9) < 0 ||
      (draft.threshold ?? 0.9) > 1)
  )
    throw new Error('相似度需要 0–1 的有效数值。')
  if (draft.operation === 'aggregate' && draft.metric !== 'count' && !draft.metricField.trim())
    throw new Error('请填写需要统计的字段名称。')
  const filters = draft.filters.map((row): QueryFilter => {
    const field = row.field === 'metadata' ? `metadata.${row.custom.trim()}` : row.field
    if (!field || field === 'metadata.') throw new Error('请填写自定义字段名称。')
    if (['exists', 'missing'].includes(row.op)) return { field, op: row.op }
    const input = String(row.value ?? '').trim()
    if (!input) throw new Error('请填写每个筛选条件的值，或移除空条件。')
    const numeric =
      ['size', 'duration', 'chunks'].includes(field) ||
      (field.startsWith('metadata.') && ['gt', 'gte', 'lt', 'lte'].includes(row.op))
    const scalar = (raw: string) => {
      const value = numeric ? Number(raw) : raw.trim()
      if (numeric && !Number.isFinite(value)) throw new Error('数值条件格式无效。')
      return value
    }
    if (row.op === 'in' && !input.split(/[,，]/).some((v) => v.trim()))
      throw new Error('请至少填写一个条件值。')
    return {
      field,
      op: row.op,
      value:
        row.op === 'in'
          ? input
              .split(/[,，]/)
              .map((v) => v.trim())
              .filter(Boolean)
              .map(scalar)
          : scalar(input),
    }
  })
  let where: QueryFilter = { [draft.logic]: filters }
  if (draft.period) {
    const [start, end] = monthRange(draft.period.month)
    where = {
      all: [
        where,
        { field: draft.period.field, op: 'gte', value: start! },
        { field: draft.period.field, op: 'lt', value: end! },
      ],
    }
  }
  const aggregate = draft.operation === 'aggregate'
  const grouped = aggregate && !!draft.group
  return {
    version: 1,
    operation: draft.operation,
    where,
    metric: aggregate ? draft.metric : 'count',
    metric_field:
      !aggregate || draft.metric === 'count'
        ? 'size'
        : ['size', 'duration', 'chunks'].includes(draft.metricField.trim()) ||
            draft.metricField.startsWith('metadata.')
          ? draft.metricField.trim()
          : `metadata.${draft.metricField.trim()}`,
    group_by: draft.operation === 'aggregate' ? draft.group : '',
    group_date: draft.date,
    order_by: !grouped && ['key', 'value', 'count'].includes(draft.order) ? 'title' : draft.order,
    descending: draft.descending,
    limit: draft.limit,
    offset: draft.offset,
    ...(draft.operation === 'duplicates' ? { threshold: draft.threshold ?? 0.9 } : {}),
  }
}
export function queryLabel(draft: QueryDraft, t: (value: string) => string = (value) => value) {
  const action =
    draft.operation === 'duplicates'
      ? '检查重复笔记'
      : draft.operation === 'list'
        ? '筛选资料'
        : {
            count: '统计资料数量',
            sum: '计算合计',
            avg: '计算平均值',
            min: '查询最小值',
            max: '查询最大值',
          }[draft.metric]
  const fieldLabel =
    queryFields.find(([key]) => key === draft.metricField)?.[1] ??
    draft.metricField.replace(/^metadata\./, '')
  const groupLabels: Record<string, string> = {
    month: '按月',
    year: '按年',
    kind: '按资料类型',
    tags: '按标签',
    folder: '按文件夹',
    extension: '按文件类型',
  }
  const groupLabel = draft.operation === 'aggregate' ? (groupLabels[draft.group] ?? '') : ''
  const metricLabel =
    draft.operation === 'aggregate' && draft.metric !== 'count' ? ' ' + fieldLabel : ''
  const kindLabels: Record<string, string> = {
    document: '文档',
    image: '图片',
    audio: '音频',
    video: '视频',
    bundle: '联合素材',
  }
  const conditions = draft.filters.map((row) => {
    const field =
      row.field === 'metadata'
        ? row.custom
        : (queryFields.find(([key]) => key === row.field)?.[1] ?? row.field)
    const value = row.field === 'kind' ? t(kindLabels[row.value] ?? row.value) : row.value
    return `${t(field)} ${t(operatorLabel(row.field, row.op))}${['missing', 'exists'].includes(row.op) ? '' : ' ' + value}`
  })
  const period = draft.period
    ? `${t(queryFields.find(([key]) => key === draft.period!.field)?.[1] ?? draft.period.field)} ${draft.period.month}`
    : ''
  const joined = conditions.join(` ${t(draft.logic === 'all' ? '且' : '或')} `)
  const conditionText = draft.logic === 'any' && conditions.length > 1 ? `(${joined})` : joined
  return (
    [t(groupLabel), t(action), metricLabel ? t(fieldLabel) : ''].filter(Boolean).join(' ') +
    t('：') +
    [period, conditions.length ? conditionText : t('当前资料范围')]
      .filter(Boolean)
      .join(` ${t('且')} `)
  )
}
