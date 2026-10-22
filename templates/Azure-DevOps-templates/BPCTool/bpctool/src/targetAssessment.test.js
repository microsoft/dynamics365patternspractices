import { describe, expect, it } from 'vitest'
import {
  assessExistingTargets,
  buildWorkbookFingerprint,
  gateExistingTargetUpdates,
  validateTargetNames,
} from './targetAssessment'

describe('assessExistingTargets', () => {
  it('flags create vs update and workbook deltas', () => {
    const assessment = assessExistingTargets({
      processName: 'Business Process Catalog',
      projectName: 'Contoso-BPC',
      knownProcesses: [{ name: 'Business Process Catalog' }],
      knownProjects: [],
      templatePath: 'C:\\templates\\guide-v2.xlsx',
      workbookVersion: '2026.08',
      lastAppliedWorkbook: {
        fingerprint: buildWorkbookFingerprint({
          templatePath: 'C:\\templates\\guide-v1.xlsx',
          workbookVersion: '2026.07',
        }),
      },
    })

    expect(assessment.process.exists).toBe(true)
    expect(assessment.process.recommendedAction).toBe('update-from-workbook')
    expect(assessment.project.exists).toBe(false)
    expect(assessment.project.recommendedAction).toBe('create')
    expect(assessment.workbook.changed).toBe(true)
  })
})

describe('gateExistingTargetUpdates', () => {
  const baseAssessment = assessExistingTargets({
    processName: 'Business Process Catalog',
    projectName: 'Contoso-BPC',
    knownProcesses: [{ name: 'Business Process Catalog' }],
    knownProjects: [{ name: 'Contoso-BPC' }],
    templatePath: 'guide.xlsx',
    workbookVersion: '1',
    lastAppliedWorkbook: null,
  })

  it('requires confirmation before updating existing process/project', () => {
    const gated = gateExistingTargetUpdates({
      targetStepIds: ['process', 'layout', 'project'],
      assessment: baseAssessment,
      updatePolicy: 'require-confirmation',
      confirmProcessUpdate: false,
      confirmProjectUpdate: false,
    })

    expect(gated.ok).toBe(false)
    expect(gated.errors.join(' ')).toMatch(/Confirm update/)
  })

  it('allows updates when confirmations are set', () => {
    const gated = gateExistingTargetUpdates({
      targetStepIds: ['process', 'layout', 'project'],
      assessment: baseAssessment,
      updatePolicy: 'require-confirmation',
      confirmProcessUpdate: true,
      confirmProjectUpdate: true,
    })

    expect(gated.ok).toBe(true)
  })

  it('skips existing targets when policy is skip-existing', () => {
    const gated = gateExistingTargetUpdates({
      targetStepIds: ['process', 'layout', 'project'],
      assessment: baseAssessment,
      updatePolicy: 'skip-existing',
    })

    expect(gated.ok).toBe(true)
    expect(gated.skippedStepIds).toEqual(['process', 'project'])
  })

  it('treats a backlog-only run as changing the existing process', () => {
    const gate = (updatePolicy, confirmProcessUpdate = false) =>
      gateExistingTargetUpdates({
        targetStepIds: ['backlog'],
        assessment: baseAssessment,
        updatePolicy,
        confirmProcessUpdate,
      })

    expect(gate('require-confirmation').errors).toEqual([
      'Process "Business Process Catalog" already exists. Confirm update before applying process/workbook changes.',
    ])
    expect(gate('require-confirmation', true).ok).toBe(true)
    expect(gate('create-only').errors).toEqual([
      'Process "Business Process Catalog" already exists and update policy is create-only.',
    ])
  })
})

describe('validateTargetNames', () => {
  it('requires typed process and project names', () => {
    const result = validateTargetNames({
      processName: '',
      projectName: '',
      assessment: assessExistingTargets({
        processName: '',
        projectName: '',
        knownProcesses: [],
        knownProjects: [],
        templatePath: 'a.xlsx',
      }),
      updatePolicy: 'always-update',
    })

    expect(result.ok).toBe(false)
    expect(result.errors.processName[0]).toMatch(/Enter the process name/)
    expect(result.errors.projectName[0]).toMatch(/Enter the project name/)
  })

  it('accepts new names under create policy', () => {
    const result = validateTargetNames({
      processName: 'Business Process Catalog',
      projectName: 'Contoso-BPC',
      assessment: assessExistingTargets({
        processName: 'Business Process Catalog',
        projectName: 'Contoso-BPC',
        knownProcesses: [],
        knownProjects: [],
        templatePath: 'a.xlsx',
      }),
      updatePolicy: 'require-confirmation',
    })

    expect(result.ok).toBe(true)
  })

  it('only applies the policy to targets the planned steps change', () => {
    const assessment = assessExistingTargets({
      processName: 'Business Process Catalog',
      projectName: 'Contoso-BPC',
      knownProcesses: [{ name: 'Business Process Catalog' }],
      knownProjects: [{ name: 'Contoso-BPC' }],
      templatePath: 'a.xlsx',
    })
    const validate = (targetStepIds) =>
      validateTargetNames({
        processName: 'Business Process Catalog',
        projectName: 'Contoso-BPC',
        assessment,
        updatePolicy: 'require-confirmation',
        targetStepIds,
      })

    expect(validate(['catalog', 'report']).ok).toBe(true)
    expect(validate(['layout']).errors.policy).toEqual([
      'Process "Business Process Catalog" already exists. Confirm update before the workflow can proceed.',
    ])
    expect(validate(['project', 'teams']).errors.policy).toEqual([
      'Project "Contoso-BPC" already exists. Confirm update before the workflow can proceed.',
    ])
    expect(validate(['backlog']).errors.policy).toEqual([
      'Process "Business Process Catalog" already exists. Confirm update before the workflow can proceed.',
    ])
    expect(validate(null).errors.policy).toHaveLength(2)
  })
})
