import { spawn, type ChildProcess } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { createInterface } from 'node:readline'

export interface BackendSession {
  baseUrl: string
  token: string
}

export class BackendProcess {
  private child: ChildProcess | undefined
  private stopping = false

  async start(
    root: string,
    dataDir: string,
    resources: string,
    packaged: boolean,
    onFailure: () => void,
  ): Promise<BackendSession> {
    const command = packaged
      ? join(resources, 'backend/server')
      : join(root, 'backend/.venv/bin/python')
    if (!existsSync(command)) {
      throw new Error(
        '后端运行环境未安装。请在项目目录执行 uv sync --project backend --extra embedding --extra ocr。',
      )
    }
    const token = randomBytes(32).toString('hex')
    const child = spawn(command, packaged ? [] : ['-m', 'edge_knowledge'], {
      cwd: packaged ? dataDir : root,
      env: {
        ...process.env,
        EDGE_BACKEND_TOKEN: token,
        EDGE_PORT: '0',
        EDGE_DATA_DIR: dataDir,
        EDGE_PREPARED_MODEL_DIR:
          process.env.EDGE_PREPARED_MODEL_DIR ||
          join(packaged ? dataDir : join(root, 'data'), 'models/embeddinggemma-2'),
        EDGE_RENDERER_ORIGIN: packaged
          ? ''
          : new URL(process.env.ELECTRON_RENDERER_URL || 'http://localhost:5173').origin,
        PYTHONUNBUFFERED: '1',
        HF_HOME: join(dataDir, 'models'),
        ANONYMIZED_TELEMETRY: 'False',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    this.child = child
    // Keep startup diagnostics out of the renderer and avoid logging keys or document text.
    child.stderr?.on('data', () => {})
    const session = await new Promise<BackendSession>((resolve, reject) => {
      const timeout = setTimeout(() => {
        cleanup()
        reject(new Error('本地服务启动超时，请检查后端依赖。'))
      }, 45_000)
      const lines = createInterface({ input: child.stdout! })
      const onExit = () => {
        cleanup()
        reject(new Error('本地服务启动失败，请检查后端依赖与配置。'))
      }
      const onError = () => {
        cleanup()
        reject(new Error('无法启动本地服务。'))
      }
      const cleanup = () => {
        clearTimeout(timeout)
        lines.close()
        child.off('exit', onExit)
        child.off('error', onError)
      }
      child.once('exit', onExit)
      child.once('error', onError)
      lines.on('line', (line) => {
        try {
          const message = JSON.parse(line)
          if (
            message.event === 'backend_ready' &&
            Number.isInteger(message.port) &&
            message.port > 0 &&
            message.port < 65536
          ) {
            cleanup()
            resolve({ baseUrl: `http://127.0.0.1:${message.port}`, token })
          }
        } catch {
          /* Third-party startup output is not a control message. */
        }
      })
    })
    child.once('exit', () => {
      if (!this.stopping) onFailure()
    })
    for (let attempt = 0; attempt < 60; attempt++) {
      if (child.exitCode !== null || child.signalCode !== null) throw new Error('本地服务已停止。')
      try {
        const result = await fetch(`${session.baseUrl}/api/health`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: AbortSignal.timeout(1000),
        })
        if (result.ok) return session
      } catch {
        /* The process bound its socket before entering the serving loop. */
      }
      await new Promise((resolve) => setTimeout(resolve, 250))
    }
    throw new Error('本地服务未能完成健康检查。')
  }

  async stop(): Promise<void> {
    this.stopping = true
    const child = this.child
    if (!child || child.exitCode !== null || child.signalCode !== null) return
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => child.kill('SIGKILL'), 5000)
      child.once('exit', () => {
        clearTimeout(timer)
        resolve()
      })
      child.kill('SIGTERM')
    })
  }
}
