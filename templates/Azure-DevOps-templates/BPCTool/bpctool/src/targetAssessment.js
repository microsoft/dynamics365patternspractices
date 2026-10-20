/**
 * Assess whether selected process/project already exist and whether a new
 * workbook should update the process template before mutating ADO.
 */

const INVALID_NAME_CHARS = /[\\/:*?"<>|#%&+={}[\]';@',~]/

export function namesMatch(left, right) {
  return String(left || '')
    .trim()
    .toLowerCase() === String(right || '').trim().toLowerCase()
}

export function buildWorkbookFingerprint({ templatePath, workbookVersion }) {
  const path = String(templatePath || '').trim().toLowerCase()
  const version = String(workbookVersion || '').trim().toLowerCase()
  return `${path}::${version || 'unversioned'}`
}

export function assessExistingTargets({
  processName,
  projectName,
  knownProcesses = [],
  knownProjects = [],
  templatePath,
  workbookVersion,
  lastAppliedWorkbook,
}) {
  const processExists = knownProcesses.some((process) =>
    namesMatch(process.name ?? process, processName),
  )
  const projectExists = knownProjects.some((project) =>
    namesMatch(project.name ?? project, projectName),
  )

  const nextFingerprint = buildWorkbookFingerprint({ templatePath, workbookVersion })
  const previousFingerprint = lastAppliedWorkbook?.fingerprint ?? null
  const workbookChanged =
    Boolean(templatePath?.trim()) &&
    (!previousFingerprint || previousFingerprint !== nextFingerprint)

  return {
    process: {
      name: processName?.trim() || '',
      exists: processExists,
      recommendedAction: processExists
        ? workbookChanged
          ? 'update-from-workbook'
          : 'verify-before-update'
        : 'create',
    },
    project: {
      name: projectName?.trim() || '',
      exists: projectExists,
      recommendedAction: projectExists ? 'verify-before-update' : 'create',
    },
    workbook: {
      fingerprint: nextFingerprint,
      previousFingerprint,
      changed: workbookChanged,
      appliesTo: 'process',
      message: workbookChanged
        ? previousFingerprint
          ? 'New or changed spreadsheet detected — process template can receive workbook updates.'
          : 'Spreadsheet ready to apply to the process template.'
        : 'Workbook matches the last applied revision for this process.',
    },
  }
}

/**
 * Decide whether a planned step may proceed given existing-target policy.
 * Returns { ok, errors, skippedStepIds, assessment }.
 */
export function gateExistingTargetUpdates({
  targetStepIds,
  assessment,
  updatePolicy = 'require-confirmation',
  confirmProcessUpdate = false,
  confirmProjectUpdate = false,
}) {
  const errors = []
  const skippedStepIds = []
  const planned = new Set(targetStepIds)

  // Backlog changes the process's backlog levels, which every project on the process shares.
  const processTouched = planned.has('process') || planned.has('layout') || planned.has('backlog')
  const projectTouched = planned.has('project') || planned.has('teams') || planned.has('backlog')

  if (updatePolicy === 'skip-existing') {
    if (assessment.process.exists && planned.has('process')) {
      skippedStepIds.push('process')
    }
    if (assessment.project.exists && planned.has('project')) {
      skippedStepIds.push('project')
    }
  }

  if (updatePolicy === 'require-confirmation') {
    if (
      processTouched &&
      assessment.process.exists &&
      (planned.has('process') ||
        planned.has('backlog') ||
        (planned.has('layout') && assessment.workbook.changed)) &&
      !confirmProcessUpdate
    ) {
      errors.push(
        `Process "${assessment.process.name}" already exists. Confirm update before applying process/workbook changes.`,
      )
    }

    if (projectTouched && assessment.project.exists && planned.has('project') && !confirmProjectUpdate) {
      errors.push(
        `Project "${assessment.project.name}" already exists. Confirm update before project creation/update work.`,
      )
    }
  }

  if (updatePolicy === 'create-only') {
    if (assessment.process.exists && processTouched) {
      errors.push(
        `Process "${assessment.process.name}" already exists and update policy is create-only.`,
      )
    }
    if (assessment.project.exists && planned.has('project')) {
      errors.push(
        `Project "${assessment.project.name}" already exists and update policy is create-only.`,
      )
    }
  }

  return {
    ok: errors.length === 0,
    errors,
    skippedStepIds,
    assessment,
  }
}

export function workbookApplyKey(orgUrl, processName) {
  return `${String(orgUrl || '')
    .trim()
    .toLowerCase()
    .replace(/\/+$/, '')}::${String(processName || '')
    .trim()
    .toLowerCase()}`
}

/**
 * Validate typed process/project names for create/update against policy.
 * Returns field errors and whether the run can proceed for naming.
 * With targetStepIds, policy only applies to the targets those steps change
 * (process: Process / Layout / Backlog; project: Project), as the runner does.
 */
export function validateTargetNames({
  processName,
  projectName,
  assessment,
  updatePolicy = 'require-confirmation',
  confirmProcessUpdate = false,
  confirmProjectUpdate = false,
  requireProjectName = true,
  targetStepIds = null,
}) {
  const errors = {
    processName: [],
    projectName: [],
    policy: [],
  }

  const process = String(processName || '').trim()
  const project = String(projectName || '').trim()

  if (!process) {
    errors.processName.push('Enter the process name to create or update.')
  } else if (process.length < 3) {
    errors.processName.push('Process name must be at least 3 characters.')
  } else if (INVALID_NAME_CHARS.test(process)) {
    errors.processName.push('Process name contains invalid characters.')
  }

  if (requireProjectName) {
    if (!project) {
      errors.projectName.push('Enter the project name to create or update.')
    } else if (project.length < 3) {
      errors.projectName.push('Project name must be at least 3 characters.')
    } else if (INVALID_NAME_CHARS.test(project)) {
      errors.projectName.push('Project name contains invalid characters.')
    }
  }

  const planned = targetStepIds ? new Set(targetStepIds) : null
  const checkProcess = Boolean(
    assessment?.process.exists &&
      (!planned || planned.has('process') || planned.has('layout') || planned.has('backlog')),
  )
  const checkProject = Boolean(
    requireProjectName && assessment?.project.exists && (!planned || planned.has('project')),
  )

  if (updatePolicy === 'require-confirmation') {
    if (checkProcess && !confirmProcessUpdate) {
      errors.policy.push(
        `Process "${process}" already exists. Confirm update before the workflow can proceed.`,
      )
    }
    if (checkProject && !confirmProjectUpdate) {
      errors.policy.push(
        `Project "${project}" already exists. Confirm update before the workflow can proceed.`,
      )
    }
  }

  if (updatePolicy === 'create-only') {
    if (checkProcess) {
      errors.policy.push(
        `Process "${process}" already exists and policy is create-only.`,
      )
    }
    if (checkProject) {
      errors.policy.push(
        `Project "${project}" already exists and policy is create-only.`,
      )
    }
  }

  const all = [...errors.processName, ...errors.projectName, ...errors.policy]
  return {
    ok: all.length === 0,
    errors,
    messages: all,
  }
}
