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
  value: string
  custom: string
}
export interface QueryDraft {
  operation: 'list' | 'aggregate' | 'duplicates'
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
export function buildQuery(draft: QueryDraft): QuerySpec {
  if (draft.operation === 'aggregate' && draft.metric !== 'count' && !draft.metricField.trim())
    throw new Error('请填写需要统计的字段名称。')
  const filters = draft.filters.map((row): QueryFilter => {
    const field = row.field === 'metadata' ? `metadata.${row.custom.trim()}` : row.field
    if (!field || field === 'metadata.') throw new Error('请填写自定义字段名称。')
    if (['exists', 'missing'].includes(row.op)) return { field, op: row.op }
    if (!row.value.trim()) throw new Error('请填写每个筛选条件的值，或移除空条件。')
    const numeric =
      ['size', 'duration', 'chunks'].includes(field) ||
      (field.startsWith('metadata.') && ['gt', 'gte', 'lt', 'lte'].includes(row.op))
    const scalar = (raw: string) => {
      const value = numeric ? Number(raw) : raw.trim()
      if (numeric && !Number.isFinite(value)) throw new Error('数值条件格式无效。')
      return value
    }
    return {
      field,
      op: row.op,
      value:
        row.op === 'in'
          ? row.value
              .split(/[,，]/)
              .map((v) => v.trim())
              .filter(Boolean)
              .map(scalar)
          : scalar(row.value),
    }
  })
  return {
    version: 1,
    operation: draft.operation,
    where: { [draft.logic]: filters },
    metric: draft.metric,
    metric_field:
      draft.metric === 'count'
        ? 'size'
        : ['size', 'duration', 'chunks'].includes(draft.metricField.trim()) ||
            draft.metricField.startsWith('metadata.')
          ? draft.metricField.trim()
          : `metadata.${draft.metricField.trim()}`,
    group_by: draft.operation === 'aggregate' ? draft.group : '',
    group_date: draft.date,
    order_by: draft.order,
    descending: draft.descending,
    limit: draft.limit,
    offset: draft.offset,
  }
}
export function queryLabel(draft: QueryDraft) {
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
  const conditions = draft.filters.map(
    (row) =>
      `${queryFields.find(([key]) => key === row.field)?.[1] ?? row.field} ${row.op === 'missing' ? '未标注' : row.op === 'exists' ? '已标注' : row.field === 'kind' ? (kindLabels[row.value] ?? row.value) : row.value}`,
  )
  return (
    groupLabel +
    action +
    metricLabel +
    (conditions.length
      ? '：' + conditions.join(draft.logic === 'all' ? '，' : ' 或 ')
      : '：当前资料范围')
  )
}
