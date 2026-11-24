<script setup>
// Create (project = null) or edit a project, including which repos, technologies and
// services it uses. Technologies, services and clients can be created on the spot.
import { computed, reactive, ref, watch } from 'vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import MultiAutocomplete from '@/mini/components/MultiAutocomplete.vue'
import MarkdownEditor from '@/mini/components/MarkdownEditor.vue'
import FormModal from '@/components/forms/FormModal.vue'
import Field from '@/components/forms/Field.vue'
import { api, ApiError } from '@/api'
import { useForm } from '@/composables/useForm'
import { useCatalogStore } from '@/stores/catalog'

const props = defineProps({
  visible: Boolean,
  project: { type: Object, default: null },
})
const emit = defineEmits(['close', 'saved', 'deleted'])

const catalog = useCatalogStore()
const form = useForm(['name', 'slug', 'group', 'status', 'client', 'description', 'notes', 'notes_markdown',
  'technologies', 'repository_ids', 'service_ids'])

const NEW_CLIENT = '__new__'
const data = reactive({})
const newClientName = ref('')

watch(() => props.visible, (visible) => {
  if (!visible) return
  form.reset()
  const p = props.project
  Object.assign(data, {
    name: p?.name ?? '',
    slug: p?.slug ?? '',
    group: p?.group ?? catalog.choices?.project_groups.find(g => !g.hidden)?.value ?? '',
    status: p?.status ?? 'active',
    client: p?.client ?? '',
    description: p?.description ?? '',
    notes: p?.notes ?? '',
    notes_markdown: p?.notes_markdown ?? true,
    technologies: [...(p?.technologies ?? [])],
    repository_ids: [...(p?.repository_ids ?? [])],
    service_ids: [...(p?.service_ids ?? [])],
  })
  newClientName.value = ''
}, { immediate: true })

const toOptions = list => list.map(x => ({ id: x.id, label: x.name }))
const techOptions = computed(() => toOptions(catalog.technologies))
const repoOptions = computed(() => toOptions(catalog.repositories))
const serviceOptions = computed(() => toOptions(catalog.services))

async function createTechnology(name) {
  await form.run(async () => {
    const tech = await api('technologies/', { method: 'POST', body: { name } })
    catalog.technologies.push(tech)
    data.technologies.push(tech.id)
  })
}

async function createService(name) {
  await form.run(async () => {
    const service = await api('services/', { method: 'POST', body: { name } })
    catalog.services.push(service)
    data.service_ids.push(service.id)
  })
}

async function save() {
  let saved = null
  const ok = await form.run(async () => {
    if (data.client === NEW_CLIENT) {
      // Its errors are about the client's name: show them under the client field.
      const client = await api('clients/', { method: 'POST', body: { name: newClientName.value } })
        .catch(e => { throw new ApiError(e.status, { client: e.data?.name || [e.message] }) })
      catalog.clients.push(client)
      data.client = client.id
    }
    const body = { ...data, client: data.client || null }
    saved = props.project
      ? await api(`projects/${props.project.slug}/`, { method: 'PATCH', body })
      : await api('projects/', { method: 'POST', body })
  })
  if (ok) {
    catalog.refresh()
    emit('saved', saved)
  }
}

async function remove() {
  const ok = await form.run(() => api(`projects/${props.project.slug}/`, { method: 'DELETE' }))
  if (ok) {
    catalog.refresh()
    emit('deleted')
  }
}

const deleteMessage = computed(() => {
  if (!props.project) return ''
  const n = props.project.environments?.length || 0
  return `Delete “${props.project.name}”, its ${n} environment${n === 1 ? '' : 's'}, links and dependencies? `
    + 'Its repositories stay, only unlinked.'
})
</script>

<template>
  <FormModal :visible="visible" :title="project ? `Edit ${project.name}` : 'New project'"
             :saving="form.saving.value" :error="form.formError.value" :deleteMessage="deleteMessage"
             @save="save" @close="emit('close')" @delete="remove">
    <Boxes>
      <Box :size="66">
        <Field label="Name" id="pf-name" :error="form.errors.value.name">
          <input id="pf-name" v-model="data.name" class="w-100" required>
        </Field>
      </Box>
      <Box :size="33">
        <Field label="Slug" id="pf-slug" :error="form.errors.value.slug" help="The page address. Empty: from the name.">
          <input id="pf-slug" v-model.trim="data.slug" class="w-100" placeholder="from the name">
        </Field>
      </Box>
      <Box :size="33">
        <Field label="Group" id="pf-group" :error="form.errors.value.group">
          <select id="pf-group" v-model="data.group" class="w-100">
            <option v-for="g in catalog.choices?.project_groups" :key="g.value" :value="g.value">{{ g.label }}</option>
          </select>
        </Field>
      </Box>
      <Box :size="33">
        <Field label="Status" id="pf-status" :error="form.errors.value.status">
          <select id="pf-status" v-model="data.status" class="w-100">
            <option v-for="s in catalog.choices?.project_statuses" :key="s.value" :value="s.value">{{ s.label }}</option>
          </select>
        </Field>
      </Box>
      <Box :size="33">
        <Field label="Client" id="pf-client" :error="form.errors.value.client">
          <select id="pf-client" v-model="data.client" class="w-100">
            <option value="">None (mine)</option>
            <option v-for="c in catalog.clients" :key="c.id" :value="c.id">{{ c.name }}</option>
            <option :value="NEW_CLIENT">New client…</option>
          </select>
          <input v-if="data.client === NEW_CLIENT" v-model="newClientName" class="w-100 mt-05"
                 placeholder="New client’s name" aria-label="New client’s name">
        </Field>
      </Box>
      <Box :size="100">
        <Field label="Description" id="pf-description" :error="form.errors.value.description" help="One line, shown on the dashboard card.">
          <input id="pf-description" v-model="data.description" class="w-100" maxlength="255">
        </Field>
      </Box>
      <Box :size="100">
        <Field label="Technologies" :error="form.errors.value.technologies">
          <MultiAutocomplete v-model="data.technologies" :options="techOptions" allowCreate
                             placeholder="Add a technology…" aria-label="Technologies"
                             @create="createTechnology"/>
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Repositories" :error="form.errors.value.repository_ids">
          <MultiAutocomplete v-model="data.repository_ids" :options="repoOptions"
                             placeholder="Link a repository…" aria-label="Repositories"/>
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Services" :error="form.errors.value.service_ids">
          <MultiAutocomplete v-model="data.service_ids" :options="serviceOptions" allowCreate
                             placeholder="Add a service…" aria-label="Services"
                             @create="createService"/>
        </Field>
      </Box>
      <Box :size="100">
        <Field label="Notes" id="pf-notes" :error="form.errors.value.notes || form.errors.value.notes_markdown"
               help="Markdown (Preview shows it), or plain text with the Plain switch. No secrets: say where they live instead.">
          <MarkdownEditor id="pf-notes" v-model="data.notes" v-model:markdown="data.notes_markdown" class="w-100" min-height="120px"/>
        </Field>
      </Box>
    </Boxes>
  </FormModal>
</template>
