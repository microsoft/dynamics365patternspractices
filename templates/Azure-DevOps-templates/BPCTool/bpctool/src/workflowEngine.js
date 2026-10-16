import { executeApiStep } from './adoApi'
import { normalizeAdoOrgUrl, parseAdoOrgUrl } from './adoOrgUrl'
import {
  assessExistingTargets,
  gateExistingTargetUpdates,
} from './targetAssessment'

/**
 * Ordered BPC flow:
 * 1) Process template from workbook
 * 2) Page layouts on that process
 * 3) Project creation only after process + layout are done
 * 4) Teams / areas
 * 5) Backlog
 */
export const workflowDefinitions = [
  {
    id: 'process',
    title: '1. Process Template',
    script: 'runner · process',
    description:
      'Create or update the inherited process shell, work item types, fields, and picklists from the workbook. Supports future spreadsheet deltas against an existing process.',
    inputs: ['Template workbook path', 'Process name', 'Workbook version'],
    durationMs: 900,
    phase: 'process',
  },
  {
    id: 'layout',
    title: '2. Page Layout Setup',
    script: 'runner · layout',
    description:
      'Apply form/page layout customizations on the process work item types before any project is created. HTML fields use HtmlFieldControl groups.',
    inputs: ['Threads', 'Layout worksheet name'],
    durationMs: 750,
    phase: 'process',
  },
  {
    id: 'project',
    title: '3. Project Creation',
    script: 'runner · project',
    description:
      'Create or update the Azure DevOps project only after the process template and page layouts are finished.',
    inputs: ['Project name', 'Process name'],
    durationMs: 700,
    phase: 'project',
  },
  {
    id: 'teams',
    title: '4. Teams & Areas Setup',
    script: 'runner · teams',
    description:
      'Create teams and area paths from template values to align ownership and navigation structure.',
    inputs: ['Root area path', 'Team mode'],
    durationMs: 650,
    phase: 'project',
  },
  {
    id: 'backlog',
    title: '5. Backlog Configuration',
    script: 'runner · backlog',
    description:
      'Configure backlog levels, visibility, and sequencing for the Business Process Catalog workflow.',
    inputs: ['Backlog worksheet name', 'Rehearsal only mode'],
    durationMs: 700,
    phase: 'project',
  },
  {
    id: 'catalog',
    title: '6. Catalog Import',
    script: 'runner · catalog',
    description:
      'Import BPC catalog workbooks. HTML field values accept both HTML and markdown-like Excel text (converted for ADO).',
    inputs: ['Catalog source folder'],
    durationMs: 1200,
    phase: 'catalog',
  },
  {
    id: 'report',
    title: '7. HTML/JSON Report',
    script: 'runner · report',
    description: 'Write the plain-language run report (HTML/JSON) to the run output folder.',
    inputs: ['Output folder'],
    durationMs: 400,
    phase: 'report',
  },
]

export const stepOrder = workflowDefinitions.map((workflow) => workflow.id)
const transientErrorCodes = new Set(['ADO_THROTTLED', 'NETWORK_TIMEOUT'])

/** Migrate legacy completion caches that used combined `creation` step. */
export function migrateCompletedStepIds(completedStepIds = []) {
  const next = new Set()
  for (const stepId of completedStepIds) {
    if (stepId === 'creation') {
      next.add('process')
      next.add('project')
      continue
    }
    if (stepOrder.includes(stepId)) {
      next.add(stepId)
    }
  }
  return Array.from(next)
}

const sleep = (ms, signal) =>
  new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(buildFlowError('ABORTED', 'Run cancelled.', false))
      return
    }

    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)

    const onAbort = () => {
      clearTimeout(timer)
      reject(buildFlowError('ABORTED', 'Run cancelled.', false))
    }

    signal?.addEventListener('abort', onAbort, { once: true })
  })

export const buildFlowError = (code, message, transient = false) => {
  const error = new Error(message)
  error.code = code
  error.transient = transient
  return error
}

const throwIfAborted = (signal) => {
  if (signal?.aborted) {
    throw buildFlowError('ABORTED', 'Run cancelled.', false)
  }
}

/**
 * Resolve which steps a run will execute.
 *
 * - `step`: only the selected card (re-run even if already completed; no prerequisites)
 * - `single`: dependency-aware run through the selected card (skips completed)
 * - `from`: the selected card and every later card (re-runs completed ones)
 * - `full`: all incomplete steps in order
 *
 * For `single` / `from` / `full`, project-phase steps are withheld until process + layout
 * are already complete or included earlier in the same plan.
 */
export function resolveTargetSteps(mode, selectedWorkflowId, completedStepIds) {
  const completedSet = new Set(migrateCompletedStepIds(completedStepIds))

  if (mode === 'step') {
    return stepOrder.includes(selectedWorkflowId) ? [selectedWorkflowId] : []
  }

  let candidates
  if (mode === 'from') {
    const selectedIndex = stepOrder.indexOf(selectedWorkflowId)
    if (selectedIndex < 0) {
      return []
    }
    candidates = stepOrder.slice(selectedIndex)
  } else if (mode === 'full') {
    candidates = stepOrder.filter((stepId) => !completedSet.has(stepId))
  } else {
    // Default / legacy: dependency-aware (`single`)
    const selectedIndex = stepOrder.indexOf(selectedWorkflowId)
    if (selectedIndex < 0) {
      return []
    }
    candidates = stepOrder
      .slice(0, selectedIndex + 1)
      .filter((stepId) => !completedSet.has(stepId))
  }

  // Hard dependency: project (and later project-phase steps) require process + layout first.
  const processReady =
    completedSet.has('process') || candidates.includes('process')
  const layoutReady = completedSet.has('layout') || candidates.includes('layout')

  if (!processReady || !layoutReady) {
    return candidates.filter((stepId) => stepId === 'process' || stepId === 'layout')
  }

  return candidates
}

export function validateRunnerConfig(config, targetStepIds = stepOrder) {
  const errors = []
  const planned = new Set(targetStepIds)

  if (!config.orgUrl) {
    errors.push('Azure DevOps org URL is required.')
  } else {
    const parsed = parseAdoOrgUrl(config.orgUrl)
    if (!parsed.ok) {
      errors.push(parsed.error)
    }
  }

  if (!config.pat || config.pat.length < 20) {
    errors.push('PAT is required and should be at least 20 characters.')
  }

  if (!config.templatePath || !config.templatePath.toLowerCase().endsWith('.xlsx')) {
    errors.push('Template workbook path must point to an .xlsx file.')
  }

  const needsProcess = planned.has('process') || planned.has('layout') || planned.has('project')
  if (needsProcess && (!config.processName || config.processName.trim().length < 3)) {
    errors.push('Process name must be at least 3 characters.')
  }

  const needsProject =
    planned.has('project') ||
    planned.has('teams') ||
    planned.has('backlog') ||
    planned.has('catalog') ||
    planned.has('report')
  if (needsProject && (!config.projectName || config.projectName.trim().length < 3)) {
    errors.push('Project name must be at least 3 characters.')
  }

  if (
    !Number.isFinite(config.maxRetries) ||
    config.maxRetries < 0 ||
    config.maxRetries > 5
  ) {
    errors.push('Retry count must be between 0 and 5.')
  }

  if (!Number.isFinite(config.threads) || config.threads < 1 || config.threads > 16) {
    errors.push('Thread count must be between 1 and 16.')
  }

  if (planned.has('layout') && !config.layoutSheet?.trim()) {
    errors.push('Layout worksheet name is required for the page layout step.')
  }

  if (
    planned.has('teams') &&
    !config.rootAreaPath?.trim() &&
    !config.projectName?.trim()
  ) {
    errors.push('Root area path (or project name) is required for the teams & areas step.')
  }

  if (
    (planned.has('catalog') || planned.has('report')) &&
    config.executionMode === 'runner' &&
    !config.catalogSourceDir?.trim()
  ) {
    errors.push('Catalog source folder is required for catalog/report steps.')
  }

  if (planned.has('backlog') && !config.backlogSheet?.trim()) {
    errors.push('Backlog worksheet name is required for the backlog step.')
  }

  const allowedPolicies = new Set([
    'require-confirmation',
    'always-update',
    'skip-existing',
    'create-only',
  ])
  if (config.updatePolicy && !allowedPolicies.has(config.updatePolicy)) {
    errors.push('Update policy is invalid.')
  }

  return errors
}

/** Simulated step executor — default adapter until API/Python backends are wired. */
export async function simulateStepExecution(step, config, { signal } = {}) {
  throwIfAborted(signal)
  await sleep(step.durationMs, signal)
  throwIfAborted(signal)

  if (config.orgUrl.includes('throttle-test') && step.id === 'layout') {
    throw buildFlowError(
      'ADO_THROTTLED',
      'Azure DevOps rate limit reached while applying layouts.',
      true,
    )
  }

  if (step.id === 'project' && config.projectName.trim().toLowerCase() === 'invalid') {
    throw buildFlowError('INVALID_PROJECT', 'Project name is not valid for creation.', false)
  }

  const warnings = []

  if (step.id === 'process' && config.assessment?.process?.exists) {
    warnings.push(
      config.assessment.workbook?.changed
        ? 'Existing process will receive spreadsheet delta updates.'
        : 'Existing process selected — verified update path.',
    )
  }

  if (step.id === 'project' && config.assessment?.project?.exists) {
    warnings.push('Existing project selected — verified update/reuse path.')
  }

  if (step.id === 'layout' && config.threads > 8) {
    warnings.push('High thread count can trigger ADO throttling; 2-8 is recommended.')
  }

  if (step.id === 'backlog' && config.dryRun) {
    warnings.push('Dry-run enabled. Backlog changes are evaluated but not committed.')
  }

  const subject =
    step.phase === 'process' ? `process ${config.processName}` : `project ${config.projectName}`

  return {
    details: `[simulate] ${step.script} completed for ${subject}.`,
    warnings,
    workbookApplied:
      step.id === 'process'
        ? {
            fingerprint: config.assessment?.workbook?.fingerprint,
            processName: config.processName,
          }
        : undefined,
  }
}

/**
 * Placeholder adapters for future backends. Swap via executeStep option.
 * Keep the same return shape: { details, warnings }.
 */
export const stepExecutors = {
  simulate: simulateStepExecution,
  api: async (step, config, options) => {
    try {
      return await executeApiStep(step, config, options)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      const transient = /ADO (429|503)\b/.test(message) || /throttl|network|fetch/i.test(message)
      throw buildFlowError(transient ? 'ADO_THROTTLED' : 'ADO_API', message, transient)
    }
  },
  /**
   * Per-step runner adapter is unused — App.jsx drives whole-job apply via /api/jobs.
   * Kept so executionMode lookups stay stable.
   */
  runner: async (step) => {
    throw buildFlowError(
      'USE_RUNNER_JOB',
      `Step ${step.id} must run via the local runner job API (/api/jobs), not per-step.`,
      false,
    )
  },
}

export { normalizeAdoOrgUrl, parseAdoOrgUrl, assessExistingTargets, gateExistingTargetUpdates }

export function formatDurationMs(ms) {
  const value = Math.max(0, Math.round(Number(ms) || 0))
  if (value < 1000) {
    return `${value}ms`
  }
  const seconds = value / 1000
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`
  }
  const minutes = Math.floor(seconds / 60)
  if (minutes >= 60) {
    return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
  }
  const rem = seconds - minutes * 60
  return `${minutes}m ${rem.toFixed(1)}s`
}

export function formatTimingSummary(timings = [], totalMs) {
  const lines = timings.map((row) => {
    if (row.skipped) {
      return `  ${row.stepId}: skipped`
    }
    return `  ${row.stepId}: ${formatDurationMs(row.durationMs)}`
  })
  if (totalMs != null) {
    lines.push(`  total: ${formatDurationMs(totalMs)}`)
  }
  return lines.length ? lines.join('\n') : '  (no steps)'
}

const emit = (onEvent, event) => {
  if (typeof onEvent === 'function') {
    onEvent({
      timestamp: new Date().toISOString(),
      ...event,
    })
  }
}

async function runStepWithRetry(step, config, onEvent, executeStep, signal) {
  const maxAttempts = config.maxRetries + 1

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    throwIfAborted(signal)

    emit(onEvent, {
      type: 'step-attempt',
      stepId: step.id,
      stepTitle: step.title,
      attempt,
      maxAttempts,
      message: `Attempt ${attempt}/${maxAttempts}`,
    })

    try {
      const result = await executeStep(step, config, { signal })
      return { ok: true, warnings: [], ...result }
    } catch (error) {
      if (error?.code === 'ABORTED' || signal?.aborted) {
        return { ok: false, error: buildFlowError('ABORTED', 'Run cancelled.', false) }
      }

      const isTransient = transientErrorCodes.has(error.code) || error.transient === true
      const isLastAttempt = attempt === maxAttempts

      emit(onEvent, {
        type: 'step-error',
        stepId: step.id,
        stepTitle: step.title,
        attempt,
        maxAttempts,
        transient: isTransient,
        message: error.message,
      })

      if (!isTransient || isLastAttempt) {
        return { ok: false, error }
      }

      await sleep(250 * attempt, signal)
    }
  }

  return {
    ok: false,
    error: buildFlowError('UNKNOWN', 'Step failed with an unknown error.', false),
  }
}

export async function runWorkflowFlow({
  mode,
  selectedWorkflowId,
  completedStepIds,
  config,
  onEvent,
  signal,
  executeStep = stepExecutors.simulate,
}) {
  const migratedCompleted = migrateCompletedStepIds(completedStepIds)
  let targetStepIds = resolveTargetSteps(mode, selectedWorkflowId, migratedCompleted)
  const nextCompletedSet = new Set(migratedCompleted)

  const assessment =
    config.assessment ??
    assessExistingTargets({
      processName: config.processName,
      projectName: config.projectName,
      knownProcesses: config.knownProcesses,
      knownProjects: config.knownProjects,
      templatePath: config.templatePath,
      workbookVersion: config.workbookVersion,
      lastAppliedWorkbook: config.lastAppliedWorkbook,
    })

  const gated = gateExistingTargetUpdates({
    targetStepIds,
    assessment,
    updatePolicy: config.updatePolicy || 'require-confirmation',
    confirmProcessUpdate: Boolean(config.confirmProcessUpdate),
    confirmProjectUpdate: Boolean(config.confirmProjectUpdate),
  })

  emit(onEvent, {
    type: 'target-assessment',
    message: 'Evaluated existing process/project and workbook revision.',
    assessment,
    skippedStepIds: gated.skippedStepIds,
  })

  if (!gated.ok) {
    return {
      ok: false,
      completedStepIds: migratedCompleted,
      assessment,
      error: buildFlowError('UPDATE_CONFIRMATION_REQUIRED', gated.errors.join(' '), false),
    }
  }

  const timings = []
  if (gated.skippedStepIds.length > 0) {
    const skipSet = new Set(gated.skippedStepIds)
    targetStepIds = targetStepIds.filter((stepId) => !skipSet.has(stepId))
    for (const stepId of gated.skippedStepIds) {
      nextCompletedSet.add(stepId)
      timings.push({ stepId, durationMs: 0, skipped: true })
      emit(onEvent, {
        type: 'step-skipped',
        stepId,
        durationMs: 0,
        message: `Skipped ${stepId} because the target already exists (skip-existing policy).`,
      })
    }
  }

  const runConfig = { ...config, assessment }

  const validationErrors = validateRunnerConfig(runConfig, targetStepIds)
  if (validationErrors.length > 0) {
    return {
      ok: false,
      completedStepIds: migratedCompleted,
      assessment,
      error: buildFlowError('VALIDATION', validationErrors.join(' '), false),
    }
  }

  if (targetStepIds.length === 0) {
    return {
      ok: true,
      completedStepIds: Array.from(nextCompletedSet),
      assessment,
      message: 'No new steps required. Selected flow is already complete.',
    }
  }

  let appliedWorkbook = null
  const runStarted = performance.now()

  try {
    throwIfAborted(signal)

    for (const stepId of targetStepIds) {
      throwIfAborted(signal)

      const step = workflowDefinitions.find((workflow) => workflow.id === stepId)
      if (!step) {
        return {
          ok: false,
          completedStepIds: Array.from(nextCompletedSet),
          assessment,
          error: buildFlowError('MISSING_STEP', `Workflow step not found: ${stepId}`, false),
        }
      }

      // Enforce ordering at execution time as well.
      if (
        (stepId === 'project' || stepId === 'teams' || stepId === 'backlog') &&
        !(nextCompletedSet.has('process') && nextCompletedSet.has('layout'))
      ) {
        return {
          ok: false,
          completedStepIds: Array.from(nextCompletedSet),
          assessment,
          error: buildFlowError(
            'DEPENDENCY',
            'Project creation cannot start until process template and page layout are finished.',
            false,
          ),
        }
      }

      emit(onEvent, {
        type: 'step-started',
        stepId: step.id,
        stepTitle: step.title,
        message: `Starting ${step.script}`,
      })

      const stepStarted = performance.now()
      const result = await runStepWithRetry(step, runConfig, onEvent, executeStep, signal)
      const durationMs = Math.round(performance.now() - stepStarted)

      if (!result.ok) {
        timings.push({ stepId: step.id, durationMs, skipped: false })
        emit(onEvent, {
          type: 'step-failed',
          stepId: step.id,
          stepTitle: step.title,
          durationMs,
          message: result.error.message,
        })
        const totalMs = Math.round(performance.now() - runStarted)
        emit(onEvent, {
          type: 'run-summary',
          durationMs: totalMs,
          timings,
          message: `Run timing (failed):\n${formatTimingSummary(timings, totalMs)}`,
        })

        return {
          ok: false,
          completedStepIds: Array.from(nextCompletedSet),
          assessment,
          appliedWorkbook,
          durationMs: totalMs,
          timings,
          error: result.error,
        }
      }

      nextCompletedSet.add(step.id)
      if (result.workbookApplied?.fingerprint) {
        appliedWorkbook = result.workbookApplied
      }

      timings.push({ stepId: step.id, durationMs, skipped: false })
      emit(onEvent, {
        type: 'step-completed',
        stepId: step.id,
        stepTitle: step.title,
        durationMs,
        message: `${result.details} (${formatDurationMs(durationMs)})`,
        warnings: result.warnings,
      })

      if (result.warnings.length > 0) {
        for (const warning of result.warnings) {
          emit(onEvent, {
            type: 'step-warning',
            stepId: step.id,
            stepTitle: step.title,
            message: warning,
          })
        }
      }
    }

    const totalMs = Math.round(performance.now() - runStarted)
    emit(onEvent, {
      type: 'run-summary',
      durationMs: totalMs,
      timings,
      message: `Run timing:\n${formatTimingSummary(timings, totalMs)}`,
    })

    return {
      ok: true,
      completedStepIds: Array.from(nextCompletedSet),
      assessment,
      appliedWorkbook,
      durationMs: totalMs,
      timings,
    }
  } catch (error) {
    if (error?.code === 'ABORTED' || signal?.aborted) {
      return {
        ok: false,
        completedStepIds: Array.from(nextCompletedSet),
        assessment,
        appliedWorkbook,
        error: buildFlowError('ABORTED', 'Run cancelled.', false),
      }
    }

    throw error
  }
}
