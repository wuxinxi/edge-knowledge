import { expect, it } from 'vitest'
import { join } from 'node:path'
import { backendCommand } from './backend-path'

it('selects Windows venv executables and packaged exe instead of Unix paths', () => {
  expect(backendCommand('/repo', '/resources', false, 'win32')).toBe(
    join('/repo', 'backend/.venv/Scripts/python.exe'),
  )
  expect(backendCommand('/repo', '/resources', true, 'win32')).toBe(
    join('/resources', 'backend/server.exe'),
  )
})
it('retains macOS and Linux executable paths', () => {
  for (const platform of ['darwin', 'linux'] as const) {
    expect(backendCommand('/repo', '/resources', false, platform)).toBe(
      join('/repo', 'backend/.venv/bin/python'),
    )
    expect(backendCommand('/repo', '/resources', true, platform)).toBe(
      join('/resources', 'backend/server'),
    )
  }
})
