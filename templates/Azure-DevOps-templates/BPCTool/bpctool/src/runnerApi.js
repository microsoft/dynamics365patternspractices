/**
 * Local FastAPI runner client (Excel → IR → plan/apply).
 */

const sleep = (ms, signal) =>
  new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new Error('Run cancelled.'))
      return
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    const onAbort = () => {
      clearTimeout(timer)
      reject(new Error('Run cancelled.'))
    }
    signal?.addEventListener('abort', onAbort, { once: true })
  })

export const RUNNER_UNREACHABLE =
  "Can't reach the local runner. On first launch it sets itself up (about a minute) — wait for “[bpc-runner] Ready” in the terminal window BPCTool is running in. If that window shows an error instead, run npm run setup (or double-click Start BPCTool), then start BPCTool again."

/** fetch() for /api calls; a runner that isn't running becomes RUNNER_UNREACHABLE. */
export async function runnerFetch(url, options) {
  let response
  try {
    response = await fetch(url, options)
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw error
    }
    throw new Error(RUNNER_UNREACHABLE, { cause: error })
  }
  // The dev-server proxy answers 502 when nothing listens on the runner port.
  if (response.status === 502) {
    const error = new Error(RUNNER_UNREACHABLE)
    error.status = 502
    throw error
  }
  return response
}

async function parsePayload(response) {
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail =
      typeof payload.detail === 'string'
        ? payload.detail
        : payload.detail
          ? JSON.stringify(payload.detail)
          : `Runner error (${response.status})`
    const error = new Error(detail)
    error.status = response.status
    throw error
  }
  return payload
}

const MAX_POLL_FAILURES = 8

export async function createRunnerJob(body, { signal } = {}) {
  const response = await runnerFetch('/api/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  return parsePayload(response)
}

export async function getRunnerJob(jobId, { signal, since = 0 } = {}) {
  const query = since > 0 ? `?since=${since}` : ''
  const response = await runnerFetch(`/api/jobs/${encodeURIComponent(jobId)}${query}`, { signal })
  return parsePayload(response)
}

/** Ask the runner to stop the job at its next safe checkpoint. */
export async function cancelRunnerJob(jobId) {
  const response = await runnerFetch(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
  })
  return parsePayload(response)
}

/** URL for a run output file (report, failures, data checks) served by the runner. */
export const outputFileUrl = (folder, name, root = '') =>
  `/api/outputs/${encodeURIComponent(folder)}/${encodeURIComponent(name)}${
    root ? `?root=${encodeURIComponent(root)}` : ''
  }`

export const isActiveJobStatus = (status) => status === 'queued' || status === 'running'

/**
 * Poll an existing job until terminal status, fetching only new events.
 * Returns the final job with `events` holding every event received.
 */
export async function pollRunnerJob(
  jobId,
  { signal, onEvent, pollMs = 750, initialJob = null } = {},
) {
  const events = []
  let job = initialJob

  const absorb = (next) => {
    const offset = next.event_offset ?? 0
    const fresh = (next.events || []).slice(Math.max(0, events.length - offset))
    for (const event of fresh) {
      events.push(event)
      if (typeof onEvent === 'function') {
        onEvent(event)
      }
    }
  }

  if (job) {
    absorb(job)
  } else {
    job = await getRunnerJob(jobId, { signal })
    absorb(job)
  }

  let failures = 0
  while (isActiveJobStatus(job.status)) {
    await sleep(pollMs * 2 ** Math.min(failures, 3), signal)
    try {
      const next = await getRunnerJob(jobId, { signal, since: events.length })
      failures = 0
      job = next
      absorb(job)
    } catch (error) {
      // A long run shouldn't be abandoned over a brief network/runner blip.
      failures += 1
      if (signal?.aborted || error?.status === 404 || failures >= MAX_POLL_FAILURES) {
        throw error
      }
    }
  }

  return { ...job, events }
}

/**
 * Create an apply/dry-run job and poll until terminal status.
 * Invokes onEvent for each new runner event and onJobCreated with the job id.
 */
export async function runRunnerJob(body, { signal, onEvent, onJobCreated, pollMs = 750 } = {}) {
  const job = await createRunnerJob(body, { signal })
  if (typeof onJobCreated === 'function') {
    onJobCreated(job.id)
  }
  return pollRunnerJob(job.id, { signal, onEvent, pollMs, initialJob: job })
}

export function buildRunnerJobBody({
  orgUrl,
  pat,
  processName,
  projectName,
  projectDescription = '',
  templatePath,
  catalogSourceDir,
  workbookVersion,
  updatePolicy,
  confirmProcessUpdate,
  confirmProjectUpdate,
  knownProcessExists,
  knownProjectExists,
  rootAreaPath,
  mode = 'apply',
  applyDryRun = false,
  steps = null,
  catalogLimit = null,
  convertMarkdownToHtml = false,
  includeDeprecatedDeleted = false,
  catalogParallelWorkers = 4,
  outputRoot = '',
}) {
  return {
    org_url: orgUrl,
    pat,
    process_name: processName,
    project_name: projectName,
    project_description: projectDescription || '',
    excel_file: templatePath,
    catalog_source_dir: catalogSourceDir || null,
    workbook_version: workbookVersion || '',
    update_policy: updatePolicy,
    confirm_process_update: Boolean(confirmProcessUpdate),
    confirm_project_update: Boolean(confirmProjectUpdate),
    known_process_exists: knownProcessExists ?? null,
    known_project_exists: knownProjectExists ?? null,
    root_area_path: rootAreaPath || projectName,
    mode,
    apply_dry_run: Boolean(applyDryRun),
    steps,
    catalog_limit: catalogLimit,
    convert_markdown_to_html: Boolean(convertMarkdownToHtml),
    include_deprecated_deleted: Boolean(includeDeprecatedDeleted),
    output_root: outputRoot.trim() || null,
    catalog_parallel_workers: Math.max(
      1,
      Math.min(16, Number(catalogParallelWorkers) || 4),
    ),
  }
}
