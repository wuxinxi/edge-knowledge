export function toggleVisibleSelection(selected: string[], visible: string[]): string[] {
  const next = new Set(selected)
  if (visible.length && visible.every((id) => next.has(id)))
    visible.forEach((id) => next.delete(id))
  else visible.forEach((id) => next.add(id))
  return [...next]
}
