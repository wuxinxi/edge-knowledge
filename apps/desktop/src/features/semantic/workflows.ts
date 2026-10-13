import type { MediaKind } from '../../shared/types/api'
export type Workflow = 'images' | 'media' | 'mixed' | 'collect' | 'organize'
export const workflows = [
  {
    id: 'images',
    title: '找相似图片',
    description: '放一张参考图，或描述想找的画面',
    heading: '你想找什么图片？',
    placeholder: '例如：蓝色背景的产品图、快递票据…',
    action: '查找图片',
    accept: '.png,.jpg,.jpeg,.webp',
  },
  {
    id: 'media',
    title: '找音视频片段',
    description: '描述内容，找到可播放的时间片段',
    heading: '你想找哪段内容？',
    placeholder: '例如：讨论项目进度的录音、出现海浪的片段…',
    action: '查找片段',
    accept: '.wav,.mp3,.m4a,.aac,.flac,.ogg,.mp4,.mov,.mkv,.webm',
  },
  {
    id: 'mixed',
    title: '组合查找',
    description: '一起使用文字、图片与一段音视频',
    heading: '用这些素材一起查找',
    placeholder: '补充你希望匹配的内容或条件…',
    action: '查找相关资料',
    accept:
      '.txt,.md,.pdf,.docx,.png,.jpg,.jpeg,.webp,.wav,.mp3,.m4a,.aac,.flac,.ogg,.mp4,.mov,.mkv,.webm',
  },
  {
    id: 'collect',
    title: '收集一组素材',
    description: '把说明和相关文件保存为一份资料',
    heading: '把相关素材放在一起',
    placeholder: '描述这组资料的用途、主题或背景…',
    action: '保存到知识库',
    accept:
      '.txt,.md,.pdf,.docx,.png,.jpg,.jpeg,.webp,.wav,.mp3,.m4a,.aac,.flac,.ogg,.mp4,.mov,.mkv,.webm',
  },
  {
    id: 'organize',
    title: '整理已有资料',
    description: '分类建议、内容分组、查找重复',
    heading: '选择你想做的整理',
    placeholder: '',
    action: '开始整理',
    accept: '',
  },
] as const
export function inputIssue(flow: Workflow, files: Pick<File, 'name' | 'size'>[]): string {
  if (files.length > 12) return '一次最多添加 12 份素材。'
  let media = 0,
    bytes = 0
  for (const file of files) {
    const suffix = file.name.split('.').at(-1)?.toLowerCase() ?? ''
    const isMedia = /^(wav|mp3|m4a|aac|flac|ogg|mp4|mov|mkv|webm)$/.test(suffix)
    if (flow === 'images' && !/^(png|jpg|jpeg|webp)$/.test(suffix))
      return '找图片只接受参考图片，请移除其他文件或切换到组合查找。'
    if (flow === 'media' && !isMedia)
      return '此入口接受音视频参考文件，请移除其他文件或切换到组合查找。'
    if (
      !/^(txt|md|pdf|docx|png|jpg|jpeg|webp|wav|mp3|m4a|aac|flac|ogg|mp4|mov|mkv|webm)$/.test(
        suffix,
      )
    )
      return '此文件格式暂不支持。'
    if (isMedia) media++
    if (file.size > (isMedia ? 200 : 20) * 1024 * 1024)
      return '文档和图片上限 20 MB，音视频上限 200 MB。'
    bytes += file.size
  }
  if (media > 1) return '一次只能组合一段音视频；多份媒体请分别导入知识库。'
  if (bytes > 240 * 1024 * 1024) return '这组素材超过 240 MB，请分开处理。'
  return ''
}
export function targetKinds(flow: Workflow, kind: MediaKind | ''): MediaKind[] {
  return kind ? [kind] : flow === 'media' ? ['audio', 'video'] : []
}
