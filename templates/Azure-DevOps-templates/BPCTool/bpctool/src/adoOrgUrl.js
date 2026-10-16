/**
 * Azure DevOps organization URL helpers (SaaS only).
 */

export function parseAdoOrgUrl(raw) {
  const s = String(raw || '').trim()
  if (!s) {
    return { ok: false, error: 'URL or organization name required' }
  }

  let toParse = s

  if (!/^https?:\/\//i.test(s)) {
    const bareOrg = /^([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])$/
    if (bareOrg.test(s) && !s.includes('/') && !s.includes('.') && !s.includes(':')) {
      toParse = `https://dev.azure.com/${s}`
    } else if (/^dev\.azure\.com\//i.test(s)) {
      toParse = `https://${s}`
    } else if (/^[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]\.visualstudio\.com$/i.test(s)) {
      toParse = `https://${s}`
    } else {
      return {
        ok: false,
        error:
          'Enter a full https:// URL (for example https://dev.azure.com/yourorg or https://yourorg.visualstudio.com) or your organization name only.',
      }
    }
  }

  let url
  try {
    url = new URL(toParse)
  } catch {
    return { ok: false, error: 'Invalid URL' }
  }

  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return { ok: false, error: 'URL must use http or https' }
  }

  const host = url.hostname.toLowerCase()

  if (host === 'dev.azure.com') {
    const parts = url.pathname.split('/').filter(Boolean)
    if (parts.length === 0) {
      return {
        ok: false,
        error:
          'URL must include the organization after dev.azure.com (for example https://dev.azure.com/yourorg).',
      }
    }

    const org = parts[0]
    return {
      ok: true,
      org,
      canonicalUrl: `https://dev.azure.com/${org}`,
      apiHostname: 'dev.azure.com',
    }
  }

  if (host.endsWith('.visualstudio.com')) {
    const sub = host.slice(0, -'.visualstudio.com'.length)
    if (!sub || sub.includes('.') || /^(app|vssps|vsaex|pkgs|feeds)$/i.test(sub)) {
      return {
        ok: false,
        error:
          'URL must be https://dev.azure.com/{organization} or https://{organization}.visualstudio.com',
      }
    }

    return {
      ok: true,
      org: sub,
      canonicalUrl: `https://dev.azure.com/${sub}`,
      apiHostname: 'dev.azure.com',
    }
  }

  return {
    ok: false,
    error:
      'URL must be https://dev.azure.com/{organization} or https://{organization}.visualstudio.com',
  }
}

/**
 * Normalizes profile/display URL; preserves visualstudio.com host style when entered.
 */
export function normalizeAdoOrgUrl(raw) {
  const parsed = parseAdoOrgUrl(raw)
  if (!parsed.ok) {
    return parsed
  }

  const s = String(raw || '').trim()
  let toInspect = s
  if (!/^https?:\/\//i.test(s)) {
    if (/^[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]\.visualstudio\.com$/i.test(s)) {
      toInspect = `https://${s}`
    } else if (/^dev\.azure\.com\//i.test(s)) {
      toInspect = `https://${s}`
    } else {
      return { ok: true, url: parsed.canonicalUrl }
    }
  }

  try {
    const host = new URL(toInspect).hostname.toLowerCase()
    if (host.endsWith('.visualstudio.com')) {
      return { ok: true, url: `https://${parsed.org}.visualstudio.com` }
    }
  } catch {
    /* fall through */
  }

  return { ok: true, url: parsed.canonicalUrl }
}
