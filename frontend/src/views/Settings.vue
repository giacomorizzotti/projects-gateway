<script setup>
// The catalog's lists: the project groups (the dashboard's sections, in their order), the
// clients, the technologies and their categories. Add, rename, delete; groups also reorder
// and can be hidden.
import { computed, onMounted, ref } from 'vue'
import { NavArrowDown, NavArrowUp } from '@iconoir/vue'
import Container from '@/mini/components/Container.vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import Button from '@/mini/components/Button.vue'
import LoadingBox from '@/mini/components/LoadingBox.vue'
import Tabs from '@/mini/components/Tabs.vue'
import { usePersistedRef } from '@/mini/composables/usePersistedRef'
import EditButton from '@/components/EditButton.vue'
import ListItemForm from '@/components/forms/ListItemForm.vue'
import { api } from '@/api'
import { useCatalogStore } from '@/stores/catalog'

const catalog = useCatalogStore()
const groups = ref([])
const groupsError = ref('')
async function loadGroups() {
  try {
    groups.value = await api('groups/')
    groupsError.value = ''
  } catch (e) {
    groupsError.value = e.message || 'Could not load the groups.'
  }
}
const categories = ref([])
const categoriesError = ref('')
async function loadCategories() {
  try {
    categories.value = await api('technology-categories/')
    categoriesError.value = ''
  } catch (e) {
    categoriesError.value = e.message || 'Could not load the categories.'
  }
}
onMounted(() => {
  catalog.load()
  loadGroups()
  loadCategories()
})

const tab = usePersistedRef('gateway.settings.tab', 'groups')     // groups | clients | technologies | categories
const TABS = computed(() => [
  { value: 'groups', label: `Project groups (${groups.value.length})` },
  { value: 'clients', label: `Clients (${catalog.clients.length})` },
  { value: 'technologies', label: `Technologies (${catalog.technologies.length})` },
  { value: 'categories', label: `Technology categories (${categories.value.length})` },
])

const categoryLabel = computed(() =>
  Object.fromEntries((catalog.choices?.technology_categories || []).map(c => [c.value, c.label])))
const technologies = computed(() => [...catalog.technologies].sort((a, b) =>
  (categoryLabel.value[a.category] || '').localeCompare(categoryLabel.value[b.category] || '') || a.name.localeCompare(b.name)))

// Groups: up and down, saved at once (the dashboard follows this order).
const moving = ref(false)
async function move(index, delta) {
  const ids = groups.value.map(g => g.id)
  ;[ids[index], ids[index + delta]] = [ids[index + delta], ids[index]]
  moving.value = true
  try {
    groups.value = await api('groups/reorder/', { method: 'POST', body: { ids } })
    catalog.refresh()
  } finally {
    moving.value = false
  }
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`

// What each list's form edits, and what deleting one of its entries does.
const FORMS = computed(() => ({
  group: {
    endpoint: 'groups/', noun: 'group',
    fields: [
      { key: 'name', label: 'Name' },
      { key: 'hidden', type: 'checkbox', label: 'Hidden, like Archive',
        help: 'Its projects are off the dashboard unless “Show archived” is on, and their sites aren’t health-checked.' },
    ],
    defaults: { hidden: false },
    deleteMessage: g => (g.project_count ? '' : `Delete the group ${g.name}? It has no projects.`),
    hint: g => (g.project_count ? `${plural(g.project_count, 'project is', 'projects are')} in it: move them to another group to delete it.` : ''),
  },
  client: {
    endpoint: 'clients/', noun: 'client',
    fields: [{ key: 'name', label: 'Name' }],
    deleteMessage: c => {
      const used = [c.project_count && plural(c.project_count, 'project', 'projects'), c.domain_count && plural(c.domain_count, 'domain', 'domains')].filter(Boolean)
      return `Delete the client ${c.name}?` + (used.length ? ` Its ${used.join(' and ')} will have no client.` : '')
    },
  },
  technology: {
    endpoint: 'technologies/', noun: 'technology',
    fields: [
      { key: 'name', label: 'Name' },
      { key: 'category', type: 'select', label: 'Category',
        options: [...(catalog.choices?.technology_categories || []), { value: '', label: 'No category' }] },
    ],
    defaults: { category: categoryLabel.value.other ? 'other' : '' },
    deleteMessage: t => `Delete ${t.name}?` + (t.project_count ? ` It’s removed from ${plural(t.project_count, 'project', 'projects')}.` : ''),
  },
  category: {
    endpoint: 'technology-categories/', noun: 'category',
    fields: [{ key: 'name', label: 'Name' }],
    deleteMessage: c => (c.technology_count ? '' : `Delete the category ${c.name}? It has no technologies.`),
    hint: c => (c.technology_count ? `${plural(c.technology_count, 'technology is', 'technologies are')} in it: move them to another category to delete it.` : ''),
  },
}))

// null = closed; { kind, item } to edit, { kind } for a new one.
const editing = ref(null)
const form = computed(() => editing.value && FORMS.value[editing.value.kind])
async function saved() {
  const kind = editing.value?.kind
  editing.value = null
  await catalog.refresh()
  if (kind === 'group') await loadGroups()
  if (kind === 'category' || kind === 'technology') await loadCategories()     // the names, or the counts
}
</script>

<template>
  <Container>
    <Boxes spaceTopBot>
      <Box :size="100">
        <h1 class="m-0">Settings</h1>
        <p class="muted-text m-0">The catalog’s lists: the dashboard’s project groups, the clients, the technologies and their categories.</p>
      </Box>

      <Box :size="100" v-if="catalog.loading && !catalog.choices"><LoadingBox/></Box>
      <Box :size="100" v-else-if="catalog.error"><p class="danger-box">{{ catalog.error }}</p></Box>

      <Box :size="100" v-else class="wrap-anywhere">
        <Tabs v-model="tab" :tabs="TABS" label="Lists">
          <template v-if="tab === 'groups'">
            <p class="S muted-text">The dashboard’s sections, in this order. Renaming one changes nothing in its projects.</p>
            <p v-if="groupsError" class="danger-box S">{{ groupsError }}</p>
            <table class="data-table S">
              <thead><tr><th>Order</th><th>Group</th><th>Projects</th><th></th></tr></thead>
              <tbody>
                <tr v-for="(g, i) in groups" :key="g.id">
                  <td class="nowrap">
                    <Button size="XS" invert :disabled="moving || i === 0" @click="move(i, -1)" :aria-label="`Move ${g.name} up`" class="m-0 me-025">
                      <NavArrowUp width="14" height="14" aria-hidden="true"/>
                    </Button>
                    <Button size="XS" invert :disabled="moving || i === groups.length - 1" @click="move(i, 1)" :aria-label="`Move ${g.name} down`" class="m-0">
                      <NavArrowDown width="14" height="14" aria-hidden="true"/>
                    </Button>
                  </td>
                  <td>
                    <strong>{{ g.name }}</strong>
                    <span v-if="g.hidden" class="text-box XS ms-05" title="Off the dashboard unless “Show archived” is on; no health checks">hidden</span>
                  </td>
                  <td>{{ g.project_count }}</td>
                  <td class="right"><EditButton :label="`Edit ${g.name}`" @click="editing = { kind: 'group', item: g }"/></td>
                </tr>
              </tbody>
            </table>
            <p><Button size="S" @click="editing = { kind: 'group' }">+ New group</Button></p>
          </template>

          <template v-else-if="tab === 'clients'">
            <p v-if="!catalog.clients.length" class="muted-text">No client yet.</p>
            <table v-else class="data-table S">
              <thead><tr><th>Client</th><th>Projects</th><th>Domains</th><th></th></tr></thead>
              <tbody>
                <tr v-for="c in catalog.clients" :key="c.id">
                  <td><strong>{{ c.name }}</strong></td>
                  <td>{{ c.project_count }}</td>
                  <td>{{ c.domain_count }}</td>
                  <td class="right"><EditButton :label="`Edit ${c.name}`" @click="editing = { kind: 'client', item: c }"/></td>
                </tr>
              </tbody>
            </table>
            <p><Button size="S" @click="editing = { kind: 'client' }">+ New client</Button></p>
          </template>

          <template v-else-if="tab === 'technologies'">
            <p v-if="!technologies.length" class="muted-text">No technology yet.</p>
            <table v-else class="data-table S">
              <thead><tr><th>Technology</th><th>Category</th><th>Projects</th><th></th></tr></thead>
              <tbody>
                <tr v-for="t in technologies" :key="t.id">
                  <td><strong>{{ t.name }}</strong></td>
                  <td>{{ categoryLabel[t.category] || t.category || '–' }}</td>
                  <td>{{ t.project_count }}</td>
                  <td class="right"><EditButton :label="`Edit ${t.name}`" @click="editing = { kind: 'technology', item: t }"/></td>
                </tr>
              </tbody>
            </table>
            <p><Button size="S" @click="editing = { kind: 'technology' }">+ New technology</Button></p>
          </template>

          <template v-else>
            <p class="S muted-text">What the technologies are grouped by. Renaming one changes nothing in its technologies.</p>
            <p v-if="categoriesError" class="danger-box S">{{ categoriesError }}</p>
            <p v-if="!categories.length" class="muted-text">No category yet.</p>
            <table v-else class="data-table S">
              <thead><tr><th>Category</th><th>Technologies</th><th></th></tr></thead>
              <tbody>
                <tr v-for="c in categories" :key="c.id">
                  <td><strong>{{ c.name }}</strong></td>
                  <td>{{ c.technology_count }}</td>
                  <td class="right"><EditButton :label="`Edit ${c.name}`" @click="editing = { kind: 'category', item: c }"/></td>
                </tr>
              </tbody>
            </table>
            <p><Button size="S" @click="editing = { kind: 'category' }">+ New category</Button></p>
          </template>
        </Tabs>
      </Box>
    </Boxes>

    <ListItemForm v-if="form" :visible="!!editing" :endpoint="form.endpoint" :noun="form.noun"
                  :item="editing.item || null" :fields="form.fields" :defaults="form.defaults || {}"
                  :deleteMessage="editing.item ? form.deleteMessage(editing.item) : ''"
                  :hint="editing.item && form.hint ? form.hint(editing.item) : ''"
                  @close="editing = null" @saved="saved"/>
  </Container>
</template>

<style scoped>
.nowrap {
  white-space: nowrap;
}
</style>
