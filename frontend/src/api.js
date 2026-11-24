// JSON calls to the gateway's own API (same origin: /api/…), with the auth token.
import { useAuthStore } from '@/mini/stores/auth'

export class ApiError extends Error {
  constructor(status, data) {
    super(typeof data?.detail === 'string' ? data.detail : `Request failed (${status})`)
    this.status = status
    this.data = data
  }
}

export async function api(path, { method = 'GET', body } = {}) {
  const auth = useAuthStore()
  const init = { method, headers: { Accept: 'application/json' } }
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  const response = await auth.authFetch(`/api/${path}`, init)
  if (response.status === 204) return null
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, data)
  return data
}
