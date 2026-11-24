// The whole catalog is small (tens of projects), so it's loaded once and filtered in the browser.
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api'

export const useCatalogStore = defineStore('catalog', () => {
  const projects = ref([])
  const platforms = ref([])
  const repositories = ref([])
  // Lookups for the edit forms.
  const clients = ref([])
  const technologies = ref([])
  const services = ref([])
  // Every "project depends on project" row, for the dependency tree.
  const dependencies = ref([])
  // The domains I own, each with the projects and sites using it (for the project pages).
  const domains = ref([])
  const choices = ref(null)
  const loading = ref(false)
  const error = ref('')
  let loadPromise = null

  async function load({ force = false } = {}) {
    if (choices.value && !force) return
    if (loadPromise) return loadPromise
    loading.value = true
    error.value = ''
    loadPromise = (async () => {
      try {
        const [p, pl, r, cl, t, s, d, c, dm] = await Promise.all([
          api('projects/'), api('platforms/'), api('repositories/'),
          api('clients/'), api('technologies/'), api('services/'), api('dependencies/'), api('choices/'),
          api('domains/'),
        ])
        domains.value = dm
        projects.value = p
        platforms.value = pl
        repositories.value = r
        clients.value = cl
        technologies.value = t
        services.value = s
        dependencies.value = d
        choices.value = c
      } catch (e) {
        error.value = e.message || 'Could not load the catalog.'
      } finally {
        loading.value = false
        loadPromise = null
      }
    })()
    return loadPromise
  }

  // After any edit: everything is re-read (it's small), so every page stays consistent.
  function refresh() {
    return load({ force: true })
  }

  // value → label, for every fixed list (groups, statuses, kinds…)
  const labels = computed(() => {
    const out = {}
    for (const [name, options] of Object.entries(choices.value || {})) {
      out[name] = Object.fromEntries(options.map(o => [o.value, o.label]))
    }
    return out
  })

  return {
    projects, platforms, repositories, clients, technologies, services, dependencies, domains, choices, labels,
    loading, error, load, refresh,
  }
})
