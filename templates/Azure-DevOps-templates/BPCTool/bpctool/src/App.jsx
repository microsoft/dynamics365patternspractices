import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import {
  DEVLABS_MULTIVALUE,
  fetchProcesses,
  fetchProjects,
  getMultivalueExtensionStatus,
  installMultivalueExtension,
  stepsRequireMultivalueExtension,
} from './adoApi'
import { normalizeAdoOrgUrl, parseAdoOrgUrl } from './adoOrgUrl'
import CollapsibleSection from './CollapsibleSection'
import ConnectionPanel from './ConnectionPanel'
import PathPickerModal from './PathPickerModal'
import {
  assessExistingTargets,
  validateTargetNames,
  workbookApplyKey,
} from './targetAssessment'
import { describeCatalogProgress } from './catalogProgress'
import RunResultsCard, { DataChecks } from './RunResultsCard'
import {
  buildRunnerJobBody,
  cancelRunnerJob,
  pollRunnerJob,
  RUNNER_UNREACHABLE,
  runnerFetch,
  runRunnerJob,
} from './runnerApi'
import {
  formatDurationMs,
  formatTimingSummary,
  migrateCompletedStepIds,
  resolveTargetSteps,
  runWorkflowFlow,
  stepExecutors,
  workflowDefinitions,
} from './workflowEngine'

const COMPLETION_CACHE_KEY = 'bpcCompletedSteps'
const WORKBOOK_APPLIES_KEY = 'bpcWorkbookApplies'
const SESSION_ORG_URL = 'bpcSessionOrgUrl'
const SESSION_PAT = 'bpcSessionPat'
const SESSION_PROJECT = 'bpcSessionProject'
const SESSION_PROJECT_DESCRIPTION = 'bpcSessionProjectDescription'
const SESSION_PROCESS = 'bpcSessionProcess'
const SESSION_EXECUTION_MODE = 'bpcSessionExecutionMode'
const SESSION_ACTIVE_RUNNER_JOB = 'bpcActiveRunnerJob'
const OUTPUT_ROOT_KEY = 'bpcOutputRoot'

const readActiveRunnerJob = () => {
  try {
    const saved = JSON.parse(readSession(SESSION_ACTIVE_RUNNER_JOB, 'null'))
    return saved?.jobId ? saved : null
  } catch {
    return null
  }
}

const loadJson = (key, fallbackValue) => {
  try {
    return JSON.parse(localStorage.getItem(key) ?? JSON.stringify(fallbackValue))
  } catch {
    return fallbackValue
  }
}

const readSession = (key, fallback = '') => {
  try {
    return sessionStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

const writeSession = (key, value) => {
  try {
    if (value) {
      sessionStorage.setItem(key, value)
    } else {
      sessionStorage.removeItem(key)
    }
  } catch {
    /* private mode / quota */
  }
}

const derivedRootAreaPath = (projectName) => (projectName || '').trim()

/** True when empty or still equal to the project root (auto default). */
const isAutoRootAreaPath = (path, projectName = '') => {
  const trimmed = (path || '').trim()
  if (!trimmed) {
    return true
  }
  const project = (projectName || '').trim()
  if (project && trimmed === project) {
    return true
  }
  // Legacy auto-default from earlier builds: Project\\Business Process Catalog
  const legacySuffix = '\\Business Process Catalog'
  return (
    trimmed === 'Business Process Catalog' ||
    trimmed.endsWith(legacySuffix)
  )
}

const buildCacheKey = (orgUrl, processName, projectName) => {
  const normalized = normalizeAdoOrgUrl(orgUrl)
  const orgKey = (normalized.ok ? normalized.url : orgUrl.trim())
    .toLowerCase()
    .replace(/\/+$/, '')
  const processKey = processName.trim().toLowerCase()
  const projectKey = projectName.trim().toLowerCase()

  if (!orgKey || !processKey) {
    return null
  }

  return `${orgKey}::${processKey}::${projectKey || '__pre_project__'}`
}

const normalizeCompletionCache = (raw) => {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return {}
  }

  return Object.fromEntries(
    Object.entries(raw)
      .filter(([key, value]) => typeof key === 'string' && Array.isArray(value))
      .map(([key, value]) => [key, migrateCompletedStepIds(value)]),
  )
}

const normalizeWorkbookApplies = (raw) => {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return {}
  }
  return raw
}

const buildStepStatuses = (completedStepIds) => {
  const completedSet = new Set(completedStepIds)

  return Object.fromEntries(
    workflowDefinitions.map((workflow) => [
      workflow.id,
      completedSet.has(workflow.id) ? 'completed' : 'idle',
    ]),
  )
}

const parseBoundedInt = (rawValue, fallback) => {
  if (rawValue === '' || rawValue === null || rawValue === undefined) {
    return Number.NaN
  }

  const parsed = Number(rawValue)
  return Number.isFinite(parsed) ? parsed : fallback
}

const statusLabelMap = {
  idle: 'Not run',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  skipped: 'Skipped',
}

function App() {
  const [orgUrl, setOrgUrlState] = useState(() => readSession(SESSION_ORG_URL))
  const [pat, setPatState] = useState(() => readSession(SESSION_PAT))
  const [showPat, setShowPat] = useState(false)
  const [selectedWorkflowId, setSelectedWorkflowId] = useState(
    workflowDefinitions[0].id,
  )
  const [runMode, setRunMode] = useState('step')
  const [executionMode, setExecutionModeState] = useState(() => {
    const stored = readSession(SESSION_EXECUTION_MODE, 'runner')
    return ['api', 'runner', 'simulate'].includes(stored) ? stored : 'runner'
  })
  const [templatePath, setTemplatePath] = useState('')
  const [catalogSourceDir, setCatalogSourceDir] = useState('')
  const [outputRoot, setOutputRoot] = useState('')
  // Empty = runner default (BPCTOOL_OUTPUT_DIR or bpctool/runner-out).
  const [outputRootChoice, setOutputRootChoiceState] = useState(() => {
    try {
      return localStorage.getItem(OUTPUT_ROOT_KEY) || ''
    } catch {
      return ''
    }
  })
  const [pathPickerOpen, setPathPickerOpen] = useState(false)
  const [pathPickerMode, setPathPickerMode] = useState('file')
  const [pathPickerTarget, setPathPickerTarget] = useState('template')
  const [workbookVersion, setWorkbookVersion] = useState('')
  const [planResult, setPlanResult] = useState(null)
  const [planLoading, setPlanLoading] = useState(false)
  const [planError, setPlanError] = useState('')
  const [updatePolicy, setUpdatePolicy] = useState('require-confirmation')
  const [confirmProcessUpdate, setConfirmProcessUpdate] = useState(false)
  const [confirmProjectUpdate, setConfirmProjectUpdate] = useState(false)
  const [projectName, setProjectNameState] = useState(() => readSession(SESSION_PROJECT))
  const [projectDescription, setProjectDescriptionState] = useState(() =>
    readSession(SESSION_PROJECT_DESCRIPTION),
  )
  const [processName, setProcessNameState] = useState(() => readSession(SESSION_PROCESS))
  const [threads, setThreads] = useState(4)
  const [maxRetries, setMaxRetries] = useState(2)
  const [layoutSheet, setLayoutSheet] = useState('Page Layout')
  // null = follow project name from section 2; string = user override
  const [rootAreaPathOverride, setRootAreaPathOverride] = useState(null)
  const [backlogSheet, setBacklogSheet] = useState('Backlog Config')
  // Live ADO apply by default in Runner mode. Use Preview plan for planning;
  // check this only when you want writers to skip Azure DevOps mutations.
  const [dryRun, setDryRun] = useState(false)
  const [convertMarkdownToHtml, setConvertMarkdownToHtml] = useState(false)
  const [includeDeprecatedDeleted, setIncludeDeprecatedDeleted] = useState(false)
  const [runMessage, setRunMessage] = useState('No action run yet.')
  const [runLogs, setRunLogs] = useState([])
  const [isRunning, setIsRunning] = useState(false)
  const [completionCache, setCompletionCache] = useState(() => {
    try {
      localStorage.removeItem('bpcProfiles')
      sessionStorage.removeItem('bpcSessionProfile')
    } catch {
      /* ignore */
    }
    const scoped = normalizeCompletionCache(loadJson(COMPLETION_CACHE_KEY, {}))
    localStorage.setItem(COMPLETION_CACHE_KEY, JSON.stringify(scoped))
    return scoped
  })
  const [workbookApplies, setWorkbookApplies] = useState(() =>
    normalizeWorkbookApplies(loadJson(WORKBOOK_APPLIES_KEY, {})),
  )
  const [runOverlay, setRunOverlay] = useState({ key: null, statuses: {} })
  const [projects, setProjects] = useState([])
  const [fetchingProjects, setFetchingProjects] = useState(false)
  const [projectsFetched, setProjectsFetched] = useState(false)
  const [processes, setProcesses] = useState([])
  const [fetchingProcesses, setFetchingProcesses] = useState(false)
  const [processesFetched, setProcessesFetched] = useState(false)
  const [inventoryRefreshKey, setInventoryRefreshKey] = useState(0)
  const [apiStatusText, setApiStatusText] = useState(
    'Fetch projects to validate the PAT against Azure DevOps.',
  )
  const [checkedExtensionStatus, setExtensionStatus] = useState('unknown')
  const [checkedExtensionMessage, setExtensionMessage] = useState('')
  const [extensionBusy, setExtensionBusy] = useState(false)

  const [catalogProgress, setCatalogProgress] = useState(null)
  const [runOutcome, setRunOutcome] = useState(null)
  const [cancelRequested, setCancelRequested] = useState(false)
  const catalogProgressSummary = useMemo(
    () => describeCatalogProgress(catalogProgress),
    [catalogProgress],
  )

  const isRunningRef = useRef(false)
  const abortControllerRef = useRef(null)
  const activeJobIdRef = useRef(null)
  const runnerJobStartingRef = useRef(false)
  const pendingCancelRef = useRef(false)

  const setOutputRootChoice = (value) => {
    setOutputRootChoiceState(value)
    try {
      if (value.trim()) {
        localStorage.setItem(OUTPUT_ROOT_KEY, value.trim())
      } else {
        localStorage.removeItem(OUTPUT_ROOT_KEY)
      }
    } catch {
      /* ignore */
    }
  }

  const outputFolderName = useMemo(() => {
    const parsed = parseAdoOrgUrl(orgUrl)
    const project = projectName.trim()
    if (!parsed.ok || !project) {
      return '<org>_<project>'
    }
    // Same rule as the runner's default_output_dir.
    const slug = `${parsed.org}_${project}`
      .replace(/[^A-Za-z0-9._-]+/g, '_')
      .replace(/^[._-]+|[._-]+$/g, '')
    return slug || 'ado'
  }, [orgUrl, projectName])

  const pathPickerInitial =
    pathPickerTarget === 'catalog'
      ? catalogSourceDir
      : pathPickerTarget === 'output'
        ? outputRootChoice || outputRoot
        : templatePath

  const rootAreaPath =
    rootAreaPathOverride ?? derivedRootAreaPath(projectName)

  const loadRunnerDefaults = async ({ onlyEmpty = false } = {}) => {
    try {
      const response = await runnerFetch('/api/defaults')
      if (!response.ok) {
        throw new Error(`Runner defaults unavailable (${response.status})`)
      }
      const defaults = await response.json()
      setRunMessage((current) => (current === RUNNER_UNREACHABLE ? 'No action run yet.' : current))
      if (defaults.output_root) {
        setOutputRoot(defaults.output_root)
      }
      const fillTemplate = defaults.excel_file && !(onlyEmpty && templatePath.trim())
      const fillCatalog =
        defaults.catalog_source_dir && !(onlyEmpty && catalogSourceDir.trim())
      if (fillTemplate) {
        setTemplatePath(defaults.excel_file)
      }
      if (fillCatalog) {
        setCatalogSourceDir(defaults.catalog_source_dir)
      }
      if (defaults.release_label && !workbookVersion.trim()) {
        setWorkbookVersion(defaults.release_label)
      }
      const release = defaults.release_label ? ` (release ${defaults.release_label})` : ''
      if (defaults.excel_file && defaults.catalog_source_dir) {
        setRunMessage(`Loaded template and catalog folder${release} from ${defaults.bpc_files_root}.`)
      } else if (defaults.catalog_source_dir) {
        setRunMessage(
          `Loaded catalog folder${release}. No "ADO template guideline*.xlsx" found there — set Template workbook path (Browse…).`,
        )
      } else if (!onlyEmpty) {
        setRunMessage(
          defaults.bpc_files_root_exists === 'yes'
            ? `No catalog workbooks found in ${defaults.bpc_files_root} or its release subfolders. Set paths with Browse….`
            : `${defaults.bpc_files_root} does not exist. Create it with one subfolder per release (e.g. 2026-Q4), or set paths with Browse….`,
        )
      }
    } catch (error) {
      if (error instanceof Error && error.message === RUNNER_UNREACHABLE) {
        setRunMessage(RUNNER_UNREACHABLE)
        return false
      }
      if (onlyEmpty) {
        return true
      }
      const message =
        error instanceof Error
          ? error.message
          : 'Failed to reach local runner. Quit and relaunch Start BPCTool (or npm start).'
      setRunMessage(`Could not load runner defaults: ${message}`)
    }
    return true
  }

  // Bumped whenever the org URL or PAT changes, so a fetch still in flight for the
  // previous connection doesn't record its lists against the new one.
  const connectionGenRef = useRef(0)

  const setOrgUrl = (value) => {
    connectionGenRef.current += 1
    setOrgUrlState(value)
    writeSession(SESSION_ORG_URL, value)
    setProjects([])
    setProjectsFetched(false)
    setProcesses([])
    setProcessesFetched(false)
  }

  const setPat = (value) => {
    connectionGenRef.current += 1
    setPatState(value)
    writeSession(SESSION_PAT, value)
    setProjectsFetched(false)
    setProcessesFetched(false)
  }

  const setProjectName = (value) => {
    setProjectNameState(value)
    writeSession(SESSION_PROJECT, value)
    setConfirmProjectUpdate(false)
    // If override still looks auto-derived from the previous project, drop it so
    // the field follows the new project name from section 2.
    if (
      rootAreaPathOverride !== null &&
      isAutoRootAreaPath(rootAreaPathOverride, projectName)
    ) {
      setRootAreaPathOverride(null)
    }
  }

  const setProjectDescription = (value) => {
    setProjectDescriptionState(value)
    writeSession(SESSION_PROJECT_DESCRIPTION, value)
  }

  const setRootAreaPathValue = (value) => {
    const derived = derivedRootAreaPath(projectName)
    if (!value.trim() || value.trim() === derived) {
      setRootAreaPathOverride(null)
      return
    }
    setRootAreaPathOverride(value)
  }

  const setProcessName = (value) => {
    setProcessNameState(value)
    writeSession(SESSION_PROCESS, value)
    setConfirmProcessUpdate(false)
  }

  const setExecutionMode = (value) => {
    const next = ['api', 'runner'].includes(value) ? value : 'simulate'
    setExecutionModeState(next)
    writeSession(SESSION_EXECUTION_MODE, next)
  }

  const effectiveOrgUrl = useMemo(() => {
    const normalized = normalizeAdoOrgUrl(orgUrl)
    return normalized.ok ? normalized.url : orgUrl.trim()
  }, [orgUrl])

  const connectionReady = Boolean(effectiveOrgUrl && pat.trim())

  const runButtonLabel =
    executionMode !== 'runner'
      ? 'Run selected flow'
      : dryRun
        ? 'Rehearse selected flow'
        : 'Run selected flow (live)'
  const liveTargetLabel = [
    effectiveOrgUrl ? ` org ${effectiveOrgUrl}` : '',
    processName.trim() ? ` · process “${processName.trim()}”` : '',
    projectName.trim() ? ` · project “${projectName.trim()}”` : '',
  ].join('')

  const extensionCheckable = connectionReady && executionMode !== 'simulate'
  const extensionStatus = extensionCheckable ? checkedExtensionStatus : 'unknown'
  let extensionMessage = checkedExtensionMessage
  if (!extensionCheckable) {
    extensionMessage =
      executionMode === 'simulate' ? 'Simulate mode skips Azure DevOps extension checks.' : ''
  }

  useEffect(() => {
    if (!extensionCheckable) {
      return undefined
    }

    let cancelled = false
    ;(async () => {
      setExtensionBusy(true)
      setExtensionStatus('checking')
      try {
        const result = await getMultivalueExtensionStatus(
          effectiveOrgUrl,
          pat.trim(),
        )
        if (cancelled) {
          return
        }
        setExtensionStatus(result.status)
        if (result.status === 'installed') {
          setExtensionMessage(
            `${DEVLABS_MULTIVALUE.displayName} is installed and enabled.`,
          )
        } else if (result.status === 'disabled') {
          setExtensionMessage(
            `${DEVLABS_MULTIVALUE.displayName} is installed but disabled. Enable it before process/project setup.`,
          )
        } else {
          setExtensionMessage(
            `${DEVLABS_MULTIVALUE.displayName} is not installed. Required for process template and project setup.`,
          )
        }
      } catch (error) {
        if (cancelled) {
          return
        }
        const message =
          error instanceof Error ? error.message : 'Extension check failed'
        setExtensionStatus('error')
        setExtensionMessage(`Could not verify Multivalue extension: ${message}`)
      } finally {
        if (!cancelled) {
          setExtensionBusy(false)
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [extensionCheckable, effectiveOrgUrl, pat])

  const cacheKey = useMemo(
    () => buildCacheKey(effectiveOrgUrl, processName, projectName),
    [effectiveOrgUrl, processName, projectName],
  )

  const lastAppliedWorkbook = useMemo(() => {
    const key = workbookApplyKey(effectiveOrgUrl, processName)
    return workbookApplies[key] ?? null
  }, [workbookApplies, effectiveOrgUrl, processName])

  const targetAssessment = useMemo(
    () =>
      assessExistingTargets({
        processName,
        projectName,
        knownProcesses: processes,
        knownProjects: projects,
        templatePath,
        workbookVersion,
        lastAppliedWorkbook,
      }),
    [
      processName,
      projectName,
      processes,
      projects,
      templatePath,
      workbookVersion,
      lastAppliedWorkbook,
    ],
  )

  const completedStepIds = useMemo(
    () => (cacheKey ? migrateCompletedStepIds(completionCache[cacheKey] ?? []) : []),
    [cacheKey, completionCache],
  )

  const plannedStepIds = useMemo(
    () => resolveTargetSteps(runMode, selectedWorkflowId, completedStepIds),
    [runMode, selectedWorkflowId, completedStepIds],
  )

  const nameValidation = useMemo(
    () =>
      validateTargetNames({
        processName,
        projectName,
        assessment: targetAssessment,
        updatePolicy,
        confirmProcessUpdate,
        confirmProjectUpdate,
        requireProjectName: true,
        targetStepIds: plannedStepIds,
      }),
    [
      processName,
      projectName,
      targetAssessment,
      updatePolicy,
      confirmProcessUpdate,
      confirmProjectUpdate,
      plannedStepIds,
    ],
  )

  const stepStatuses = useMemo(() => {
    const base = buildStepStatuses(completedStepIds)
    if (runOverlay.key !== cacheKey) {
      return base
    }

    return { ...base, ...runOverlay.statuses }
  }, [completedStepIds, runOverlay, cacheKey])

  const selectedWorkflow = useMemo(
    () =>
      workflowDefinitions.find((workflow) => workflow.id === selectedWorkflowId),
    [selectedWorkflowId],
  )

  const runModeLabel =
    runMode === 'full'
      ? 'Full flow'
      : runMode === 'step'
        ? 'Selected step only'
        : runMode === 'from'
          ? 'From selected step onward'
          : 'Dependency-aware'

  const runPlanLabel = useMemo(() => {
    if (plannedStepIds.length === 0) {
      if (runMode === 'full') {
        return 'Will run: nothing new (all steps already completed for this org/project).'
      }
      if (runMode === 'step') {
        return 'Will run: nothing (select a workflow card).'
      }
      if (runMode === 'from') {
        return 'Will run: nothing — Process Template and Page Layout must complete before later steps. Start from Process Template or Page Layout, or use “Selected step only”.'
      }
      return 'Will run: nothing new (selected flow already completed for this org/project). Use “Selected step only” to re-run a completed card.'
    }

    const titles = plannedStepIds.map((stepId) => {
      const step = workflowDefinitions.find((workflow) => workflow.id === stepId)
      return step?.title ?? stepId
    })

    if (runMode === 'step') {
      return `Will re-run only: ${titles[0]} (no prerequisite steps)`
    }

    if (runMode === 'from') {
      const selectedIndex = workflowDefinitions.findIndex((step) => step.id === selectedWorkflowId)
      const heldBack = workflowDefinitions.length - selectedIndex - plannedStepIds.length
      if (heldBack > 0) {
        return `Will run: ${titles.join(' → ')}. The ${heldBack} later step(s) wait until Process Template and Page Layout have completed — start from Process Template, or run them afterwards.`
      }
    }

    return `Will run: ${titles.join(' → ')}`
  }, [plannedStepIds, runMode, selectedWorkflowId])

  const persistCompletionCache = (updater) => {
    setCompletionCache((previous) => {
      const nextCache = typeof updater === 'function' ? updater(previous) : updater
      localStorage.setItem(COMPLETION_CACHE_KEY, JSON.stringify(nextCache))
      return nextCache
    })
  }

  const addLog = (message) => {
    const timestamp = new Date().toLocaleTimeString()
    setRunLogs((previousLogs) => [
      `[${timestamp}] ${message}`,
      ...previousLogs,
    ].slice(0, 120))
  }

  const refreshMultivalueExtension = async () => {
    if (!connectionReady || executionMode === 'simulate') {
      setExtensionStatus('unknown')
      setExtensionMessage(
        executionMode === 'simulate'
          ? 'Simulate mode skips Azure DevOps extension checks.'
          : '',
      )
      return 'unknown'
    }

    setExtensionBusy(true)
    setExtensionStatus('checking')
    setExtensionMessage('Checking DevLabs Multivalue control on the organization…')
    try {
      const result = await getMultivalueExtensionStatus(
        effectiveOrgUrl,
        pat.trim(),
      )
      setExtensionStatus(result.status)
      if (result.status === 'installed') {
        setExtensionMessage(
          `${DEVLABS_MULTIVALUE.displayName} is installed and enabled.`,
        )
      } else if (result.status === 'disabled') {
        setExtensionMessage(
          `${DEVLABS_MULTIVALUE.displayName} is installed but disabled. Enable it in Organization settings → Extensions before process/project setup.`,
        )
      } else {
        setExtensionMessage(
          `${DEVLABS_MULTIVALUE.displayName} is not installed. It is required for process template and project setup (Multi-select fields).`,
        )
      }
      return result.status
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Extension check failed'
      setExtensionStatus('error')
      setExtensionMessage(`Could not verify Multivalue extension: ${message}`)
      return 'error'
    } finally {
      setExtensionBusy(false)
    }
  }

  const handleInstallMultivalueExtension = async ({ prompted = false } = {}) => {
    if (!connectionReady) {
      return false
    }
    setExtensionBusy(true)
    setExtensionMessage('Installing DevLabs Multivalue control…')
    try {
      await installMultivalueExtension(effectiveOrgUrl, pat.trim())
      setExtensionStatus('installed')
      setExtensionMessage(
        `${DEVLABS_MULTIVALUE.displayName} installed successfully.`,
      )
      addLog('Installed DevLabs Multivalue control extension on organization.')
      return true
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Install failed'
      setExtensionStatus('missing')
      setExtensionMessage(
        `Unable to install Multivalue extension: ${message}. Install manually from ${DEVLABS_MULTIVALUE.marketplaceUrl} (org owner / Extension Management permission required), then re-check.`,
      )
      if (prompted) {
        window.alert(
          `Unable to install the DevLabs Multivalue control extension.\n\n${message}\n\nThis extension is required for process template and project setup. Install it from the Marketplace (org admin), then try again:\n${DEVLABS_MULTIVALUE.marketplaceUrl}`,
        )
      }
      return false
    } finally {
      setExtensionBusy(false)
    }
  }

  /**
   * Gate process / layout / project runs on Multivalue extension presence.
   * Prompts to install when missing; blocks if declined or install fails.
   * Skipped for Simulate and Rehearsal only (no ADO mutations; matches runner).
   */
  const ensureMultivalueExtensionForSetup = async () => {
    if (executionMode === 'simulate' || dryRun) {
      return true
    }
    if (!stepsRequireMultivalueExtension(plannedStepIds)) {
      return true
    }

    let status = extensionStatus
    if (
      status === 'unknown' ||
      status === 'error' ||
      status === 'checking'
    ) {
      status = await refreshMultivalueExtension()
    }

    if (status === 'installed') {
      return true
    }

    if (status === 'disabled') {
      window.alert(
        `${DEVLABS_MULTIVALUE.displayName} is installed but disabled on this organization.\n\nEnable it under Organization settings → Extensions before process template and project setup can proceed.`,
      )
      setRunMessage(
        'Blocked: DevLabs Multivalue extension is disabled on the organization.',
      )
      return false
    }

    if (status === 'error') {
      window.alert(
        `Could not verify the DevLabs Multivalue control extension.\n\n${extensionMessage || 'Check failed.'}\n\nProcess template and project setup require this extension. Fix PAT/permissions and re-check, or install from:\n${DEVLABS_MULTIVALUE.marketplaceUrl}`,
      )
      setRunMessage('Blocked: could not verify DevLabs Multivalue extension.')
      return false
    }

    const wantInstall = window.confirm(
      `${DEVLABS_MULTIVALUE.displayName} is not installed on this Azure DevOps organization.\n\n` +
        `It is required for process template and project setup (Multi-select fields such as Application family / Products).\n\n` +
        `Install it now with the current PAT?`,
    )
    if (!wantInstall) {
      window.alert(
        `Cannot proceed with process template and project setup without the DevLabs Multivalue control extension.\n\n` +
          `Install it from the Marketplace and re-check, then run again:\n${DEVLABS_MULTIVALUE.marketplaceUrl}`,
      )
      setRunMessage(
        'Blocked: DevLabs Multivalue extension is required for process/project setup.',
      )
      return false
    }

    const installed = await handleInstallMultivalueExtension({ prompted: true })
    if (!installed) {
      setRunMessage(
        'Blocked: could not install DevLabs Multivalue extension (required for process/project setup).',
      )
    }
    return installed
  }

  const logRunTiming = (timings, totalMs, { failed = false } = {}) => {
    if (!timings?.length && totalMs == null) {
      return
    }
    const header = failed ? 'Run timing (failed):' : 'Run timing:'
    addLog(`${header}\n${formatTimingSummary(timings || [], totalMs)}`)
  }

  const handleFetchProjects = async () => {
    if (!connectionReady) {
      return
    }

    setFetchingProjects(true)
    setProjectsFetched(false)
    setProjects([])
    setApiStatusText('Fetching projects...')
    const generation = connectionGenRef.current

    try {
      const list = await fetchProjects(effectiveOrgUrl, pat.trim())
      if (generation !== connectionGenRef.current) {
        return
      }
      setProjects(list)
      setProjectsFetched(true)
      setApiStatusText(
        `Connected. Found ${list.length} project${list.length === 1 ? '' : 's'}.`,
      )
      setRunMessage(`Fetched ${list.length} project${list.length === 1 ? '' : 's'} from Azure DevOps.`)
      addLog(`API: fetched ${list.length} projects`)
    } catch (error) {
      if (generation !== connectionGenRef.current) {
        return
      }
      const message = error instanceof Error ? error.message : 'Failed to fetch projects'
      setProjectsFetched(false)
      setApiStatusText(message)
      setRunMessage(`Fetch projects failed: ${message}`)
      addLog(`API error: ${message}`)
    } finally {
      setFetchingProjects(false)
    }
  }

  const handleFetchProcesses = async () => {
    if (!connectionReady) {
      return
    }

    setFetchingProcesses(true)
    setProcessesFetched(false)
    setProcesses([])
    setApiStatusText('Fetching processes...')
    const generation = connectionGenRef.current

    try {
      const list = await fetchProcesses(effectiveOrgUrl, pat.trim())
      if (generation !== connectionGenRef.current) {
        return
      }
      setProcesses(list)
      setProcessesFetched(true)
      setApiStatusText(
        `Fetched ${list.length} process${list.length === 1 ? '' : 'es'}.`,
      )
      setRunMessage(`Fetched ${list.length} process${list.length === 1 ? '' : 'es'} from Azure DevOps.`)
      addLog(`API: fetched ${list.length} processes`)
    } catch (error) {
      if (generation !== connectionGenRef.current) {
        return
      }
      const message = error instanceof Error ? error.message : 'Failed to fetch processes'
      setProcessesFetched(false)
      setApiStatusText(message)
      setRunMessage(`Fetch processes failed: ${message}`)
      addLog(`API error: ${message}`)
    } finally {
      setFetchingProcesses(false)
    }
  }

  // Existing processes/projects drive the policy checks and confirm boxes, so load them
  // once the connection is usable and again after each live run (which may create them).
  useEffect(() => {
    if (!connectionReady || executionMode === 'simulate') {
      return undefined
    }
    let cancelled = false
    const orgUrlAtStart = effectiveOrgUrl
    const token = pat.trim()
    const timer = setTimeout(async () => {
      setFetchingProjects(true)
      setFetchingProcesses(true)
      const [projectsResult, processesResult] = await Promise.allSettled([
        fetchProjects(orgUrlAtStart, token),
        fetchProcesses(orgUrlAtStart, token),
      ])
      setFetchingProjects(false)
      setFetchingProcesses(false)
      if (cancelled) {
        return
      }
      const found = []
      const failed = []
      const reason = (result) =>
        result.reason instanceof Error ? result.reason.message : String(result.reason)
      if (projectsResult.status === 'fulfilled') {
        setProjects(projectsResult.value)
        setProjectsFetched(true)
        const count = projectsResult.value.length
        found.push(`${count} project${count === 1 ? '' : 's'}`)
      } else {
        setProjectsFetched(false)
        failed.push(`projects (${reason(projectsResult)})`)
      }
      if (processesResult.status === 'fulfilled') {
        setProcesses(processesResult.value)
        setProcessesFetched(true)
        const count = processesResult.value.length
        found.push(`${count} process${count === 1 ? '' : 'es'}`)
      } else {
        setProcessesFetched(false)
        failed.push(`processes (${reason(processesResult)})`)
      }
      const status = [
        found.length ? `Connected. Found ${found.join(' and ')}.` : '',
        failed.length ? `Could not load existing ${failed.join('; ')}.` : '',
      ]
        .filter(Boolean)
        .join(' ')
      setApiStatusText(status)
      addLog(`API: loaded existing targets automatically — ${status}`)
    }, 600)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [connectionReady, executionMode, effectiveOrgUrl, pat, inventoryRefreshKey])

  const clearCompletionCache = () => {
    if (!cacheKey) {
      setRunOverlay({ key: null, statuses: {} })
      setRunMessage('Enter org URL and process name to clear a scoped completion cache.')
      return
    }

    persistCompletionCache((previous) => {
      const nextCache = { ...previous }
      delete nextCache[cacheKey]
      return nextCache
    })
    setRunOverlay({ key: cacheKey, statuses: {} })
    setRunMessage('Completion cache cleared for this org/process/project. Steps reset to Not run.')
  }

  const persistWorkbookApply = (applied) => {
    if (!applied?.fingerprint || !applied.processName) {
      return
    }

    const key = workbookApplyKey(effectiveOrgUrl, applied.processName)
    const next = {
      ...workbookApplies,
      [key]: {
        fingerprint: applied.fingerprint,
        templatePath: templatePath.trim(),
        workbookVersion: workbookVersion.trim(),
        appliedAt: new Date().toISOString(),
      },
    }
    localStorage.setItem(WORKBOOK_APPLIES_KEY, JSON.stringify(next))
    setWorkbookApplies(next)
  }

  const setStepStatus = (stepId, status) => {
    setRunOverlay((current) => ({
      key: cacheKey,
      statuses: {
        ...(current.key === cacheKey ? current.statuses : {}),
        [stepId]: status,
      },
    }))
  }

  const cancelWorkflow = async () => {
    const jobId = activeJobIdRef.current
    if (!jobId && runnerJobStartingRef.current) {
      // Job id not known yet; cancel on the runner as soon as it is created.
      pendingCancelRef.current = true
      setCancelRequested(true)
      setRunMessage('Cancel requested — waiting for the runner job to start...')
      return
    }
    if (!jobId) {
      abortControllerRef.current?.abort()
      return
    }
    setCancelRequested(true)
    setRunMessage('Cancel requested — the runner stops after in-flight requests finish...')
    try {
      await cancelRunnerJob(jobId)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Cancel request failed.'
      addLog(`Cancel failed (${message}); stopped watching the job instead.`)
      abortControllerRef.current?.abort()
    }
  }

  const beginRun = () => {
    isRunningRef.current = true
    const abortController = new AbortController()
    abortControllerRef.current = abortController
    setIsRunning(true)
    pendingCancelRef.current = false
    setCancelRequested(false)
    setCatalogProgress(null)
    setRunOutcome(null)
    setRunLogs([])
    setRunOverlay({ key: cacheKey, statuses: {} })
    return abortController
  }

  const endRun = () => {
    isRunningRef.current = false
    abortControllerRef.current = null
    activeJobIdRef.current = null
    runnerJobStartingRef.current = false
    pendingCancelRef.current = false
    writeSession(SESSION_ACTIVE_RUNNER_JOB, '')
    setIsRunning(false)
    setCancelRequested(false)
  }

  const rememberRunnerJob = (jobId, context) => {
    activeJobIdRef.current = jobId
    runnerJobStartingRef.current = false
    writeSession(SESSION_ACTIVE_RUNNER_JOB, JSON.stringify({ ...context, jobId }))
    if (pendingCancelRef.current) {
      pendingCancelRef.current = false
      cancelRunnerJob(jobId).catch((error) => {
        addLog(`Cancel failed: ${error instanceof Error ? error.message : error}`)
      })
    }
  }

  const dropRunningStatuses = (activeCacheKey) => {
    setRunOverlay((current) => ({
      key: activeCacheKey,
      statuses:
        current.key === activeCacheKey
          ? Object.fromEntries(
              Object.entries(current.statuses).filter(([, status]) => status !== 'running'),
            )
          : {},
    }))
  }

  const handleRunnerEvent = (event, context, signal) => {
    if (signal?.aborted) {
      return
    }
    if (event.type === 'catalog-progress') {
      setCatalogProgress(event)
      return
    }
    const stepId = event.stepId
    const message = event.message || event.type
    if (event.type === 'cancel-requested') {
      setCancelRequested(true)
    }
    if (event.type === 'step-started' && stepId) {
      setStepStatus(stepId, 'running')
    }
    if (event.type === 'step-completed' && stepId) {
      // Dry-run must not look like a live completion in the workflow cards.
      setStepStatus(stepId, context.dryRun ? 'skipped' : 'completed')
    }
    if ((event.type === 'step-skipped' || event.type === 'step-cancelled') && stepId) {
      setStepStatus(stepId, 'skipped')
    }
    if ((event.type === 'step-failed' || event.type === 'job-error') && stepId) {
      setStepStatus(stepId, 'failed')
    }
    if (event.type === 'run-summary') {
      addLog(message)
      return
    }
    addLog(stepId ? `${stepId}: ${message}` : message)
  }

  const recordCompletedSteps = (activeCacheKey, stepIds) => {
    if (!activeCacheKey || stepIds.length === 0) {
      return
    }
    persistCompletionCache((previous) => ({
      ...previous,
      [activeCacheKey]: Array.from(
        new Set([...migrateCompletedStepIds(previous[activeCacheKey] ?? []), ...stepIds]),
      ),
    }))
  }

  const finishRunnerJob = (job, context) => {
    const activeCacheKey = buildCacheKey(
      context.orgUrl,
      context.processName,
      context.projectName,
    )
    const applyOk = job.status === 'succeeded' && (job.apply_result?.ok ?? false)
    const timings = job.apply_result?.timings || []
    const totalMs = job.apply_result?.duration_ms ?? job.duration_ms ?? null
    // run-summary event already logged when present; ensure a summary if missing.
    if (!job.events?.some((event) => event.type === 'run-summary')) {
      logRunTiming(timings, totalMs, { failed: !applyOk })
    }
    const timingNote = totalMs != null ? ` Total ${formatDurationMs(totalMs)}.` : ''
    const finished = Object.keys(job.apply_result?.step_results || {})
    const outcome = job.apply_result?.outcome ?? null
    setRunOutcome(outcome)
    const resultsNote = outcome ? ' See the results below.' : ''
    if (!context.dryRun) {
      setInventoryRefreshKey((key) => key + 1)
    }

    if (applyOk) {
      // Never mark steps complete / record workbook apply for dry-run —
      // otherwise dependency-aware runs skip real work next time.
      if (!context.dryRun) {
        recordCompletedSteps(activeCacheKey, finished)
        if (finished.includes('process') && job.result?.workbook_fingerprint) {
          persistWorkbookApply({
            fingerprint: job.result.workbook_fingerprint,
            processName: context.processName,
          })
        }
      }
      setRunOverlay({ key: activeCacheKey, statuses: {} })
      setRunMessage(
        context.dryRun
          ? `Rehearsal finished — no Azure DevOps changes were made.${timingNote}${resultsNote} Uncheck “Rehearsal only” and run again for the live run.`
          : `${outcome?.headline ?? 'Run finished'}.${timingNote}${resultsNote}`,
      )
      return
    }

    dropRunningStatuses(activeCacheKey)
    if (job.status === 'cancelled') {
      if (!context.dryRun) {
        // A cancelled catalog is partial; its id-map lets the next run resume.
        recordCompletedSteps(
          activeCacheKey,
          finished.filter((stepId) => stepId !== 'catalog'),
        )
      }
      setRunMessage(
        `Runner job cancelled.${timingNote} Run again to resume — Catalog Import continues from ado-id-map.csv.`,
      )
      addLog('Run cancelled by user.')
      return
    }
    setRunMessage(`Runner job failed: ${job.error || 'unknown error'}.${timingNote}${resultsNote}`)
  }

  const setUpCatalogRerun = () => {
    setSelectedWorkflowId('catalog')
    setRunMode('step')
    setDryRun(false)
    setRunMessage(
      'Catalog Import is selected with “Selected step only”. Fix the rows listed in the results, then click Run selected flow (live) — items already imported are skipped.',
    )
  }

  const reattachRunnerJob = async (saved) => {
    if (isRunningRef.current) {
      return
    }
    const abortController = beginRun()
    activeJobIdRef.current = saved.jobId
    setRunMessage(`Reattaching to runner job ${saved.jobId} started before the page reloaded...`)
    try {
      const job = await pollRunnerJob(saved.jobId, {
        signal: abortController.signal,
        onEvent: (event) => handleRunnerEvent(event, saved, abortController.signal),
      })
      finishRunnerJob(job, saved)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unexpected runner error.'
      setRunMessage(
        message.startsWith('Job not found')
          ? 'The previous runner job is no longer available (the runner was restarted, or it has finished 20 newer jobs since and keeps only the latest 20).'
          : `Stopped watching runner job: ${message}`,
      )
    } finally {
      endRun()
    }
  }

  const loadRunnerDefaultsRef = useRef(loadRunnerDefaults)
  useEffect(() => {
    loadRunnerDefaultsRef.current = loadRunnerDefaults
  })

  useEffect(() => {
    // Mount-only: prefill paths from the runner without overwriting user input.
    // The runner may still be starting (first launch sets up Python), so keep trying.
    let cancelled = false
    let timer
    const attempt = async (triesLeft) => {
      const reached = await loadRunnerDefaultsRef.current({ onlyEmpty: true })
      if (!reached && !cancelled && triesLeft > 0) {
        timer = setTimeout(() => attempt(triesLeft - 1), 3000)
      }
    }
    timer = setTimeout(() => attempt(60), 0)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    const saved = readActiveRunnerJob()
    if (!saved) {
      return undefined
    }
    const timer = setTimeout(() => reattachRunnerJob(saved), 0)
    return () => clearTimeout(timer)
    // Mount-only: resume watching a job that outlived a page reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const openPathPicker = (target, mode) => {
    setPathPickerTarget(target)
    setPathPickerMode(mode)
    setPathPickerOpen(true)
  }

  const previewPlan = async () => {
    if (!connectionReady) {
      setPlanError('Set org URL and PAT in Connection first.')
      return
    }
    if (!nameValidation.ok) {
      setPlanError(nameValidation.messages.join(' '))
      return
    }

    setPlanLoading(true)
    setPlanError('')
    setPlanResult(null)
    setRunMessage('Building plan preview from the workbooks (no Azure DevOps changes)...')

    try {
      const response = await runnerFetch('/api/plan/dry-run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          org_url: effectiveOrgUrl,
          process_name: processName.trim(),
          project_name: projectName.trim(),
          excel_file: templatePath.trim(),
          catalog_source_dir: catalogSourceDir.trim() || null,
          workbook_version: workbookVersion.trim(),
          update_policy: updatePolicy,
          confirm_process_update: confirmProcessUpdate,
          confirm_project_update: confirmProjectUpdate,
          known_process_exists: processesFetched ? targetAssessment.process.exists : null,
          known_project_exists: projectsFetched ? targetAssessment.project.exists : null,
          root_area_path: rootAreaPath.trim() || projectName.trim(),
          include_deprecated_deleted: includeDeprecatedDeleted,
        }),
      })

      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail || `Runner error (${response.status})`)
      }

      setPlanResult(payload)
      setRunMessage(
        payload.ok
          ? `Plan ready: ${payload.actions?.length ?? 0} actions from ${payload.summary?.counts?.catalog_rows ?? 0} catalog rows.`
          : `Plan blocked: ${(payload.errors || []).join(' ')}`,
      )
      addLog(
        `Plan preview: fingerprint ${payload.workbook_fingerprint}; steps ${
          payload.steps?.map((step) => step.id).join(' → ') || 'none'
        }`,
      )
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : 'Failed to reach local runner. Quit and relaunch Start BPCTool (or npm start).'
      setPlanError(message)
      setRunMessage(`Plan preview failed: ${message}`)
    } finally {
      setPlanLoading(false)
    }
  }

  const runWorkflow = async () => {
    if (isRunningRef.current) {
      return
    }

    if (!connectionReady) {
      setRunMessage('Set org URL and PAT in Connection first.')
      return
    }

    if (!nameValidation.ok) {
      setRunMessage(`Name/policy validation failed: ${nameValidation.messages.join(' ')}`)
      return
    }

    const extensionOk = await ensureMultivalueExtensionForSetup()
    if (!extensionOk) {
      return
    }

    const abortController = beginRun()
    setRunMessage(
      executionMode === 'runner'
        ? dryRun
          ? 'Rehearsing selected flow (no Azure DevOps changes)...'
          : 'Running local runner apply against Azure DevOps...'
        : executionMode === 'api'
          ? 'Running flow (live Azure DevOps API reads)...'
          : 'Running flow (simulation)...',
    )

    const runConfig = {
      orgUrl: effectiveOrgUrl,
      pat: pat.trim(),
      templatePath: templatePath.trim(),
      catalogSourceDir: catalogSourceDir.trim(),
      workbookVersion: workbookVersion.trim(),
      projectName: projectName.trim(),
      projectDescription: projectDescription.trim(),
      processName: processName.trim(),
      threads: parseBoundedInt(threads, Number.NaN),
      maxRetries: parseBoundedInt(maxRetries, Number.NaN),
      dryRun,
      layoutSheet: layoutSheet.trim(),
      rootAreaPath: rootAreaPath.trim() || projectName.trim(),
      backlogSheet: backlogSheet.trim(),
      updatePolicy,
      confirmProcessUpdate,
      confirmProjectUpdate,
      knownProcesses: processes,
      knownProjects: projects,
      lastAppliedWorkbook,
      assessment: targetAssessment,
      executionMode,
    }

    try {
      if (executionMode === 'runner') {
        if (dryRun) {
          addLog(
            'Rehearsal only is ON — steps run and write preview files, but nothing is created or updated in Azure DevOps.',
          )
        } else {
          addLog('Live apply — runner will mutate Azure DevOps in the selected org.')
        }

        const plannedSteps = resolveTargetSteps(runMode, selectedWorkflowId, completedStepIds)
        const jobContext = {
          dryRun,
          orgUrl: runConfig.orgUrl,
          processName: runConfig.processName,
          projectName: runConfig.projectName,
        }
        runnerJobStartingRef.current = true
        const job = await runRunnerJob(
          buildRunnerJobBody({
            orgUrl: runConfig.orgUrl,
            pat: runConfig.pat,
            processName: runConfig.processName,
            projectName: runConfig.projectName,
            projectDescription: runConfig.projectDescription,
            templatePath: runConfig.templatePath,
            catalogSourceDir: runConfig.catalogSourceDir,
            workbookVersion: runConfig.workbookVersion,
            updatePolicy,
            confirmProcessUpdate,
            confirmProjectUpdate,
            knownProcessExists: processesFetched ? targetAssessment.process.exists : null,
            knownProjectExists: projectsFetched ? targetAssessment.project.exists : null,
            rootAreaPath: runConfig.rootAreaPath,
            mode: 'apply',
            applyDryRun: dryRun,
            steps: plannedSteps.length ? plannedSteps : null,
            convertMarkdownToHtml,
            includeDeprecatedDeleted,
            catalogParallelWorkers: parseBoundedInt(threads, 4),
            outputRoot: outputRootChoice,
          }),
          {
            signal: abortController.signal,
            onEvent: (event) => handleRunnerEvent(event, jobContext, abortController.signal),
            onJobCreated: (jobId) => rememberRunnerJob(jobId, jobContext),
          },
        )
        finishRunnerJob(job, jobContext)
      } else {
        const result = await runWorkflowFlow({
          mode: runMode,
          selectedWorkflowId,
          completedStepIds,
          config: runConfig,
          signal: abortController.signal,
          executeStep: stepExecutors[executionMode] ?? stepExecutors.simulate,
          onEvent: (event) => {
            if (abortController.signal.aborted) {
              return
            }

            if (event.type === 'target-assessment') {
              addLog(
                `Assessment: process ${event.assessment.process.recommendedAction}, project ${event.assessment.project.recommendedAction}. ${event.assessment.workbook.message}`,
              )
            }

            if (event.type === 'step-skipped') {
              setStepStatus(event.stepId, 'skipped')
              addLog(`Skipped ${event.stepId}: ${event.message}`)
            }

            if (event.type === 'step-started') {
              setStepStatus(event.stepId, 'running')
              addLog(`${event.stepTitle}: ${event.message}`)
            }

            if (event.type === 'step-attempt') {
              addLog(`${event.stepTitle}: ${event.message}`)
            }

            if (event.type === 'step-error') {
              addLog(
                `${event.stepTitle}: ${event.message}${
                  event.transient ? ' (transient, retrying)' : ''
                }`,
              )
            }

            if (event.type === 'step-warning') {
              addLog(`${event.stepTitle}: warning - ${event.message}`)
            }

            if (event.type === 'step-completed') {
              setStepStatus(event.stepId, 'completed')
              addLog(`${event.stepTitle}: ${event.message}`)
            }

            if (event.type === 'step-failed') {
              setStepStatus(event.stepId, 'failed')
              addLog(`${event.stepTitle}: FAILED - ${event.message}`)
            }

            if (event.type === 'run-summary') {
              addLog(event.message)
            }
          },
        })

        const nextCompleted = Array.isArray(result.completedStepIds)
          ? result.completedStepIds
          : completedStepIds

        const activeCacheKey = buildCacheKey(
          runConfig.orgUrl,
          runConfig.processName,
          runConfig.projectName,
        )
        if (activeCacheKey) {
          persistCompletionCache((previous) => ({
            ...previous,
            [activeCacheKey]: nextCompleted,
          }))
        }

        if (result.appliedWorkbook) {
          persistWorkbookApply(result.appliedWorkbook)
        }

        const timingNote =
          result.durationMs != null
            ? ` Total ${formatDurationMs(result.durationMs)}.`
            : ''

        if (result.ok) {
          setRunOverlay({ key: activeCacheKey, statuses: {} })
          setRunMessage(
            (result.message ??
              `Flow completed successfully in ${runModeLabel.toLowerCase()} mode (${executionMode}).`) +
              timingNote,
          )
        } else if (result.error?.code === 'ABORTED') {
          setRunOverlay((current) => {
            const statuses =
              current.key === activeCacheKey
                ? Object.fromEntries(
                    Object.entries(current.statuses).filter(
                      ([, status]) => status === 'failed' || status === 'completed',
                    ),
                  )
                : {}
            return { key: activeCacheKey, statuses }
          })
          setRunMessage('Flow cancelled.')
          addLog('Run cancelled by user.')
        } else {
          setRunOverlay((current) => {
            const statuses =
              current.key === activeCacheKey
                ? Object.fromEntries(
                    Object.entries(current.statuses).filter(
                      ([, status]) =>
                        status === 'failed' || status === 'skipped' || status === 'completed',
                    ),
                  )
                : {}
            return { key: activeCacheKey, statuses }
          })
          setRunMessage(`Flow failed: ${result.error.message}.${timingNote}`)
        }
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unexpected runner error.'
      setRunMessage(`Flow failed: ${message}`)
      addLog(`Runner error: ${message}`)
    } finally {
      endRun()
    }
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <h1>BPCTool</h1>
        <p>
          Sets up the Business Process Catalog in Azure DevOps from the Excel template and
          catalog workbooks.
        </p>
        <ol className="header-steps">
          <li>Connect with your org URL and PAT.</li>
          <li>Name the process and project.</li>
          <li>Pick the steps to run.</li>
          <li>
            Check with <strong>Preview plan</strong> and a <strong>Rehearsal</strong>, then run
            live.
          </li>
        </ol>
        <p className="mode-banner">
          Mode:{' '}
          <strong>
            {executionMode === 'runner'
              ? 'Runner'
              : executionMode === 'api'
                ? 'API'
                : 'Simulation'}
          </strong>
          {executionMode === 'runner'
            ? ' — runs on this computer (started with the app).'
            : executionMode === 'api'
              ? ' — only reads Azure DevOps (connection and inventory checks).'
              : ' — practice mode; nothing is sent to Azure DevOps. Switch to Runner to apply.'}
        </p>
      </header>

      <ConnectionPanel
        orgUrl={orgUrl}
        onOrgUrlChange={setOrgUrl}
        pat={pat}
        onPatChange={setPat}
        showPat={showPat}
        onToggleShowPat={() => setShowPat((value) => !value)}
        connectionReady={connectionReady}
        connectionStatusText={apiStatusText}
        fetchingProjects={fetchingProjects}
        projectsFetched={projectsFetched}
        onFetchProjects={handleFetchProjects}
        fetchingProcesses={fetchingProcesses}
        processesFetched={processesFetched}
        onFetchProcesses={handleFetchProcesses}
        executionMode={executionMode}
        onExecutionModeChange={setExecutionMode}
        extensionStatus={extensionStatus}
        extensionMessage={extensionMessage}
        extensionBusy={extensionBusy}
        onCheckExtension={refreshMultivalueExtension}
        onInstallExtension={() => handleInstallMultivalueExtension({ prompted: false })}
        disabled={isRunning}
      />

      <CollapsibleSection
        title="2. Process & project names"
        defaultOpen
        summary={
          [
            processName.trim() || 'No process name',
            projectName.trim() || 'No project name',
            projectDescription.trim()
              ? `Description (${projectDescription.trim().length} chars)`
              : 'No description',
            updatePolicy,
          ].join(' · ')
        }
      >
        <p className="section-lead">
          Type the names to create. Existing projects and processes load from the connection
          to detect collisions; suggestions appear as you type.
        </p>
        <div className="grid-2">
          <label>
            Process name to create
            <input
              list="process-name-suggestions"
              value={processName}
              onChange={(event) => setProcessName(event.target.value)}
              placeholder="e.g. Business Process Catalog"
              disabled={isRunning}
            />
            <datalist id="process-name-suggestions">
              {processes.map((process) => (
                <option key={process.id} value={process.name} />
              ))}
            </datalist>
            {nameValidation.errors.processName.map((message) => (
              <small key={message} className="field-error">
                {message}
              </small>
            ))}
            {processName.trim() && nameValidation.errors.processName.length === 0 ? (
              <small className="field-hint">
                {targetAssessment.process.exists
                  ? `Matches existing process → ${targetAssessment.process.recommendedAction}`
                  : 'New process → will be created'}
              </small>
            ) : null}
          </label>

          <label>
            Project name to create
            <input
              list="project-name-suggestions"
              value={projectName}
              onChange={(event) => setProjectName(event.target.value)}
              placeholder="e.g. Contoso-BPC"
              disabled={isRunning}
            />
            <datalist id="project-name-suggestions">
              {projects.map((project) => (
                <option key={project.id} value={project.name} />
              ))}
            </datalist>
            {nameValidation.errors.projectName.map((message) => (
              <small key={message} className="field-error">
                {message}
              </small>
            ))}
            {projectName.trim() && nameValidation.errors.projectName.length === 0 ? (
              <small className="field-hint">
                {targetAssessment.project.exists
                  ? `Matches existing project → ${targetAssessment.project.recommendedAction}`
                  : 'New project → created after process + layout'}
              </small>
            ) : null}
          </label>

        </div>

        <label className="stack-field project-description-field">
          Project description
          <textarea
            value={projectDescription}
            onChange={(event) => setProjectDescription(event.target.value)}
            placeholder="Optional description shown on the Azure DevOps project overview"
            rows={3}
            disabled={isRunning}
          />
          <small className="field-hint">
            Applied on project create. If the project already exists, re-running Project
            Creation updates the description when this field is non-empty.
          </small>
        </label>

        <div className="assessment-grid name-policy-block">
          <label>
            Existing target policy
            <select
              value={updatePolicy}
              onChange={(event) => setUpdatePolicy(event.target.value)}
              disabled={isRunning}
            >
              <option value="require-confirmation">Require confirmation before update</option>
              <option value="always-update">Always update existing targets</option>
              <option value="skip-existing">Skip steps for existing targets</option>
              <option value="create-only">Create only (fail if exists)</option>
            </select>
          </label>
          {updatePolicy === 'require-confirmation' && targetAssessment.process.exists ? (
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={confirmProcessUpdate}
                onChange={(event) => setConfirmProcessUpdate(event.target.checked)}
                disabled={isRunning}
              />
              Confirm updating existing process / applying spreadsheet changes
            </label>
          ) : null}
          {updatePolicy === 'require-confirmation' && targetAssessment.project.exists ? (
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={confirmProjectUpdate}
                onChange={(event) => setConfirmProjectUpdate(event.target.checked)}
                disabled={isRunning}
              />
              Confirm updating / reusing existing project
            </label>
          ) : null}
          {nameValidation.errors.policy.map((message) => (
            <small key={message} className="field-error">
              {message}
            </small>
          ))}
          <p className="field-hint">{targetAssessment.workbook.message}</p>
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title="3. Workflow selection"
        defaultOpen
        summary={`${runModeLabel} · ${runPlanLabel}`}
      >
        <div className="run-mode">
          <label className="radio-row">
            <input
              type="radio"
              checked={runMode === 'step'}
              onChange={() => setRunMode('step')}
              disabled={isRunning}
            />
            Selected step only (re-run; no prerequisites)
          </label>
          <label className="radio-row">
            <input
              type="radio"
              checked={runMode === 'single'}
              onChange={() => setRunMode('single')}
              disabled={isRunning}
            />
            Dependency-aware run to selected step
          </label>
          <label className="radio-row">
            <input
              type="radio"
              checked={runMode === 'from'}
              onChange={() => setRunMode('from')}
              disabled={isRunning}
            />
            Run from selected step onward (re-runs completed steps)
          </label>
          <label className="radio-row">
            <input
              type="radio"
              checked={runMode === 'full'}
              onChange={() => setRunMode('full')}
              disabled={isRunning}
            />
            Full flow run (skip already completed)
          </label>
        </div>
        <p className="run-plan" role="status">
          {runPlanLabel}
        </p>
        <div className="workflow-list">
          {workflowDefinitions.map((workflow) => {
            const isPlanned = plannedStepIds.includes(workflow.id)
            const isCachedSkip =
              completedStepIds.includes(workflow.id) &&
              (runMode === 'full' ||
                (runMode === 'single' &&
                  workflowDefinitions.findIndex((item) => item.id === workflow.id) <=
                    workflowDefinitions.findIndex(
                      (item) => item.id === selectedWorkflowId,
                    )))
            const cardActive =
              runMode === 'full' ? isPlanned || isCachedSkip : selectedWorkflowId === workflow.id

            return (
              <button
                key={workflow.id}
                type="button"
                className={`workflow-card ${cardActive ? 'active' : ''} ${
                  (runMode === 'full' || runMode === 'step' || runMode === 'from') && isPlanned
                    ? 'planned'
                    : ''
                }`}
                onClick={() => {
                  if (runMode === 'full') {
                    return
                  }
                  setSelectedWorkflowId(workflow.id)
                }}
                disabled={isRunning || runMode === 'full'}
                aria-disabled={runMode === 'full'}
              >
                <strong>
                  {workflow.title}
                  <span className={`status-chip ${stepStatuses[workflow.id] ?? 'idle'}`}>
                    {statusLabelMap[stepStatuses[workflow.id] ?? 'idle']}
                  </span>
                </strong>
                <span>{workflow.script}</span>
                <small>{workflow.description}</small>
                {runMode === 'step' && isPlanned ? (
                  <small className="plan-hint">Will re-run alone</small>
                ) : null}
                {runMode === 'full' && isCachedSkip && !isPlanned ? (
                  <small className="plan-hint">Cached — will skip</small>
                ) : null}
                {runMode === 'full' && isPlanned ? (
                  <small className="plan-hint">In this run</small>
                ) : null}
                {runMode === 'from' && isPlanned ? (
                  <small className="plan-hint">
                    {workflow.id === selectedWorkflowId ? 'Starts here' : 'In this run'}
                  </small>
                ) : null}
              </button>
            )
          })}
        </div>
      </CollapsibleSection>

      <section className="panel">
        <h2>4. Run configuration</h2>
        <div className="grid-run-config">
          <label className="span-12">
            Template workbook path
            <div className="path-picker-row">
              <input
                value={templatePath}
                onChange={(event) => {
                  setTemplatePath(event.target.value)
                  setConfirmProcessUpdate(false)
                }}
                disabled={isRunning}
              />
              <button
                type="button"
                className="secondary-inline"
                onClick={() => openPathPicker('template', 'file')}
                disabled={isRunning}
              >
                Browse…
              </button>
            </div>
            <small className="field-hint">
              Absolute path to the current release&apos;s ADO template guideline <code>.xlsx</code>{' '}
              (not bundled). Keep it in the same release folder as the catalog workbooks so Load
              runner defaults finds it.
            </small>
          </label>
          <label className="span-12">
            Catalog source folder
            <div className="path-picker-row">
              <input
                value={catalogSourceDir}
                onChange={(event) => setCatalogSourceDir(event.target.value)}
                placeholder="/Users/you/BPC Files/2026-Q4"
                disabled={isRunning}
              />
              <button
                type="button"
                className="secondary-inline"
                onClick={() => openPathPicker('catalog', 'folder')}
                disabled={isRunning}
              >
                Browse…
              </button>
            </div>
            <small className="field-hint">
              One release folder, e.g. <code>~/BPC Files/2026-Q4</code>, holding that
              quarter&apos;s template and catalog workbooks. Every catalog workbook in it is
              imported, so do not mix releases.
            </small>
          </label>
          <label className="span-12">
            Run output folder
            <div className="path-picker-row">
              <input
                value={outputRootChoice}
                onChange={(event) => setOutputRootChoice(event.target.value)}
                placeholder={outputRoot || 'Runner default (bpctool/runner-out)'}
                disabled={isRunning}
              />
              <button
                type="button"
                className="secondary-inline"
                onClick={() => openPathPicker('output', 'folder')}
                disabled={isRunning}
              >
                Browse…
              </button>
              {outputRootChoice ? (
                <button
                  type="button"
                  className="secondary-inline"
                  onClick={() => setOutputRootChoice('')}
                  disabled={isRunning}
                >
                  Use default
                </button>
              ) : null}
            </div>
            <small className="field-hint">
              Each run writes to{' '}
              <code>
                {(outputRootChoice.trim() || outputRoot || 'runner-out').replace(/[/\\]+$/, '')}/
                {outputFolderName}/
              </code>{' '}
              (<code>{outputFolderName}-&lt;code&gt;</code> if another project&apos;s results already use that
              name). Keep this folder between runs and releases — <code>ado-id-map.csv</code> there is
              what prevents duplicate catalog work items. If you change folders, move the existing{' '}
              <code>&lt;org&gt;_&lt;project&gt;</code> folder too.
            </small>
          </label>
          <label className="span-4">
            Workbook version / revision label
            <input
              value={workbookVersion}
              onChange={(event) => {
                setWorkbookVersion(event.target.value)
                setConfirmProcessUpdate(false)
              }}
              placeholder="Quarterly release label, e.g. 2026-Q3"
              disabled={isRunning}
            />
          </label>
          <label className="span-2">
            {executionMode === 'runner' ? 'Catalog workers' : 'Threads'}
            <input
              type="number"
              min="1"
              max="16"
              value={Number.isNaN(threads) ? '' : threads}
              onChange={(event) =>
                setThreads(parseBoundedInt(event.target.value, Number.NaN))
              }
              disabled={isRunning}
            />
            <span className="field-hint">
              {executionMode === 'runner'
                ? 'Parallel creates and parent-link checks for Catalog Import. Start with 2–8; 1 = serial.'
                : 'Parallelism for Simulate/API layout stubs.'}
            </span>
          </label>
          {executionMode !== 'runner' ? (
            <>
              <label className="span-2">
                Retry count
                <input
                  type="number"
                  min="0"
                  max="5"
                  value={Number.isNaN(maxRetries) ? '' : maxRetries}
                  onChange={(event) =>
                    setMaxRetries(parseBoundedInt(event.target.value, Number.NaN))
                  }
                  disabled={isRunning}
                />
              </label>
              <label className="span-4">
                Layout worksheet name
                <input
                  value={layoutSheet}
                  onChange={(event) => setLayoutSheet(event.target.value)}
                  disabled={isRunning}
                />
              </label>
            </>
          ) : null}
          <label className="span-8">
            Root area path
            <input
              value={rootAreaPath}
              onChange={(event) => setRootAreaPathValue(event.target.value)}
              placeholder={derivedRootAreaPath(projectName) || 'Project name'}
              disabled={isRunning}
            />
            <small className="field-hint">
              Defaults to the project root (
              <code>{derivedRootAreaPath(projectName) || 'project name'}</code>
              ) from section 2. Area path children come from the Excel Area paths
              sheet. Edit only to nest them below the project (e.g. Project\BPC); catalog
              Area Paths move under it too.
            </small>
          </label>
          {executionMode !== 'runner' ? (
            <label className="span-4">
              Backlog worksheet name
              <input
                value={backlogSheet}
                onChange={(event) => setBacklogSheet(event.target.value)}
                disabled={isRunning}
              />
            </label>
          ) : null}
          <div
            className={`stack-field span-6 ${executionMode === 'runner' && dryRun ? 'dry-run-warning' : ''}`}
          >
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={dryRun}
                onChange={(event) => setDryRun(event.target.checked)}
                disabled={isRunning}
              />
              {executionMode === 'runner'
                ? 'Rehearsal only — run steps without changing Azure DevOps'
                : 'Rehearsal only — backlog configuration'}
            </label>
            {executionMode === 'runner' ? (
              <small className="field-hint">
                {dryRun
                  ? 'On: Rehearse selected flow runs every selected step and writes preview files (rehearsal-summary.html, import-prevalidate.csv, import-preview.csv) without changing Azure DevOps. Catalog Import only reads: if the project exists, it reports what differs from the workbook (import-changes.csv). Steps show Skipped.'
                  : 'Off: Run selected flow (live) creates/updates the process, layouts, project, teams, backlog, and catalog in the connected org.'}
              </small>
            ) : null}
          </div>
          <div className="stack-field span-6">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={convertMarkdownToHtml}
                onChange={(event) => setConvertMarkdownToHtml(event.target.checked)}
                disabled={isRunning}
              />
              Convert Markdown large-text fields to HTML
            </label>
            <small className="field-hint">
              Default preserves markdown and sets
              multilineFieldsFormat=Markdown. Enable only to store HTML instead.
            </small>
          </div>
          <div className="stack-field span-6">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={includeDeprecatedDeleted}
                onChange={(event) => setIncludeDeprecatedDeleted(event.target.checked)}
                disabled={isRunning}
              />
              Import Deprecated / Deleted rows
            </label>
            <small className="field-hint">
              Off: Catalog Import skips rows whose Catalog status is Deprecated or Deleted, and the
              rows below them (listed in skipped-deprecated-deleted.csv).
            </small>
          </div>
          <div className="input-list span-12">
            <p>Workflow-specific inputs</p>
            <ul>
              {(selectedWorkflow?.inputs ?? []).map((inputName) => (
                <li key={inputName}>{inputName}</li>
              ))}
            </ul>
          </div>
        </div>

        <div className="run-actions">
          <button
            type="button"
            className="run-button secondary"
            onClick={() => loadRunnerDefaults()}
            disabled={isRunning || planLoading}
          >
            Load runner defaults
          </button>

          <button
            type="button"
            className="run-button"
            onClick={previewPlan}
            disabled={planLoading || isRunning || !connectionReady || !nameValidation.ok}
          >
            {planLoading ? 'Building plan...' : 'Preview plan'}
          </button>

          <button
            type="button"
            className={`run-button ${executionMode === 'runner' && !dryRun ? 'live' : ''}`}
            onClick={runWorkflow}
            disabled={
              isRunning ||
              !connectionReady ||
              !nameValidation.ok
            }
          >
            {isRunning ? 'Running...' : runButtonLabel}
          </button>

          <button
            type="button"
            className="run-button secondary"
            onClick={cancelWorkflow}
            disabled={!isRunning || cancelRequested}
          >
            {cancelRequested ? 'Cancelling...' : 'Cancel run'}
          </button>

          <button
            type="button"
            className="run-button secondary"
            onClick={clearCompletionCache}
            disabled={isRunning}
          >
            Clear completion cache
          </button>
        </div>

        {executionMode === 'runner' ? (
          <p className={`run-mode-note ${dryRun ? 'rehearsal' : 'live'}`}>
            {dryRun
              ? 'Rehearsal: Azure DevOps will not be changed. Uncheck “Rehearsal only” for the live run.'
              : `Live run: changes Azure DevOps${liveTargetLabel}. Preview plan never changes anything; tick “Rehearsal only” to test the steps first.`}
          </p>
        ) : null}

        {planError ? <p className="field-error">{planError}</p> : null}

        {planResult ? (
          <div className="plan-preview">
            <h3>Plan preview</h3>
            <p className="field-hint">
              IR {planResult.ir_version} · fingerprint {planResult.workbook_fingerprint}
            </p>
            <p className="field-hint">
              Counts: {planResult.summary?.counts?.work_item_types ?? 0} WITs,{' '}
              {planResult.summary?.counts?.fields ?? 0} fields,{' '}
              {planResult.summary?.counts?.teams ?? 0} teams,{' '}
              {planResult.summary?.counts?.area_paths ?? 0} areas,{' '}
              {planResult.summary?.counts?.catalog_rows ?? 0} catalog rows
            </p>
            {(planResult.notices || []).map((notice) => (
              <p key={notice} className="run-notice">
                {notice}
              </p>
            ))}
            <ol className="plan-step-list">
              {(planResult.steps || []).map((step) => (
                <li key={step.id}>
                  <strong>
                    {step.title} ({step.planned_action})
                  </strong>
                  <span> — {step.summary}</span>
                </li>
              ))}
            </ol>
            {(planResult.warnings || []).length > 0 ? (
              <ul className="plan-warnings">
                {planResult.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
            {(planResult.errors || []).length > 0 ? (
              <ul className="plan-errors">
                {planResult.errors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            ) : null}
            <DataChecks checks={planResult.data_checks} />
          </div>
        ) : null}

        <RunResultsCard
          outcome={runOutcome}
          onRerunCatalog={setUpCatalogRerun}
          onDismiss={() => setRunOutcome(null)}
        />

        <div className="run-log" role="status" aria-live="polite">
          <p>{runMessage}</p>
          {catalogProgressSummary ? (
            <div className="catalog-progress">
              <div className="catalog-progress-label">
                <strong>{catalogProgressSummary.label}</strong>
                <span>{catalogProgressSummary.detail}</span>
              </div>
              <progress
                max={catalogProgressSummary.total}
                value={catalogProgressSummary.done}
                aria-label={`${catalogProgressSummary.label} progress`}
              />
            </div>
          ) : null}
          <pre>{runLogs.length > 0 ? runLogs.join('\n') : 'No execution logs yet.'}</pre>
        </div>
      </section>

      {pathPickerOpen ? (
        <PathPickerModal
          key={`${pathPickerTarget}:${pathPickerMode}:${pathPickerInitial}`}
          title={
            pathPickerTarget === 'catalog'
              ? 'Select catalog source folder'
              : pathPickerTarget === 'output'
                ? 'Select run output folder'
                : 'Select template workbook (.xlsx)'
          }
          mode={pathPickerMode}
          initialValue={pathPickerInitial}
          onClose={() => setPathPickerOpen(false)}
          onConfirm={(nextPath) => {
            if (pathPickerTarget === 'catalog') {
              setCatalogSourceDir(nextPath)
            } else if (pathPickerTarget === 'output') {
              setOutputRootChoice(nextPath)
            } else {
              setTemplatePath(nextPath)
              setConfirmProcessUpdate(false)
            }
            setPathPickerOpen(false)
          }}
        />
      ) : null}
    </main>
  )
}

export default App
