import { describe, expect, it } from 'vitest'
import { describeListener, parseEnvFile } from '../scripts/localRunnerPlugin.js'

describe('describeListener', () => {
  const health = (extra) =>
    JSON.stringify({ status: 'ok', teams_writer_mtime: '1', backlog_writer_mtime: '1', ...extra })

  it('recognizes a BPCTool runner and its active run count', () => {
    expect(describeListener(200, health({ active_jobs: 2 }))).toEqual({ bpctool: true, activeJobs: 2 })
    expect(describeListener(200, health({ active_jobs: 0 }))).toEqual({ bpctool: true, activeJobs: 0 })
  })

  it('treats a runner from before active_jobs as BPCTool with an unknown count', () => {
    expect(describeListener(200, health())).toEqual({ bpctool: true, activeJobs: null })
  })

  it('does not claim unrelated programs on the port', () => {
    expect(describeListener(200, '{"status":"ok"}').bpctool).toBe(false)
    expect(describeListener(200, '<html>').bpctool).toBe(false)
    expect(describeListener(404, health()).bpctool).toBe(false)
  })
})

describe('parseEnvFile', () => {
  it('reads BPCTOOL_* keys, strips quotes, skips comments and blanks', () => {
    const text = [
      '# comment',
      '',
      'BPCTOOL_CATALOG=~/BPC Files',
      'BPCTOOL_OUTPUT_DIR="/data/runner out"',
      "BPCTOOL_TEMPLATE='/t.xlsx'",
      '# BPCTOOL_IGNORED=/x',
      'PATH=/evil',
      'BPCTOOL_EMPTY=',
      'not a pair',
    ].join('\r\n')
    expect(parseEnvFile(text)).toEqual({
      BPCTOOL_CATALOG: '~/BPC Files',
      BPCTOOL_OUTPUT_DIR: '/data/runner out',
      BPCTOOL_TEMPLATE: '/t.xlsx',
    })
  })
})
