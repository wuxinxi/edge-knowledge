/** A long result being visible is not evidence that the user wants to follow it. */
export function followsLatest(distanceToBottom: number, resultTop?: number) {
  return distanceToBottom < 80 || (resultTop !== undefined && Math.abs(resultTop - 16) < 24)
}
