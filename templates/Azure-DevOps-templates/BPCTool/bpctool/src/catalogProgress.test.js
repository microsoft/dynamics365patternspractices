import { describe, expect, it } from 'vitest'
import { describeCatalogProgress } from './catalogProgress'

describe('describeCatalogProgress', () => {
  it('returns null without a total', () => {
    expect(describeCatalogProgress(null)).toBeNull()
    expect(describeCatalogProgress({ phase: 'create', total: 0 })).toBeNull()
  })

  it('summarizes create progress with ETA from items processed this run', () => {
    const summary = describeCatalogProgress({
      phase: 'create',
      done: 600,
      total: 1100,
      baseline: 100,
      elapsedMs: 50_000,
      created: 495,
      skipped: 100,
      failed: 5,
    })
    expect(summary.label).toBe('Catalog import')
    expect(summary.percent).toBe(54)
    expect(summary.eta).toBe('50s')
    expect(summary.detail).toBe(
      '600/1100 (54%) · created 495 · skipped 100 · failed 5 · ~50s left',
    )
  })

  it('omits ETA when nothing processed yet or finished', () => {
    expect(
      describeCatalogProgress({ phase: 'create', done: 10, total: 20, baseline: 10, elapsedMs: 900 })
        .eta,
    ).toBeNull()
    expect(
      describeCatalogProgress({ phase: 'create', done: 20, total: 20, elapsedMs: 900 }).eta,
    ).toBeNull()
  })

  it('labels backfill phase counts', () => {
    const summary = describeCatalogProgress({
      phase: 'backfill',
      done: 3,
      total: 4,
      elapsedMs: 7_200_000,
      linked: 2,
      conflict: 1,
    })
    expect(summary.label).toBe('Parent-link backfill')
    expect(summary.detail).toContain('linked 2 · conflict 1')
    expect(summary.eta).toBe('40m 00s')
  })
})
