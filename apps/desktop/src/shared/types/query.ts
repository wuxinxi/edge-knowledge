export type QueryOperation = 'list' | 'aggregate' | 'search' | 'answer' | 'clarify' | 'duplicates'
export const queryResultKinds = [
  'retrieval',
  'catalog',
  'clarification',
  'comparison',
  'answer',
] as const
export type QueryResultKind = (typeof queryResultKinds)[number]
export interface QueryFilter {
  field?: string
  op?: 'eq' | 'ne' | 'contains' | 'in' | 'gt' | 'gte' | 'lt' | 'lte' | 'exists' | 'missing'
  value?: string | number | boolean | (string | number | boolean)[] | null
  all?: QueryFilter[]
  any?: QueryFilter[]
}
export interface QuerySpec {
  version?: 1
  operation: QueryOperation
  where?: QueryFilter
  metric?: 'count' | 'sum' | 'avg' | 'min' | 'max'
  metric_field?: string
  group_by?: '' | 'month' | 'year' | 'kind' | 'extension' | 'tags' | 'folder'
  group_date?: string
  order_by?: string
  descending?: boolean
  limit?: number
  offset?: number
  text_query?: string
  clarification?: string
  threshold?: number
}
