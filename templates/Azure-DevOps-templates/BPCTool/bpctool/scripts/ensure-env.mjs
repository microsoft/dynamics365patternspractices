#!/usr/bin/env node
/**
 * One-time / first-launch environment bootstrap (no manual venv steps).
 */
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const isWin = process.platform === 'win32'
const venvPython = path.join(ROOT, '.venv', isWin ? 'Scripts/python.exe' : 'bin/python')
const venvPip = path.join(ROOT, '.venv', isWin ? 'Scripts/pip.exe' : 'bin/pip')

function run(command, args, opts = {}) {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    stdio: 'inherit',
    // Only .cmd shims need cmd.exe; a shell would split executable paths that contain spaces.
    shell: isWin && command.toLowerCase().endsWith('.cmd'),
    ...opts,
  })
  if (result.status !== 0) {
    process.exit(result.status ?? 1)
  }
}

function resolvePython() {
  for (const candidate of ['python3', 'python']) {
    const probe = spawnSync(candidate, ['--version'], {
      encoding: 'utf8',
      shell: isWin,
    })
    if (probe.status === 0) {
      return candidate
    }
  }
  console.error('Python 3 is required but was not found on PATH.')
  process.exit(1)
}

console.log('[setup] Working directory:', ROOT)

if (!existsSync(path.join(ROOT, 'node_modules'))) {
  console.log('[setup] Installing npm dependencies...')
  run(isWin ? 'npm.cmd' : 'npm', ['install'])
} else {
  console.log('[setup] npm dependencies already present.')
}

if (!existsSync(venvPython)) {
  const python = resolvePython()
  console.log(`[setup] Creating Python venv with ${python}...`)
  run(python, ['-m', 'venv', '.venv'])
} else {
  console.log('[setup] Python venv already present.')
}

console.log('[setup] Installing runner requirements...')
run(venvPip, ['install', '-r', 'runner/requirements.txt'])

console.log('[setup] Ready. Use Start BPCTool (or npm start) to launch.')
