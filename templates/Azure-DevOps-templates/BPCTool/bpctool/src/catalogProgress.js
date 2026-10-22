/**
 * Summaries for runner `catalog-progress` events (create + backfill phases).
 */

const formatEta = (ms) => {
  const totalSeconds = Math.max(0, Math.round(ms / 1000))
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) {
    return `${hours}h ${String(minutes).padStart(2, '0')}m`
  }
  if (minutes > 0) {
    return `${minutes}m ${String(seconds).padStart(2, '0')}s`
  }
  return `${seconds}s`
}

export function describeCatalogProgress(progress) {
  if (!progress || !progress.total) {
    return null
  }
  const total = Number(progress.total) || 0
  const done = Math.min(total, Number(progress.done) || 0)
  const baseline = Number(progress.baseline) || 0
  const elapsedMs = Number(progress.elapsedMs) || 0
  const percent = total ? Math.floor((done / total) * 100) : 0
  const backfill = progress.phase === 'backfill'

  const processed = done - baseline
  let eta = null
  if (processed > 0 && elapsedMs > 0 && done < total) {
    eta = formatEta(((total - done) * elapsedMs) / processed)
  }

  const counts = backfill
    ? [
        ['linked', progress.linked],
        ['conflict', progress.conflict],
        ['failed', progress.failed],
      ]
    : [
        ['created', progress.created],
        ['skipped', progress.skipped],
        ['failed', progress.failed],
      ]
  const countText = counts
    .filter(([, value]) => Number(value) > 0)
    .map(([label, value]) => `${label} ${value}`)
    .join(' · ')

  return {
    label: backfill ? 'Parent-link backfill' : 'Catalog import',
    done,
    total,
    percent,
    eta,
    detail: [
      `${done}/${total} (${percent}%)`,
      countText,
      eta ? `~${eta} left` : '',
    ]
      .filter(Boolean)
      .join(' · '),
  }
}
