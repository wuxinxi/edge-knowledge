import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, it } from 'vitest'
import { BackendProcess } from './backend'

it('starts a real isolated backend, authenticates health, and terminates it on exit', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'edge-knowledge-process-'))
  const process = new BackendProcess()
  let failure = false
  try {
    const session = await process.start(globalThis.process.cwd(), directory, '', false, () => {
      failure = true
    })
    const health = await fetch(`${session.baseUrl}/api/health`, {
      headers: { Authorization: `Bearer ${session.token}` },
    })
    expect(health.status).toBe(200)
    expect((await health.json()).embedding_loaded).toBe(false)
    expect((await fetch(`${session.baseUrl}/api/health`)).status).toBe(401)
    await process.stop()
    await expect(fetch(`${session.baseUrl}/api/health`)).rejects.toThrow()
    expect(failure).toBe(false)
  } finally {
    await process.stop()
    await rm(directory, { recursive: true, force: true })
  }
}, 60_000)
