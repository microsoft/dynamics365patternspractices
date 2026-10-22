import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  authHeader,
  buildAdoApiBase,
  buildExtmgmtApiBase,
  fetchProjects,
  getMultivalueExtensionStatus,
  installMultivalueExtension,
  maskSecret,
  stepsRequireMultivalueExtension,
} from './adoApi'

describe('adoApi helpers', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('builds Basic auth with empty username', () => {
    expect(authHeader('secret-token')).toBe(`Basic ${btoa(':secret-token')}`)
  })

  it('masks secrets', () => {
    expect(maskSecret('abcdefghij')).toBe('abcd***ij')
  })

  it('builds proxy API base from org URL', () => {
    expect(buildAdoApiBase('https://contoso.visualstudio.com')).toBe('/ado-proxy/contoso')
    expect(buildAdoApiBase('contoso')).toBe('/ado-proxy/contoso')
  })

  it('builds extmgmt proxy base from org URL', () => {
    expect(buildExtmgmtApiBase('https://dev.azure.com/contoso')).toBe(
      '/extmgmt-proxy/contoso',
    )
  })

  it('flags process/layout/project as requiring Multivalue extension', () => {
    expect(stepsRequireMultivalueExtension(['catalog'])).toBe(false)
    expect(stepsRequireMultivalueExtension(['process', 'catalog'])).toBe(true)
    expect(stepsRequireMultivalueExtension(['layout'])).toBe(true)
  })

  it('fetchProjects maps ADO payload', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: {
          get: (name) => (name === 'content-type' ? 'application/json' : null),
        },
        json: async () => ({
          value: [
            { id: '1', name: 'Alpha' },
            { id: '2', name: 'Beta' },
          ],
        }),
      })),
    )

    const projects = await fetchProjects('https://dev.azure.com/contoso', '01234567890123456789')
    expect(projects).toEqual([
      { id: '1', name: 'Alpha', state: undefined },
      { id: '2', name: 'Beta', state: undefined },
    ])
    expect(fetch).toHaveBeenCalledWith(
      '/ado-proxy/contoso/_apis/projects?api-version=7.1',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({
          Authorization: authHeader('01234567890123456789'),
        }),
      }),
    )
  })

  it('getMultivalueExtensionStatus maps 404 to missing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        headers: { get: () => null },
        text: async () => '',
      })),
    )
    const result = await getMultivalueExtensionStatus(
      'https://dev.azure.com/contoso',
      '01234567890123456789',
    )
    expect(result).toEqual({ status: 'missing' })
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/extmgmt-proxy/contoso/_apis/extensionmanagement/'),
      expect.objectContaining({ method: 'GET' }),
    )
  })

  it('getMultivalueExtensionStatus maps disabled flag', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: {
          get: (name) => (name === 'content-type' ? 'application/json' : null),
        },
        json: async () => ({
          extensionId: 'vsts-extensions-multivalue-control',
          installState: { flags: 'disabled' },
        }),
      })),
    )
    const result = await getMultivalueExtensionStatus(
      'https://dev.azure.com/contoso',
      '01234567890123456789',
    )
    expect(result.status).toBe('disabled')
  })

  it('getMultivalueExtensionStatus rejects a 203 sign-in page (bad PAT)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 203,
        statusText: 'Non-Authoritative Information',
        headers: {
          get: (name) => (name === 'content-type' ? 'text/html; charset=utf-8' : null),
        },
        text: async () => '<html>Sign in</html>',
      })),
    )
    await expect(
      getMultivalueExtensionStatus('https://dev.azure.com/contoso', '01234567890123456789'),
    ).rejects.toThrow(/ADO 401/)
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('installMultivalueExtension POSTs to extmgmt', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: {
          get: (name) => (name === 'content-type' ? 'application/json' : null),
        },
        json: async () => ({ extensionId: 'vsts-extensions-multivalue-control' }),
      })),
    )
    await installMultivalueExtension(
      'https://dev.azure.com/contoso',
      '01234567890123456789',
    )
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining(
        'installedextensionsbyname/ms-devlabs/vsts-extensions-multivalue-control',
      ),
      expect.objectContaining({ method: 'POST' }),
    )
  })
})
