/**
 * Azure DevOps REST helpers (PAT Basic auth + retry).
 * Browser calls go through the Vite `/ado-proxy` path to avoid CORS.
 */

import { parseAdoOrgUrl } from './adoOrgUrl'

const DEFAULT_RETRY_ATTEMPTS = 5
const DEFAULT_RETRY_BASE_MS = 1000

export function authHeader(pat) {
  return `Basic ${btoa(`:${pat}`)}`
}

export function maskSecret(value) {
  if (!value || value.length < 8) {
    return '***'
  }
  return `${value.slice(0, 4)}***${value.slice(-2)}`
}

/**
 * API base for browser calls. Always uses local proxy + org segment so
 * Authorization can reach dev.azure.com without CORS.
 */
export function buildAdoApiBase(orgUrl) {
  const parsed = parseAdoOrgUrl(orgUrl)
  if (!parsed.ok) {
    throw new Error(parsed.error)
  }

  return `/ado-proxy/${encodeURIComponent(parsed.org)}`
}

/** Extension Management host (installedextensions* APIs). */
export function buildExtmgmtApiBase(orgUrl) {
  const parsed = parseAdoOrgUrl(orgUrl)
  if (!parsed.ok) {
    throw new Error(parsed.error)
  }

  return `/extmgmt-proxy/${encodeURIComponent(parsed.org)}`
}

/** Microsoft DevLabs Multivalue control — required for Multi-select layout. */
export const DEVLABS_MULTIVALUE = {
  publisherName: 'ms-devlabs',
  extensionName: 'vsts-extensions-multivalue-control',
  itemName: 'ms-devlabs.vsts-extensions-multivalue-control',
  displayName: 'Multivalue control (Microsoft DevLabs)',
  marketplaceUrl:
    'https://marketplace.visualstudio.com/items?itemName=ms-devlabs.vsts-extensions-multivalue-control',
}

export function stepsRequireMultivalueExtension(stepIds = []) {
  const need = new Set(['process', 'layout', 'project'])
  return stepIds.some((id) => need.has(id))
}

const sleep = (ms, signal) =>
  new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new Error('Request cancelled'))
      return
    }

    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)

    const onAbort = () => {
      clearTimeout(timer)
      reject(new Error('Request cancelled'))
    }

    signal?.addEventListener('abort', onAbort, { once: true })
  })

const jitter = (ms) => Math.floor(ms * (0.5 + Math.random() * 0.5))

async function parseErrorMessage(response) {
  const text = await response.text()
  let detail = ''
  if (text) {
    try {
      const json = JSON.parse(text)
      detail = json.message || json.typeKey || text.slice(0, 200)
    } catch {
      detail = text.slice(0, 200)
    }
  }
  return `ADO ${response.status} ${response.statusText}${detail ? `: ${detail}` : ''}`
}

/**
 * fetch with Basic PAT auth and 429/503 Retry-After backoff.
 * @param {string} apiBase - `/ado-proxy/{org}` or `/extmgmt-proxy/{org}`
 */
async function adoServiceFetch(
  apiBase,
  path,
  {
    pat,
    method = 'GET',
    body,
    apiVersion = '7.1',
    signal,
    retryAttempts = DEFAULT_RETRY_ATTEMPTS,
  } = {},
) {
  if (!pat?.trim()) {
    throw new Error('PAT is required for Azure DevOps API calls.')
  }

  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const separator = normalizedPath.includes('?') ? '&' : '?'
  const url = `${apiBase}${normalizedPath}${separator}api-version=${apiVersion}`

  let lastError = null

  for (let attempt = 0; attempt < retryAttempts; attempt += 1) {
    if (signal?.aborted) {
      throw new Error('Request cancelled')
    }

    try {
      const response = await fetch(url, {
        method,
        signal,
        headers: {
          Authorization: authHeader(pat.trim()),
          Accept: 'application/json',
          ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      })

      if (response.status === 429 || response.status === 503) {
        const retryAfter = response.headers.get('Retry-After')
        const waitMs = retryAfter
          ? Number.parseInt(retryAfter, 10) * 1000
          : jitter(DEFAULT_RETRY_BASE_MS * 2 ** attempt)
        lastError = new Error(await parseErrorMessage(response))

        if (attempt < retryAttempts - 1) {
          await sleep(Number.isFinite(waitMs) ? waitMs : DEFAULT_RETRY_BASE_MS, signal)
          continue
        }

        throw lastError
      }

      if (!response.ok) {
        throw new Error(await parseErrorMessage(response))
      }

      const contentType = response.headers.get('content-type') || ''
      // ADO answers an invalid/expired PAT with 203 + an HTML sign-in page.
      if (response.status === 203 || contentType.includes('text/html')) {
        throw new Error(
          'ADO 401 Azure DevOps returned a sign-in page — the PAT is invalid, expired, or lacks the required scopes.',
        )
      }
      if (contentType.includes('application/json')) {
        return response.json()
      }

      return undefined
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error))

      if (lastError.message === 'Request cancelled' || signal?.aborted) {
        throw lastError
      }

      // Do not retry definitive client/auth failures.
      if (/^ADO (401|403|404)\b/.test(lastError.message)) {
        throw lastError
      }

      if (attempt < retryAttempts - 1 && !/^ADO \d+/.test(lastError.message)) {
        await sleep(jitter(DEFAULT_RETRY_BASE_MS * 2 ** attempt), signal)
        continue
      }

      throw lastError
    }
  }

  throw lastError || new Error('Azure DevOps request failed')
}

export async function adoFetch(orgUrl, path, options = {}) {
  return adoServiceFetch(buildAdoApiBase(orgUrl), path, options)
}

export async function extmgmtFetch(orgUrl, path, options = {}) {
  return adoServiceFetch(buildExtmgmtApiBase(orgUrl), path, options)
}

/**
 * @returns {Promise<{ status: 'installed'|'missing'|'disabled', extension?: object }>}
 */
export async function getMultivalueExtensionStatus(orgUrl, pat, { signal } = {}) {
  const path =
    `/_apis/extensionmanagement/installedextensionsbyname/` +
    `${encodeURIComponent(DEVLABS_MULTIVALUE.publisherName)}/` +
    `${encodeURIComponent(DEVLABS_MULTIVALUE.extensionName)}`
  try {
    const data = await extmgmtFetch(orgUrl, path, {
      pat,
      signal,
      apiVersion: '7.1-preview.1',
    })
    if (!data || typeof data !== 'object' || !data.extensionId) {
      throw new Error('Unexpected Multivalue extension response from Azure DevOps.')
    }
    const flags = String(data.installState?.flags ?? 'none').toLowerCase()
    if (flags.includes('disabled')) {
      return { status: 'disabled', extension: data }
    }
    return { status: 'installed', extension: data }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (/^ADO 404\b/.test(message)) {
      return { status: 'missing' }
    }
    throw error
  }
}

export async function installMultivalueExtension(orgUrl, pat, { signal } = {}) {
  const path =
    `/_apis/extensionmanagement/installedextensionsbyname/` +
    `${encodeURIComponent(DEVLABS_MULTIVALUE.publisherName)}/` +
    `${encodeURIComponent(DEVLABS_MULTIVALUE.extensionName)}`
  return extmgmtFetch(orgUrl, path, {
    pat,
    method: 'POST',
    signal,
    apiVersion: '7.1-preview.1',
  })
}

export async function fetchProjects(orgUrl, pat, { signal, apiVersion = '7.1' } = {}) {
  const data = await adoFetch(orgUrl, '/_apis/projects', { pat, signal, apiVersion })
  return (data?.value || []).map((project) => ({
    id: String(project.id || project.name),
    name: String(project.name),
    state: project.state,
  }))
}

export async function fetchProcesses(
  orgUrl,
  pat,
  { signal, inheritedOnly = false, apiVersion = '7.2-preview.1' } = {},
) {
  const path = inheritedOnly
    ? '/_apis/process/processes?type=inherited'
    : '/_apis/process/processes'
  const data = await adoFetch(orgUrl, path, { pat, signal, apiVersion })
  const processes = (data?.value || []).map((process) => ({
    id: String(process.typeId || process.id || process.name),
    name: String(process.name),
    type: process.type,
  }))

  if (inheritedOnly) {
    return processes.filter((process) => process.type === 'inherited' || !process.type)
  }

  return processes
}

export async function fetchProjectTeams(
  orgUrl,
  pat,
  projectName,
  { signal, apiVersion = '7.1' } = {},
) {
  const encodedProject = encodeURIComponent(projectName)
  const data = await adoFetch(orgUrl, `/_apis/projects/${encodedProject}/teams`, {
    pat,
    signal,
    apiVersion,
  })
  return (data?.value || []).map((team) => ({
    id: String(team.id || team.name),
    name: String(team.name),
  }))
}

export async function fetchWorkItemTypes(
  orgUrl,
  pat,
  projectName,
  { signal, apiVersion = '7.1' } = {},
) {
  const encodedProject = encodeURIComponent(projectName)
  const data = await adoFetch(orgUrl, `/${encodedProject}/_apis/wit/workitemtypes`, {
    pat,
    signal,
    apiVersion,
  })
  return (data?.value || []).map((wit) => ({
    name: String(wit.name),
    referenceName: wit.referenceName,
  }))
}

export async function fetchProcessWorkItemTypes(
  orgUrl,
  pat,
  processTypeId,
  { signal, apiVersion = '7.2-preview.1' } = {},
) {
  const encodedProcess = encodeURIComponent(processTypeId)
  const data = await adoFetch(
    orgUrl,
    `/_apis/work/processes/${encodedProcess}/workitemtypes`,
    { pat, signal, apiVersion },
  )
  return (data?.value || []).map((wit) => ({
    name: String(wit.name),
    referenceName: wit.referenceName || wit.id,
  }))
}

/**
 * API-mode step body: live ADO reads that prove wiring (not full Python parity).
 */
export async function executeApiStep(step, config, { signal } = {}) {
  switch (step.id) {
    case 'process': {
      const processes = await fetchProcesses(config.orgUrl, config.pat, {
        signal,
        inheritedOnly: false,
      })
      const processMatch = processes.find(
        (process) => process.name.toLowerCase() === config.processName.trim().toLowerCase(),
      )
      const warnings = []
      const workbookChanged = Boolean(config.assessment?.workbook?.changed)

      if (processMatch) {
        warnings.push(
          workbookChanged
            ? `Existing process "${config.processName}" will be updated from the spreadsheet revision.`
            : `Existing process "${config.processName}" found — update verified before changes.`,
        )
      } else {
        warnings.push(`Process "${config.processName}" not found — API path would create it from the workbook.`)
      }

      return {
        details: `API process check: ${processes.length} processes in org. Target ${processMatch ? 'exists (update path)' : 'is new (create path)'}.${workbookChanged ? ' Workbook delta applicable.' : ''}`,
        warnings,
        workbookApplied: {
          fingerprint: config.assessment?.workbook?.fingerprint,
          processName: config.processName,
        },
      }
    }

    case 'layout': {
      const processes = await fetchProcesses(config.orgUrl, config.pat, {
        signal,
        inheritedOnly: false,
      })
      const processMatch = processes.find(
        (process) => process.name.toLowerCase() === config.processName.trim().toLowerCase(),
      )

      if (!processMatch) {
        return {
          details: `API layout check: process "${config.processName}" not in org yet — layouts apply after process create.`,
          warnings: ['Process must exist before page layouts can be verified via API.'],
        }
      }

      const types = await fetchProcessWorkItemTypes(config.orgUrl, config.pat, processMatch.id, {
        signal,
      })
      return {
        details: `API layout check: process "${config.processName}" exposes ${types.length} work item types for layout work (pre-project).`,
        warnings:
          types.length === 0
            ? ['No process work item types returned — confirm process customization permissions.']
            : [],
      }
    }

    case 'project': {
      const projects = await fetchProjects(config.orgUrl, config.pat, { signal })
      const exists = projects.some(
        (project) => project.name.toLowerCase() === config.projectName.trim().toLowerCase(),
      )
      const warnings = []
      if (exists) {
        warnings.push(
          `Existing project "${config.projectName}" selected — update/reuse verified before project-phase changes.`,
        )
      }

      return {
        details: `API project check: ${projects.length} projects in org. Target project ${exists ? 'exists' : 'is new'}. Process "${config.processName}" must already be layout-complete.`,
        warnings,
      }
    }

    case 'teams': {
      const teams = await fetchProjectTeams(config.orgUrl, config.pat, config.projectName, {
        signal,
      })
      return {
        details: `API check: project "${config.projectName}" has ${teams.length} team${teams.length === 1 ? '' : 's'}. Root area path target: ${config.rootAreaPath}.`,
        warnings: teams.length === 0 ? ['No teams found for this project.'] : [],
      }
    }

    case 'backlog': {
      const teams = await fetchProjectTeams(config.orgUrl, config.pat, config.projectName, {
        signal,
      })
      const warnings = []
      if (config.dryRun) {
        warnings.push(
          'Dry-run enabled — API mode only inspected teams; backlog writes are not applied.',
        )
      }
      if (teams.length === 0) {
        warnings.push('No teams available to inspect backlog configuration against.')
      }

      return {
        details: `API check: backlog step can target ${teams.length} team${teams.length === 1 ? '' : 's'} using sheet "${config.backlogSheet}".`,
        warnings,
      }
    }

    default:
      throw new Error(`No API executor mapping for step ${step.id}`)
  }
}
