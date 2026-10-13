/** Present YAML as metadata; preserve source.text for copying and saved evidence. */
export function sourcePreview(text: string) {
  const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/)
  if (
    lines[0]?.trim() !== '---' ||
    !lines.slice(1).some((line) => /^[\w\u4e00-\u9fff-]+:\s*/u.test(line))
  )
    return { body: text, metadata: [] as { label: string; value: string }[] }
  const end = lines.findIndex((line, index) => index > 0 && /^(---|\.\.\.)\s*$/.test(line))
  const labels: Record<string, string> = {
    title: '标题',
    date: '日期',
    createdAt: '创建日期',
    created: '创建日期',
    created_at: '创建日期',
    updatedAt: '修改日期',
    updated: '修改日期',
    updated_at: '修改日期',
    publishedAt: '发布日期',
    publishDate: '发布日期',
  }
  const metadata = lines.slice(1, end < 0 ? undefined : end).flatMap((line) => {
    const match = /^([^\s:]+):\s*(.+)$/.exec(line)
    if (!match || !labels[match[1]!]) return []
    return [
      { label: labels[match[1]!]!, value: match[2]!.replace(/^["']|["']$/g, '').slice(0, 180) },
    ]
  })
  return {
    body:
      end < 0
        ? ''
        : lines
            .slice(end + 1)
            .join('\n')
            .trim(),
    metadata,
  }
}
