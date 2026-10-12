/** Incremental SSE decoding: UTF-8, CRLF, multiline data, and incomplete frames. */
export async function* readSSE<T>(body: ReadableStream<Uint8Array>): AsyncGenerator<T> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let data: string[] = []
  function line(value: string): T | undefined {
    if (value === '') {
      if (!data.length) return undefined
      const payload = data.join('\n')
      data = []
      return JSON.parse(payload) as T
    }
    if (value.startsWith('data:')) data.push(value.slice(5).replace(/^ /, ''))
    return undefined
  }
  try {
    while (true) {
      const { done, value } = await reader.read()
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
      let newline: number
      while ((newline = buffer.indexOf('\n')) !== -1) {
        const event = line(buffer.slice(0, newline).replace(/\r$/, ''))
        buffer = buffer.slice(newline + 1)
        if (event !== undefined) yield event
      }
      if (done) break
    }
    // Per SSE framing, an event without a final blank line is incomplete and discarded.
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
