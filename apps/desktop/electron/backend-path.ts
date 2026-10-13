import { join } from 'node:path'

export function backendCommand(
  root: string,
  resources: string,
  packaged: boolean,
  platform = process.platform,
): string {
  return packaged
    ? join(resources, 'backend', platform === 'win32' ? 'server.exe' : 'server')
    : join(
        root,
        'backend',
        '.venv',
        platform === 'win32' ? 'Scripts' : 'bin',
        platform === 'win32' ? 'python.exe' : 'python',
      )
}
