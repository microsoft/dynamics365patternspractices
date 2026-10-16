import { describe, expect, it, vi } from 'vitest'
import {
  migrateCompletedStepIds,
  resolveTargetSteps,
  runWorkflowFlow,
  validateRunnerConfig,
  workflowDefinitions,
} from './workflowEngine'

const baseConfig = {
  orgUrl: 'https://dev.azure.com/contoso',
  pat: '01234567890123456789',
  templatePath: 'C:\\templates\\guide.xlsx',
  workbookVersion: '2026.08',
  projectName: 'Contoso-BPC',
  processName: 'Business Process Catalog',
  threads: 4,
  maxRetries: 2,
  dryRun: true,
  layoutSheet: 'Page Layout',
  rootAreaPath: 'Contoso-BPC',
  backlogSheet: 'Backlog Config',
  updatePolicy: 'always-update',
  knownProcesses: [],
  knownProjects: [],
}

const instantSuccess = async (step) => ({
  details: `${step.id} ok`,
  warnings: [],
  workbookApplied:
    step.id === 'process'
      ? { fingerprint: 'guide.xlsx::2026.08', processName: 'Business Process Catalog' }
      : undefined,
})

describe('migrateCompletedStepIds', () => {
  it('maps legacy creation to process + project', () => {
    expect(migrateCompletedStepIds(['creation', 'layout'])).toEqual([
      'process',
      'project',
      'layout',
    ])
  })
})

describe('resolveTargetSteps', () => {
  it('runs process and layout before project in dependency-aware mode', () => {
    expect(resolveTargetSteps('single', 'project', [])).toEqual([
      'process',
      'layout',
      'project',
    ])
    expect(resolveTargetSteps('single', 'layout', [])).toEqual(['process', 'layout'])
  })

  it('does not start project until process and layout are done', () => {
    // Same run may include layout then project, in that order.
    expect(resolveTargetSteps('single', 'teams', ['process'])).toEqual([
      'layout',
      'project',
      'teams',
    ])
    expect(resolveTargetSteps('single', 'teams', ['process', 'layout'])).toEqual([
      'project',
      'teams',
    ])
    // Project-phase steps are withheld when neither process nor layout are available yet.
    expect(resolveTargetSteps('full', 'backlog', [])).toEqual([
      'process',
      'layout',
      'project',
      'teams',
      'backlog',
      'catalog',
      'report',
    ])
  })

  it('returns incomplete steps for full mode in the new order', () => {
    expect(resolveTargetSteps('full', 'process', ['layout'])).toEqual([
      'process',
      'project',
      'teams',
      'backlog',
      'catalog',
      'report',
    ])
  })

  it('returns empty when selected flow is already complete', () => {
    expect(resolveTargetSteps('single', 'layout', ['process', 'layout'])).toEqual([])
    expect(
      resolveTargetSteps(
        'full',
        'backlog',
        workflowDefinitions.map((step) => step.id),
      ),
    ).toEqual([])
  })

  it('runs only the selected step in step mode even when already completed', () => {
    expect(resolveTargetSteps('step', 'teams', ['process', 'layout', 'project', 'teams'])).toEqual([
      'teams',
    ])
    expect(resolveTargetSteps('step', 'backlog', [])).toEqual(['backlog'])
    expect(resolveTargetSteps('step', 'catalog', ['process'])).toEqual(['catalog'])
  })

  it('runs the selected step and every later step in from mode, including completed ones', () => {
    const all = workflowDefinitions.map((step) => step.id)
    expect(resolveTargetSteps('from', 'layout', all)).toEqual([
      'layout',
      'project',
      'teams',
      'backlog',
      'catalog',
      'report',
    ])
    expect(resolveTargetSteps('from', 'catalog', ['process', 'layout'])).toEqual([
      'catalog',
      'report',
    ])
    expect(resolveTargetSteps('from', 'process', [])).toEqual(all)
  })

  it('withholds project-phase steps in from mode until process and layout are done', () => {
    expect(resolveTargetSteps('from', 'teams', ['process'])).toEqual([])
    expect(resolveTargetSteps('from', 'layout', [])).toEqual(['layout'])
  })
})

describe('validateRunnerConfig', () => {
  it('requires root area path only when teams is planned', () => {
    const withoutArea = { ...baseConfig, rootAreaPath: '', projectName: '' }
    expect(validateRunnerConfig(withoutArea, ['process'])).toEqual([])
    expect(validateRunnerConfig(withoutArea, ['teams'])).toContain(
      'Root area path (or project name) is required for the teams & areas step.',
    )
    expect(validateRunnerConfig({ ...baseConfig, rootAreaPath: '' }, ['teams'])).toEqual([])
  })

  it('allows process/layout without project name', () => {
    const noProject = { ...baseConfig, projectName: '' }
    expect(validateRunnerConfig(noProject, ['process', 'layout'])).toEqual([])
    expect(validateRunnerConfig(noProject, ['project'])).toContain(
      'Project name must be at least 3 characters.',
    )
  })

  it('requires layout and backlog sheet names for those steps', () => {
    expect(
      validateRunnerConfig({ ...baseConfig, layoutSheet: '' }, ['layout']),
    ).toContain('Layout worksheet name is required for the page layout step.')
    expect(
      validateRunnerConfig({ ...baseConfig, backlogSheet: '  ' }, ['backlog']),
    ).toContain('Backlog worksheet name is required for the backlog step.')
  })
})

describe('runWorkflowFlow', () => {
  it('blocks project until process and layout finish', async () => {
    const executeStep = vi.fn(instantSuccess)

    const result = await runWorkflowFlow({
      mode: 'single',
      selectedWorkflowId: 'project',
      completedStepIds: [],
      config: baseConfig,
      executeStep,
    })

    expect(result.ok).toBe(true)
    expect(executeStep.mock.calls.map(([step]) => step.id)).toEqual([
      'process',
      'layout',
      'project',
    ])
  })

  it('requires confirmation when updating an existing process', async () => {
    const result = await runWorkflowFlow({
      mode: 'single',
      selectedWorkflowId: 'process',
      completedStepIds: [],
      config: {
        ...baseConfig,
        updatePolicy: 'require-confirmation',
        confirmProcessUpdate: false,
        knownProcesses: [{ name: 'Business Process Catalog' }],
      },
      executeStep: instantSuccess,
    })

    expect(result.ok).toBe(false)
    expect(result.error.code).toBe('UPDATE_CONFIRMATION_REQUIRED')
  })

  it('retries transient throttle errors then succeeds', async () => {
    let layoutAttempts = 0
    const executeStep = vi.fn(async (step) => {
      if (step.id === 'layout') {
        layoutAttempts += 1
        if (layoutAttempts < 3) {
          const error = new Error('throttled')
          error.code = 'ADO_THROTTLED'
          error.transient = true
          throw error
        }
      }
      return instantSuccess(step)
    })

    const result = await runWorkflowFlow({
      mode: 'single',
      selectedWorkflowId: 'layout',
      completedStepIds: ['process'],
      config: { ...baseConfig, maxRetries: 2 },
      executeStep,
    })

    expect(result.ok).toBe(true)
    expect(layoutAttempts).toBe(3)
    expect(result.completedStepIds).toEqual(['process', 'layout'])
  })

  it('does not retry permanent INVALID_PROJECT errors', async () => {
    const executeStep = vi.fn(async (step) => {
      if (step.id === 'project') {
        const error = new Error('bad project')
        error.code = 'INVALID_PROJECT'
        error.transient = false
        throw error
      }
      return instantSuccess(step)
    })

    const result = await runWorkflowFlow({
      mode: 'single',
      selectedWorkflowId: 'project',
      completedStepIds: ['process', 'layout'],
      config: { ...baseConfig, maxRetries: 3 },
      executeStep,
    })

    expect(result.ok).toBe(false)
    expect(result.error.code).toBe('INVALID_PROJECT')
    expect(executeStep).toHaveBeenCalledTimes(1)
    expect(result.completedStepIds).toEqual(['process', 'layout'])
  })

  it('returns partial completedStepIds when a later step fails', async () => {
    const executeStep = vi.fn(async (step) => {
      if (step.id === 'teams') {
        const error = new Error('teams failed')
        error.code = 'TEAMS_FAILED'
        throw error
      }
      return instantSuccess(step)
    })

    const result = await runWorkflowFlow({
      mode: 'full',
      selectedWorkflowId: 'backlog',
      completedStepIds: [],
      config: baseConfig,
      executeStep,
    })

    expect(result.ok).toBe(false)
    expect(result.completedStepIds).toEqual(['process', 'layout', 'project'])
  })

  it('records workbook apply metadata after process step', async () => {
    const result = await runWorkflowFlow({
      mode: 'single',
      selectedWorkflowId: 'process',
      completedStepIds: [],
      config: baseConfig,
      executeStep: instantSuccess,
    })

    expect(result.ok).toBe(true)
    expect(result.appliedWorkbook).toEqual({
      fingerprint: 'guide.xlsx::2026.08',
      processName: 'Business Process Catalog',
    })
  })

  it('stops promptly when aborted', async () => {
    const controller = new AbortController()
    const executeStep = vi.fn(async (step) => {
      if (step.id === 'process') {
        controller.abort()
      }
      await new Promise((resolve) => setTimeout(resolve, 30))
      return instantSuccess(step)
    })

    const result = await runWorkflowFlow({
      mode: 'full',
      selectedWorkflowId: 'backlog',
      completedStepIds: [],
      config: baseConfig,
      executeStep,
      signal: controller.signal,
    })

    expect(result.ok).toBe(false)
    expect(result.error.code).toBe('ABORTED')
    expect(result.completedStepIds.length).toBeLessThan(5)
  })
})
