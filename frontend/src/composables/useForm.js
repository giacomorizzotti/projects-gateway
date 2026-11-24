// Saving state and DRF validation errors for one form.
//
// `fields` are the names the form shows next to their inputs: a 400 error on one of
// them goes under that input, anything else (non_field_errors, a hidden field) goes in
// the form's general error, so no message is ever lost.
import { ref } from 'vue'
import { ApiError } from '@/api'

export function useForm(fields = []) {
  const saving = ref(false)
  const errors = ref({})
  const formError = ref('')

  function reset() {
    errors.value = {}
    formError.value = ''
  }

  function show(e) {
    if (!(e instanceof ApiError) || e.status !== 400 || !e.data || typeof e.data !== 'object') {
      formError.value = e.message || 'Could not save.'
      return
    }
    const byField = {}
    const general = []
    for (const [key, value] of Object.entries(e.data)) {
      const message = Array.isArray(value) ? value.join(' ') : String(value)
      if (fields.includes(key)) byField[key] = message
      else general.push(key === 'non_field_errors' || key === 'detail' ? message : `${key}: ${message}`)
    }
    errors.value = byField
    formError.value = general.join(' ') || 'Please check the fields marked below.'
  }

  // Runs `fn` (the API calls) once at a time. Returns true if it succeeded.
  async function run(fn) {
    if (saving.value) return false
    saving.value = true
    reset()
    try {
      await fn()
      return true
    } catch (e) {
      show(e)
      return false
    } finally {
      saving.value = false
    }
  }

  return { saving, errors, formError, reset, run }
}

// Textarea ⇄ list of strings, one per line.
export const linesToList = text => text.split('\n').map(s => s.trim()).filter(Boolean)
export const listToLines = list => (list || []).join('\n')
