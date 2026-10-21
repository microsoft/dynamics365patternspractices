#!/usr/bin/env node
/**
 * Developer commands for the Python runner using the project venv on macOS, Linux and Windows.
 *
 *   node scripts/runner.mjs start         runner API only (127.0.0.1:8787, auto-reload)
 *   node scripts/runner.mjs install       runtime requirements
 *   node scripts/runner.mjs install-dev   runtime + test requirements (pytest)
 *   node scripts/runner.mjs test [args]   runner tests (args go to pytest)
 */
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const RUNNER = path.join(ROOT, 'runner')
const isWin = process.platform === 'win32'
const venvPython = path.join(ROOT, '.venv', isWin ? 'Scripts/python.exe' : 'bin/python')

const COMMANDS = {
  start: { cwd: RUNNER, args: ['-m', 'uvicorn', 'app.main:app', '--reload', '--host', '127.0.0.1', '--port', '8787'] },
  install: { cwd: ROOT, args: ['-m', 'pip', 'install', '-r', 'runner/requirements.txt'] },
  'install-dev': { cwd: ROOT, args: ['-m', 'pip', 'install', '-r', 'runner/requirements-dev.txt'] },
  test: { cwd: RUNNER, args: ['-m', 'pytest', '-q'] },
}

const [name, ...extra] = process.argv.slice(2)
const command = COMMANDS[name]
if (!command) {
  console.error(`Usage: node scripts/runner.mjs <${Object.keys(COMMANDS).join('|')}> [args]`)
  process.exit(2)
}
if (!existsSync(venvPython)) {
  console.error(`No Python venv at ${path.dirname(path.dirname(venvPython))}. Run "npm run setup" first.`)
  process.exit(1)
}
if (name === 'test' && spawnSync(venvPython, ['-c', 'import pytest']).status !== 0) {
  console.error('pytest is not installed in the venv. Run "npm run runner:install-dev" first.')
  process.exit(1)
}

const result = spawnSync(venvPython, [...command.args, ...extra], { cwd: command.cwd, stdio: 'inherit' })
process.exit(result.status ?? 1)
