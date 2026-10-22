import { useState } from 'react'

/**
 * Simple collapsible panel section. Defaults to expanded (uncollapsed).
 */
export default function CollapsibleSection({
  title,
  summary = null,
  defaultOpen = true,
  children,
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <section className="panel collapsible-panel">
      <button
        type="button"
        className="panel-heading-row collapsible-trigger"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <h2>{title}</h2>
        <span className="collapse-meta">
          <span className="collapse-caret" aria-hidden="true">
            {open ? '▾' : '▸'}
          </span>
        </span>
      </button>

      {open ? (
        <div className="collapsible-body">{children}</div>
      ) : summary ? (
        <p className="collapsed-summary">{summary}</p>
      ) : null}
    </section>
  )
}
