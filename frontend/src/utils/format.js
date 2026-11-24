export function hostOf(url) {
  try {
    const u = new URL(url)
    const path = u.pathname === '/' ? '' : u.pathname.replace(/\/$/, '')
    return u.host + path
  } catch {
    return url
  }
}

const STATUS_BG = {
  development: 'info-bg',
  maintenance: 'warning-bg',
  discontinued: 'light-grey-bg',
  archived: 'light-grey-bg',
}

const STATUS_BOX = {
  development: 'info-box',
  maintenance: 'warning-box',
  discontinued: 'light-grey-box',
  archived: 'light-grey-box',
}

// mini box class for a project status ('' for active: no badge needed).
export function statusClass(status) {
  return STATUS_BG[status] || ''
}

export function statusBoxClass(status) {
  return STATUS_BOX[status] || ''
}

// An environment kind's colour name: env-prod, env-test, … (their colours are in main.scss).
const ENV_KINDS = ['prod', 'test', 'dev', 'local', 'other']

export function envColor(kind) {
  return ENV_KINDS.includes(kind) ? `env-${kind}` : 'env-other'
}

export function envClass(kind) {
  return `${envColor(kind)}-box`
}

export function envBorderColor(kind) {
  return `${envColor(kind)}-border`
}

export function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function formatDateTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

// A GitHub repo the sync found that no project uses (archived ones don't count).
export const needsProject = r => !!r.github_id && !r.archived && !r.projects.length
export const needsAttention = r => needsProject(r) || r.github_missing

// "CDN @main", "Git clone / deploy&nbsp;&nbsp;·&nbsp;&nbsp;946fa84 (2026-11-02)", with "PROD: " when it's per environment.
export function dependencyHow(d, { withEnvironment = true } = {}) {
  const how = [d.via_label, d.version].filter(Boolean).join(' ')
  const env = withEnvironment && d.environment_name ? `${d.environment_name}: ` : ''
  return how ? env + how : (env ? env + 'how not recorded' : '')
}

// How a change to the dependency reaches the project: the question "if I change mini…".
export function dependencyUpdate(d) {
  const floating = !d.version || ['@main', 'main', 'latest'].includes(d.version)
  switch (d.via) {
    case 'cdn':
    case 'url':
      if (floating) return { label: 'live', cls: 'info-box', title: 'Gets every change as soon as it’s published' }
      if (d.version === 'latest tag') return { label: 'on release', cls: 'text-box', title: 'Gets the latest tagged release' }
      return { label: 'pinned', cls: 'text-box', title: `Stays on ${d.version} until the link is changed` }
    case 'symlink':
      return { label: 'live', cls: 'info-box', title: 'Linked to the working copy: changes are there at once (bundled apps: at their next build)' }
    case 'source':
      return { label: 'next build', cls: 'text-box', title: 'Compiled in when the project builds' }
    case 'git':
    case 'copy':
      return { label: 'manual', cls: 'warning-box', title: 'Only updated by hand: a pull, a deploy or a new copy' }
    case 'package':
      return { label: 'on upgrade', cls: 'text-box', title: 'Updated when the package version is bumped' }
    default:
      return null
  }
}

// IPv4 and IPv6 apart: an IPv6 address or network always has a colon, an IPv4 one never.
export const isIPv6 = ip => ip.includes(':')

// The non-empty families of a list of addresses (or networks): [{ label: 'IPv4', ips }, …].
export function ipFamilies(ips = []) {
  return [
    { label: 'IPv4', ips: ips.filter(ip => !isIPv6(ip)) },
    { label: 'IPv6', ips: ips.filter(isIPv6) },
  ].filter(f => f.ips.length)
}
