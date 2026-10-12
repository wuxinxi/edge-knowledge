import { describe, expect, it } from 'vitest'
import { readSSE } from './sse'

function stream(parts: Uint8Array[]) {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      parts.forEach((part) => controller.enqueue(part))
      controller.close()
    },
  })
}

async function collect(body: ReadableStream<Uint8Array>) {
  const events: unknown[] = []
  for await (const event of readSSE(body)) events.push(event)
  return events
}

describe('SSE transport', () => {
  it('preserves UTF-8 and CRLF even when every byte arrives separately', async () => {
    const bytes = new TextEncoder().encode(
      ': keepalive\r\ndata: {"delta":"知识库"}\r\n\r\ndata: {"type":"done"}\n\n',
    )
    const parts = Array.from(bytes, (byte) => new Uint8Array([byte]))
    expect(await collect(stream(parts))).toEqual([{ delta: '知识库' }, { type: 'done' }])
  })
  it('does not replay frames across network reads', async () => {
    const encoder = new TextEncoder()
    const parts = ['data: {"delta":"a"}\n\n', 'data: {"del', 'ta":"b"}\n\n'].map((text) =>
      encoder.encode(text),
    )
    expect(await collect(stream(parts))).toEqual([{ delta: 'a' }, { delta: 'b' }])
  })
  it('supports multiline data and ignores event metadata', async () => {
    const text = 'event: delta\nid: 4\ndata: {\ndata: "delta":"ok"}\n\n'
    expect(await collect(stream([new TextEncoder().encode(text)]))).toEqual([{ delta: 'ok' }])
  })
  it('discards an unfinished event on disconnect', async () => {
    expect(
      await collect(stream([new TextEncoder().encode('data: {"delta":"incomplete"}\n')])),
    ).toEqual([])
  })
  it('cancels the reader when the caller stops generation', async () => {
    let cancelled = false
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: {"delta":"a"}\n\n'))
      },
      cancel() {
        cancelled = true
      },
    })
    for await (const _event of readSSE(body)) break
    expect(cancelled).toBe(true)
    expect(body.locked).toBe(false)
  })
})
