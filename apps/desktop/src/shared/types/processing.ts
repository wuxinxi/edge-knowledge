export const chatStages = [
  'waiting',
  'querying',
  'validating',
  'planning',
  'retrieving',
  'executing',
  'comparing',
  'preparing',
  'generating',
  'presenting',
] as const
export type ChatStage = (typeof chatStages)[number]
export interface ChatProcessing {
  startedAt: number
  finishedAt?: number
  steps: { stage: ChatStage; startedAt: number }[]
}
export const stageLabels: Record<ChatStage, string> = {
  waiting: '连接本地服务',
  querying: '执行本地查询',
  validating: '检查资料范围',
  planning: '理解问题',
  retrieving: '检索相关资料',
  executing: '筛选与计算',
  comparing: '比较笔记正文',
  preparing: '整理回答依据',
  generating: '生成回答',
  presenting: '展示查询结果',
}
