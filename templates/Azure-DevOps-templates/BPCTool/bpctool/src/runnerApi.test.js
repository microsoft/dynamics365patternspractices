import { afterEach, describe, expect, it, vi } from 'vitest'
import { RUNNER_UNREACHABLE, runnerFetch } from './runnerApi'

describe('runnerFetch', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('explains a network failure instead of "Failed to fetch"', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(runnerFetch('/api/defaults')).rejects.toThrow(RUNNER_UNREACHABLE)
  })

  it('treats the dev proxy 502 (runner not listening) as unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 502 })))
    await expect(runnerFetch('/api/defaults')).rejects.toThrow(RUNNER_UNREACHABLE)
  })

  it('passes other responses and aborts through', async () => {
    const ok = new Response('{}', { status: 200 })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(ok))
    await expect(runnerFetch('/api/defaults')).resolves.toBe(ok)

    const abort = new DOMException('stopped', 'AbortError')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abort))
    await expect(runnerFetch('/api/jobs/1')).rejects.toBe(abort)
  })
})
