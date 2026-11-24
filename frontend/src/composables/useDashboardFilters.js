// The dashboard's filters, remembered in localStorage across visits. Shared: usePersistedRef
// returns the same live ref for the same key, so the header's logo can reset what the
// dashboard shows, whether the dashboard is open or not.
import { usePersistedRef } from '@/mini/composables/usePersistedRef'

export function useDashboardFilters() {
  const search = usePersistedRef('gateway.dashboard.search', '')
  const platform = usePersistedRef('gateway.dashboard.platform', '')
  const showArchived = usePersistedRef('gateway.dashboard.showArchived', false)

  // The dashboard as it first opens: no search, every platform, archived projects hidden.
  function reset() {
    search.value = ''
    platform.value = ''
    showArchived.value = false
  }

  return { search, platform, showArchived, reset }
}
