import { describe, expect, it } from 'vitest'
import { buildAdoApiBase } from './adoApi'
import { normalizeAdoOrgUrl, parseAdoOrgUrl } from './adoOrgUrl'

describe('parseAdoOrgUrl', () => {
  it('parses dev.azure.com URLs', () => {
    expect(parseAdoOrgUrl('https://dev.azure.com/contoso')).toEqual({
      ok: true,
      org: 'contoso',
      canonicalUrl: 'https://dev.azure.com/contoso',
      apiHostname: 'dev.azure.com',
    })
    expect(parseAdoOrgUrl('https://dev.azure.com/contoso/project').org).toBe('contoso')
    expect(parseAdoOrgUrl('dev.azure.com/contoso').canonicalUrl).toBe(
      'https://dev.azure.com/contoso',
    )
  })

  it('parses visualstudio.com and bare org names', () => {
    expect(parseAdoOrgUrl('https://contoso.visualstudio.com')).toEqual({
      ok: true,
      org: 'contoso',
      canonicalUrl: 'https://dev.azure.com/contoso',
      apiHostname: 'dev.azure.com',
    })
    expect(parseAdoOrgUrl('https://contoso.visualstudio.com/DefaultCollection').org).toBe(
      'contoso',
    )
    expect(parseAdoOrgUrl('contoso.visualstudio.com').org).toBe('contoso')
    expect(parseAdoOrgUrl('contoso').canonicalUrl).toBe('https://dev.azure.com/contoso')
  })

  it('rejects unsupported hosts and reserved visualstudio subdomains', () => {
    expect(parseAdoOrgUrl('https://example.com/org').ok).toBe(false)
    expect(parseAdoOrgUrl('https://dev.azure.com/').ok).toBe(false)
    expect(parseAdoOrgUrl('https://app.visualstudio.com').ok).toBe(false)
    expect(parseAdoOrgUrl('https://vssps.visualstudio.com').ok).toBe(false)
  })
})

describe('normalizeAdoOrgUrl', () => {
  it('preserves visualstudio host style for display/profiles', () => {
    expect(normalizeAdoOrgUrl('https://contoso.visualstudio.com/extra')).toEqual({
      ok: true,
      url: 'https://contoso.visualstudio.com',
    })
  })

  it('canonicalizes bare org names to dev.azure.com', () => {
    expect(normalizeAdoOrgUrl('contoso')).toEqual({
      ok: true,
      url: 'https://dev.azure.com/contoso',
    })
  })
})

describe('API routing for both URL styles', () => {
  it('browser proxy always uses org segment (Vite → dev.azure.com)', () => {
    expect(buildAdoApiBase('https://dev.azure.com/contoso')).toBe('/ado-proxy/contoso')
    expect(buildAdoApiBase('https://contoso.visualstudio.com')).toBe('/ado-proxy/contoso')
    expect(buildAdoApiBase('contoso')).toBe('/ado-proxy/contoso')
  })
})
