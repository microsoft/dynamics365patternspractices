/**
 * Vite plugin: start/stop the local FastAPI runner with the UI so users do not
 * need a second terminal (`npm run runner`).
 *
 * Always (re)starts an owned uvicorn with --reload so writer/code changes are
 * picked up. A stale process on :8787 is terminated first.
 */
import { execSync, spawn } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const RUNNER_DIR = path.join(ROOT, 'runner')
const HOST = '127.0.0.1'
const PORT = 8787
const HEALTH = `http://${HOST}:${PORT}/health`
const ENV_FILE = path.join(ROOT, 'bpctool.env')

/** BPCTOOL_* settings from bpctool.env; real environment variables win. */
export function parseEnvFile(text) {
  const values = {}
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq <= 0) continue
    const key = line.slice(0, eq).trim()
    if (!key.startsWith('BPCTOOL_')) continue
    let value = line.slice(eq + 1).trim()
    if (value.length >= 2 && (value[0] === '"' || value[0] === "'") && value.at(-1) === value[0]) {
      value = value.slice(1, -1)
    }
    if (value) values[key] = value
  }
  return values
}

function runnerEnv(logger = console) {
  if (!existsSync(ENV_FILE)) {
    return { ...process.env }
  }
  const fromFile = parseEnvFile(readFileSync(ENV_FILE, 'utf8'))
  const keys = Object.keys(fromFile)
  if (keys.length) {
    logger.info?.(`[bpc-runner] Loaded ${keys.join(', ')} from bpctool.env`)
  }
  return { ...fromFile, ...process.env }
}

function resolveUvicorn() {
  const candidates = [
    path.join(ROOT, '.venv', 'bin', 'uvicorn'),
    path.join(ROOT, '.venv', 'Scripts', 'uvicorn.exe'),
  ]
  return candidates.find((candidate) => existsSync(candidate)) || null
}

function waitForHealth(timeoutMs = 20000) {
  const started = Date.now()
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(HEALTH, (res) => {
        res.resume()
        if (res.statusCode === 200) {
          resolve()
          return
        }
        retry()
      })
      req.on('error', retry)
      req.setTimeout(1000, () => {
        req.destroy()
        retry()
      })
    }
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error(`Local runner did not become healthy on ${HEALTH}`))
        return
      }
      setTimeout(tick, 250)
    }
    tick()
  })
}

function probeHealth() {
  return new Promise((resolve) => {
    const req = http.get(HEALTH, (res) => {
      res.resume()
      resolve(res.statusCode === 200)
    })
    req.on('error', () => resolve(false))
    req.setTimeout(800, () => {
      req.destroy()
      resolve(false)
    })
  })
}

/** Stop whatever is listening on the runner port (stale uvicorn from prior sessions). */
function freeRunnerPort(logger = console) {
  try {
    if (process.platform === 'win32') {
      const out = execSync(`netstat -ano | findstr :${PORT}`, {
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
      })
      const pids = new Set()
      for (const line of out.split(/\r?\n/)) {
        if (!line.includes('LISTENING')) continue
        const pid = line.trim().split(/\s+/).pop()
        if (pid && /^\d+$/.test(pid)) pids.add(pid)
      }
      for (const pid of pids) {
        try {
          execSync(`taskkill /PID ${pid} /T /F`, { stdio: 'ignore' })
          logger.info?.(`[bpc-runner] Stopped stale process PID ${pid} on :${PORT}`)
        } catch {
          /* ignore */
        }
      }
      return
    }

    const out = execSync(`lsof -tiTCP:${PORT} -sTCP:LISTEN`, {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
    if (!out) return
    for (const pid of out.split(/\s+/).filter(Boolean)) {
      try {
        process.kill(Number(pid), 'SIGTERM')
        logger.info?.(`[bpc-runner] Stopped stale process PID ${pid} on :${PORT}`)
      } catch {
        /* ignore */
      }
    }
  } catch {
    // nothing listening
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export function localRunnerPlugin() {
  let child = null
  let owned = false
  let shuttingDown = false

  const stop = () => {
    if (!child || !owned) {
      return
    }
    shuttingDown = true
    try {
      child.kill('SIGTERM')
    } catch {
      // ignore
    }
    child = null
    owned = false
  }

  const start = async (logger = console) => {
    // Never reuse a foreign/stale runner — it will serve old writer code without --reload.
    if (await probeHealth()) {
      logger.info?.(`[bpc-runner] Replacing existing listener on :${PORT}`)
      freeRunnerPort(logger)
      await sleep(400)
    }

    const uvicorn = resolveUvicorn()
    if (!uvicorn) {
      throw new Error(
        'Python runner venv not found. Double-click "Start BPCTool" or run: npm run setup',
      )
    }

    logger.info?.(`[bpc-runner] Starting ${uvicorn} on ${HOST}:${PORT} (--reload)`)
    child = spawn(
      uvicorn,
      [
        'app.main:app',
        '--host',
        HOST,
        '--port',
        String(PORT),
        '--reload',
        '--reload-dir',
        'app',
      ],
      {
        cwd: RUNNER_DIR,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: runnerEnv(logger),
      },
    )
    owned = true
    shuttingDown = false

    child.stdout?.on('data', (chunk) => {
      const text = String(chunk).trim()
      if (text) {
        logger.info?.(`[bpc-runner] ${text}`)
      }
    })
    child.stderr?.on('data', (chunk) => {
      const text = String(chunk).trim()
      if (text) {
        logger.info?.(`[bpc-runner] ${text}`)
      }
    })
    child.on('exit', (code, signal) => {
      if (!shuttingDown && owned) {
        logger.error?.(
          `[bpc-runner] Exited unexpectedly (code=${code}, signal=${signal})`,
        )
      }
      child = null
      owned = false
    })

    await waitForHealth()
    logger.info?.('[bpc-runner] Ready.')
  }

  const attach = (server) => {
    const logger = server.config.logger
    server.httpServer?.once('listening', () => {
      start(logger).catch((error) => {
        logger.error(`[bpc-runner] ${error.message}`)
      })
    })

    const shutdown = () => stop()
    process.once('exit', shutdown)
    process.once('SIGINT', () => {
      stop()
      process.exit(0)
    })
    process.once('SIGTERM', () => {
      stop()
      process.exit(0)
    })
  }

  return {
    name: 'bpc-local-runner',
    apply: 'serve',
    configureServer: attach,
    configurePreviewServer: attach,
  }
}
