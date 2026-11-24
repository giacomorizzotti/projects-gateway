// Live status (/api/status/): the worker's latest checks and "needs attention".
// One small answer, re-read when older than a minute; the Status page polls it.
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api'

const MAX_AGE = 60_000

export const useStatusStore = defineStore('status', () => {
  const data = ref(null)
  const error = ref('')
  const loading = ref(false)
  let loadedAt = 0
  let pending = null

  function load({ force = false } = {}) {
    if (!force && data.value && Date.now() - loadedAt < MAX_AGE) return Promise.resolve()
    if (pending) return pending
    loading.value = true
    pending = api('status/')
      .then(result => {
        data.value = result
        error.value = ''
        loadedAt = Date.now()
      })
      .catch(e => { error.value = e.message || 'Could not load the status.' })
      .finally(() => {
        loading.value = false
        pending = null
      })
    return pending
  }

  // environment id → its URL checks
  const byEnvironment = computed(() => {
    const out = {}
    for (const check of data.value?.checks || []) (out[check.environment] ||= []).push(check)
    return out
  })

  const attention = computed(() => data.value?.attention || [])
  const problems = computed(() => attention.value.filter(i => i.severity !== 'info'))

  // "Check now": the worker runs the checks within seconds of the request; wait for that run
  // (a minute or so at most, with retries). Resolves to '' or what went wrong.
  const checking = ref(false)
  async function checkNow({ every = 3000, timeout = 120_000 } = {}) {
    checking.value = true
    try {
      const { check_requested_at: asked } = await api('status/check/', { method: 'POST' })
      const deadline = Date.now() + timeout
      while (Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, every))
        await load({ force: true })
        const ran = data.value?.monitor?.checks_ran_at
        if (ran && new Date(ran) >= new Date(asked)) return ''
      }
      return 'No run from the worker in 2 minutes: is it running?'
    } catch (e) {
      return e.message || 'Could not ask for a check.'
    } finally {
      checking.value = false
    }
  }

  return { data, error, loading, load, byEnvironment, attention, problems, checking, checkNow }
})
