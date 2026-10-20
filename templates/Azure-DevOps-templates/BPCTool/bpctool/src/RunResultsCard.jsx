import { useState } from 'react'
import { outputFileUrl } from './runnerApi'

const STATUS_ICON = {
  ok: '✓',
  warning: '!',
  error: '✕',
  skipped: '–',
  rehearsed: '○',
}

const ATTENTION_PREVIEW = 4

const formatCount = (value) => Number(value || 0).toLocaleString()

const shortTime = (iso) => String(iso || '').slice(0, 16).replace('T', ' ')

function AttentionItem({ item, folder, root = '' }) {
  return (
    <li className={`attention-item ${item.severity}`}>
      <strong>{item.title}</strong>
      {item.detail ? <p>{item.detail}</p> : null}
      {item.fix ? (
        <p className="attention-fix">
          <span>How to fix:</span> {item.fix}
        </p>
      ) : null}
      {item.examples?.length ? (
        <ul className="attention-examples">
          {item.examples.map((example) => (
            <li key={example}>{example}</li>
          ))}
        </ul>
      ) : null}
      {item.file && folder ? (
        <a className="attention-file" href={outputFileUrl(folder, item.file, root)}>
          Download {item.file}
        </a>
      ) : null}
    </li>
  )
}

/** Catalog data checks (needs review / fixed automatically) from Preview plan or a run. */
export function DataChecks({ checks }) {
  if (!checks) {
    return null
  }
  const review = checks.needsReview || []
  const automatic = checks.automaticFixes || []
  if (review.length === 0 && automatic.length === 0) {
    return <p className="field-hint">Data checks: no issues found in the catalog workbooks.</p>
  }
  return (
    <div className="data-checks">
      <h4>Catalog data checks</h4>
      {review.length ? (
        <ul className="attention-list">
          {review.map((group) => (
            <AttentionItem
              key={group.kind}
              folder=""
              item={{
                severity: 'warning',
                title: `${formatCount(group.count)} ${group.count === 1 ? 'value' : 'values'}: ${group.label}`,
                detail: group.outcome,
                fix: group.fix,
                examples: (group.examples || []).map(
                  (example) => {
                    const label = example.fieldLabel || example.field
                    const value = String(example.value ?? '')
                    const detail = value ? `${label}: '${value.slice(0, 80)}'` : `${label} is empty`
                    return `${example.sourceFile} row ${example.sourceRow ?? '?'} (${example.key}) — ${detail}`
                  },
                ),
              }}
            />
          ))}
        </ul>
      ) : (
        <p className="field-hint">No values need review.</p>
      )}
      {automatic.length ? (
        <details className="data-checks-automatic">
          <summary>
            {formatCount(checks.automaticFixesTotal)} values fixed automatically (no action needed)
          </summary>
          <ul>
            {automatic.map((group) => (
              <li key={group.kind}>
                <strong>{formatCount(group.count)}</strong> — {group.label}. {group.outcome}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <p className="field-hint">
        These rows still import. The full list (with file and row) is written to
        import-prevalidate.csv when you rehearse or run Catalog Import.
      </p>
    </div>
  )
}

/** Rehearsal only: differences between the workbook and items an earlier import created. */
function ChangesSection({ changes }) {
  if (!changes) {
    return null
  }
  return (
    <div className="run-changes">
      <h3>Changes since the last import</h3>
      <p>{changes.summary}</p>
      {changes.items?.length ? (
        <ul>
          {changes.items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
      {changes.fields?.length ? (
        <ul className="attention-list">
          {changes.fields.map((field) => (
            <li key={field.field} className="attention-item info">
              <strong>
                {field.field}: {formatCount(field.count)} {field.count === 1 ? 'item' : 'items'}
              </strong>
              <p>
                {field.teamOwned
                  ? 'Usually edited in Azure DevOps after import.'
                  : 'Usually edited in the workbook.'}
              </p>
              {field.examples?.length ? (
                <ul className="attention-examples">
                  {field.examples.map((example) => (
                    <li key={example}>{example}</li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {changes.partialWorkbook ? (
        <p className="field-hint">
          Only part of the workbook was read (row limit), so items missing from the workbook are not listed.
        </p>
      ) : null}
      {changes.note ? <p className="field-hint">{changes.note}</p> : null}
    </div>
  )
}

export default function RunResultsCard({ outcome, onRerunCatalog, onDismiss }) {
  const [showAll, setShowAll] = useState(false)
  if (!outcome) {
    return null
  }
  const folder = outcome.outputFolder
  const attention = outcome.attention || []
  const visible = showAll ? attention : attention.slice(0, ATTENTION_PREVIEW)
  const primaryFiles = (outcome.files || []).filter((file) => file.primary)
  const catalogStep = (outcome.steps || []).find((step) => step.id === 'catalog')
  const canRerunCatalog =
    !outcome.dryRun && catalogStep && ['error', 'warning'].includes(catalogStep.status)

  return (
    <section className={`run-results ${outcome.status}`} aria-label="Run results">
      <header className="run-results-banner">
        <div>
          <strong>{outcome.headline}</strong>
          <p>{outcome.subline}</p>
        </div>
        {onDismiss ? (
          <button type="button" className="run-results-dismiss" onClick={onDismiss} aria-label="Dismiss results">
            ×
          </button>
        ) : null}
      </header>

      {(outcome.notices || []).map((notice) => (
        <p key={notice} className="run-notice">
          {notice}
        </p>
      ))}

      {primaryFiles.length || canRerunCatalog ? (
        <div className="run-results-actions">
          {primaryFiles.map((file) => (
            <a
              key={file.name}
              className="run-button secondary"
              href={outputFileUrl(folder, file.name, outcome.outputRoot)}
              target={file.name.endsWith('.html') ? '_blank' : undefined}
              rel="noreferrer"
              title={`${file.description}${file.updatedThisRun ? '' : ' (from an earlier run)'}`}
            >
              {file.name.endsWith('.html') ? 'Open ' : 'Download '}
              {file.label.toLowerCase()}
              {file.updatedThisRun ? '' : ' (earlier run)'}
            </a>
          ))}
          {canRerunCatalog ? (
            <button type="button" className="run-button" onClick={onRerunCatalog}>
              Set up Catalog Import re-run
            </button>
          ) : null}
        </div>
      ) : null}

      {attention.length ? (
        <>
          <h3>What needs attention</h3>
          <ol className="attention-list">
            {visible.map((item) => (
              <AttentionItem key={item.title} item={item} folder={folder} root={outcome.outputRoot} />
            ))}
          </ol>
          {attention.length > ATTENTION_PREVIEW ? (
            <button type="button" className="link-button" onClick={() => setShowAll((value) => !value)}>
              {showAll ? 'Show fewer' : `Show all ${attention.length} items`}
            </button>
          ) : null}
        </>
      ) : null}

      <ChangesSection changes={outcome.changes} />

      <h3>Steps</h3>
      <ul className="run-results-steps">
        {(outcome.steps || []).map((step) => (
          <li key={step.id} className={step.status}>
            <span className="step-icon" aria-hidden="true">
              {STATUS_ICON[step.status] ?? ''}
            </span>
            <span className="step-title">{step.title}</span>
            <span className="step-summary">
              {step.summary}
              {step.earlierRun ? (
                <em> (from an earlier run, {shortTime(step.earlierRun)})</em>
              ) : null}
            </span>
            <span className="step-duration">{step.duration}</span>
          </li>
        ))}
      </ul>

      {outcome.automaticFixes?.length ? (
        <details className="data-checks-automatic">
          <summary>Fixed automatically (no action needed)</summary>
          <ul>
            {outcome.automaticFixes.map((fix) => (
              <li key={fix.label}>
                <strong>{formatCount(fix.count)}</strong> — {fix.label}. {fix.outcome}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {outcome.outputDir ? (
        <p className="field-hint">Files are in {outcome.outputDir}</p>
      ) : null}
    </section>
  )
}
