import { useState } from 'react'

/**
 * Collapsible connection: org URL, PAT, optional inventory fetch, execution mode.
 * Process/project names to create live in a separate step.
 */
export default function ConnectionPanel({
  orgUrl,
  onOrgUrlChange,
  pat,
  onPatChange,
  showPat,
  onToggleShowPat,
  connectionReady,
  connectionStatusText,
  fetchingProjects,
  projectsFetched,
  onFetchProjects,
  fetchingProcesses,
  processesFetched,
  onFetchProcesses,
  executionMode,
  onExecutionModeChange,
  extensionStatus = 'unknown',
  extensionMessage = '',
  extensionBusy = false,
  onCheckExtension,
  onInstallExtension,
  disabled = false,
}) {
  const extensionChip =
    extensionStatus === 'installed'
      ? { className: 'completed', label: 'Multivalue: installed' }
      : extensionStatus === 'checking'
        ? { className: 'running', label: 'Multivalue: checking…' }
        : extensionStatus === 'missing'
          ? { className: 'idle', label: 'Multivalue: missing' }
          : extensionStatus === 'disabled'
            ? { className: 'idle', label: 'Multivalue: disabled' }
            : extensionStatus === 'error'
              ? { className: 'idle', label: 'Multivalue: check failed' }
              : { className: 'idle', label: 'Multivalue: not checked' }
  const [expandedWhileReady, setExpandedWhileReady] = useState(false)
  const open = !connectionReady || expandedWhileReady

  return (
    <section className="panel collapsible-panel">
      <button
        type="button"
        className="panel-heading-row collapsible-trigger"
        onClick={() => {
          if (!connectionReady) {
            return
          }
          setExpandedWhileReady((value) => !value)
        }}
        aria-expanded={open}
      >
        <h2>1. Connection</h2>
        <span className="collapse-meta">
          <span
            className={`status-chip connection-pill ${connectionReady ? 'completed' : 'idle'}`}
          >
            {connectionReady ? 'Ready' : 'Needs URL + PAT'}
          </span>
          <span className="collapse-caret" aria-hidden="true">
            {open ? '▾' : '▸'}
          </span>
        </span>
      </button>

      {open ? (
        <div className="grid-2 collapsible-body">
          <label className="field-span-full">
            Azure DevOps org URL
            <input
              value={orgUrl}
              onChange={(event) => onOrgUrlChange(event.target.value)}
              placeholder="https://dev.azure.com/org or https://org.visualstudio.com"
              disabled={disabled}
            />
          </label>

          <label className="field-span-full">
            Personal access token
            <div className="pat-row">
              <input
                type={showPat ? 'text' : 'password'}
                value={pat}
                onChange={(event) => onPatChange(event.target.value)}
                placeholder="PAT (session only, not saved)"
                autoComplete="off"
                spellCheck={false}
                disabled={disabled}
              />
              <button
                type="button"
                className="secondary-inline"
                onClick={onToggleShowPat}
                disabled={disabled}
              >
                {showPat ? 'Hide' : 'Show'}
              </button>
            </div>
          </label>

          <div className="fetch-row inventory-actions field-span-full">
            <button
              type="button"
              className={projectsFetched ? 'fetched-button' : ''}
              onClick={onFetchProjects}
              disabled={disabled || fetchingProjects || !connectionReady}
            >
              {fetchingProjects
                ? 'Loading projects...'
                : projectsFetched
                  ? 'Projects fetched'
                  : 'Fetch existing projects'}
            </button>
            <button
              type="button"
              className={processesFetched ? 'fetched-button' : ''}
              onClick={onFetchProcesses}
              disabled={disabled || fetchingProcesses || !connectionReady}
            >
              {fetchingProcesses
                ? 'Loading processes...'
                : processesFetched
                  ? 'Processes fetched'
                  : 'Fetch existing processes'}
            </button>
          </div>

          <div className="extension-preflight field-span-full">
            <div className="extension-preflight-row">
              <span className={`status-chip ${extensionChip.className}`}>
                {extensionChip.label}
              </span>
              <button
                type="button"
                className="secondary-inline"
                onClick={onCheckExtension}
                disabled={
                  disabled ||
                  extensionBusy ||
                  !connectionReady ||
                  executionMode === 'simulate'
                }
              >
                {extensionStatus === 'checking' ? 'Checking…' : 'Check Multivalue extension'}
              </button>
              {extensionStatus === 'missing' || extensionStatus === 'disabled' ? (
                <button
                  type="button"
                  onClick={onInstallExtension}
                  disabled={
                    disabled ||
                    extensionBusy ||
                    !connectionReady ||
                    executionMode === 'simulate'
                  }
                >
                  {extensionBusy ? 'Installing…' : 'Install Multivalue extension'}
                </button>
              ) : null}
            </div>
            {extensionMessage ? (
              <p className="extension-preflight-message">{extensionMessage}</p>
            ) : (
              <p className="field-hint">
                DevLabs Multivalue control is required for process template and project
                setup (Multi-select fields). Checked automatically when URL + PAT are set.
              </p>
            )}
          </div>

          <label className="field-span-full">
            Execution mode
            <select
              value={executionMode}
              onChange={(event) => onExecutionModeChange(event.target.value)}
              disabled={disabled}
            >
              <option value="runner">Runner (local Excel→IR→apply engine)</option>
              <option value="api">API (live ADO reads via proxy)</option>
              <option value="simulate">Simulate (local stubs)</option>
            </select>
          </label>

          <div className="connection-note">
            <p>{connectionStatusText}</p>
            <p>
              Org URL and PAT stay in this browser session only. Existing projects and
              processes load automatically once both are filled in (and after each live run);
              they drive the create vs update policy. Use the buttons to refresh.
              The local apply engine starts automatically with the app — no separate terminal.
            </p>
          </div>
        </div>
      ) : (
        <p className="collapsed-summary">
          {orgUrl || 'No org URL'} · PAT {pat ? 'set' : 'missing'} · mode{' '}
          {executionMode} · {extensionChip.label}
        </p>
      )}
    </section>
  )
}
