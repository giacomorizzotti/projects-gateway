// Wording and colours for the health checks, shared by the status dots and the Status page.
import { formatDate, formatDateTime, hostOf } from '@/utils/format'

// Same threshold as the backend's "Needs attention" (Let's Encrypt renews at 30 days left).
const TLS_WARN_DAYS = 21

export function daysLeft(iso) {
  return Math.floor((new Date(iso) - Date.now()) / 86_400_000)
}

// What's wrong with a URL that is up: a failure being confirmed, a certificate close to
// expiry, a name pointing elsewhere.
export function checkWarnings(c) {
  if (c.state !== 'up') return []
  const out = []
  if (c.failing_since) out.push(`not answering since ${formatDateTime(c.failing_since)} (${c.error}): checking again`)
  if (c.tls_expires_at && daysLeft(c.tls_expires_at) < TLS_WARN_DAYS) {
    out.push(`certificate expires in ${daysLeft(c.tls_expires_at)} days`)
  } else if (c.tls_error) {
    out.push(c.tls_error)
  }
  if (c.tls_elsewhere?.length) out.push(`certificate can’t renew here (it also covers ${c.tls_elsewhere.join(', ')})`)
  if (c.dns_match === false) out.push('the name points away from its platform')
  return out
}

export function describeCheck(c) {
  if (c.state === 'down') return `down since ${formatDateTime(c.since)}: ${c.error}`
  if (c.failing_since) return checkWarnings(c).join('&nbsp;&nbsp;·&nbsp;&nbsp;')
  const answer = [c.status_code, c.response_ms != null && `${c.response_ms} ms`].filter(Boolean).join(', ')
  return ['up' + (answer ? ` (${answer})` : ''), ...checkWarnings(c)].join('&nbsp;&nbsp;·&nbsp;&nbsp;')
}

// One environment's checks summed up in a colour, a short label and a tooltip.
export function checkSummary(checks) {
  if (!checks?.length) return { cls: 'grey-bg', label: 'Not checked', title: 'Not checked yet' }
  const title = checks.map(c => `${hostOf(c.url)}: ${describeCheck(c)}`).join('\n')
  const down = checks.filter(c => c.state === 'down').length
  if (down) {
    return { cls: 'danger-bg', title, label: down === checks.length ? 'Down' : `${down} of ${checks.length} URLs down` }
  }
  // Up, but browsers stop visitors at a warning: as red as down for them.
  if (checks.some(c => c.state === 'up' && c.tls_error?.startsWith('Certificate not valid'))) {
    return { cls: 'danger-bg', title, label: 'Up, but its certificate isn’t valid' }
  }
  // A failure isn't "down" until it holds up a few minutes later (the worker checks again).
  if (checks.some(c => c.state === 'up' && c.failing_since)) {
    return { cls: 'warning-bg', title, label: 'Not answering: checking again' }
  }
  if (checks.some(c => checkWarnings(c).length)) return { cls: 'warning-bg', title, label: 'Up, with a warning' }
  return { cls: 'success-bg', title, label: 'Up' }
}

export function timeAgo(iso) {
  if (!iso) return 'never'
  const minutes = Math.round((Date.now() - new Date(iso)) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return formatDate(iso)
}

export function duration(fromIso, toIso) {
  const minutes = Math.round((new Date(toIso) - new Date(fromIso)) / 60_000)
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return `${hours} h ${minutes % 60} min`
  return `${Math.floor(hours / 24)} days`
}

export const SEVERITY_BOX = { danger: 'danger-box', warning: 'warning-box', info: 'info-box' }
// For flags (a coloured background, no border), as on the project and platform pages.
export const SEVERITY_FLAG = { danger: 'danger-bg', warning: 'warning-bg', info: 'info-bg' }
export const KIND_LABEL = {
  down: 'Down', tls: 'Certificate', dns: 'DNS', backup: 'Backup', worker: 'Checks',
  github: 'GitHub', cleanup: 'Cleanup', scan: 'Scan', service: 'Service', nginx: 'nginx', git: 'git', domain: 'Domain', malware: 'Malware',
  security: 'Security',
}

export const shortPath = path => path.replace(/^\/home\/projects\//, '')
