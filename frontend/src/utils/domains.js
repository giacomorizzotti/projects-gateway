// Same thresholds as the backend's "Needs attention" (domains/attention.py).
const WARN_DAYS = 30
const DANGER_DAYS = 7

// The colour for a domain's expiry date: a renewal is near (and isn't automatic) or past.
export function expiryClass(d) {
  if (d.days_left == null) return 'white-text'
  if (d.days_left < 0) return 'danger-text'
  if (d.auto_renew) return 'white-text'
  if (d.days_left < DANGER_DAYS) return 'danger-text'
  if (d.days_left < WARN_DAYS) return 'warning-text'
  return ''
}

// A domain row's left border, like the environments' rows: green while far from expiry.
export function expiryBorder(d) {
  const cls = expiryClass(d)
  if (cls) return cls.replace('-text', '-border')
  return d.days_left == null ? 'light-grey-border' : 'success-border'
}

export function expiryBackground(d) {
  const cls = expiryClass(d)
  if (cls) return cls.replace('-text', '-bg')
  return d.days_left == null ? 'light-grey-bg' : 'success-bg'
}