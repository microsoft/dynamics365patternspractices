import { describe, expect, it } from 'vitest'
import { parseEnvFile } from '../scripts/localRunnerPlugin.js'

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
