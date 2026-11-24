<script setup>
// Create (service = null) or edit a web service the projects use (Iubenda, Paddle, an SMTP…).
// The kind suggests the ones already used, so the list groups well.
import { computed, reactive, watch } from 'vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import MultiAutocomplete from '@/mini/components/MultiAutocomplete.vue'
import FormModal from '@/components/forms/FormModal.vue'
import Field from '@/components/forms/Field.vue'
import { api } from '@/api'
import { useForm } from '@/composables/useForm'
import { useCatalogStore } from '@/stores/catalog'

const props = defineProps({
  visible: Boolean,
  service: { type: Object, default: null },
})
const emit = defineEmits(['close', 'saved'])

const catalog = useCatalogStore()
const form = useForm(['name', 'kind', 'url', 'account', 'projects', 'notes'])
const data = reactive({})

watch(() => props.visible, (visible) => {
  if (!visible) return
  form.reset()
  const s = props.service
  Object.assign(data, {
    name: s?.name ?? '',
    kind: s?.kind ?? '',
    url: s?.url ?? '',
    account: s?.account ?? '',
    projects: [...(s?.projects ?? [])],
    notes: s?.notes ?? '',
  })
}, { immediate: true })

const projectOptions = computed(() => catalog.projects.map(p => ({ id: p.id, label: p.name })))
const kinds = computed(() => [...new Set(catalog.services.map(s => s.kind).filter(Boolean))].sort())

async function save() {
  const ok = await form.run(() => props.service
    ? api(`services/${props.service.slug}/`, { method: 'PATCH', body: data })
    : api('services/', { method: 'POST', body: data }))
  if (ok) {
    catalog.refresh()
    emit('saved')
  }
}

async function remove() {
  const ok = await form.run(() => api(`services/${props.service.slug}/`, { method: 'DELETE' }))
  if (ok) {
    catalog.refresh()
    emit('saved')
  }
}

const deleteMessage = computed(() => {
  const s = props.service
  if (!s) return ''
  const used = s.projects.length ? ` It’s unlinked from ${s.projects.length} project${s.projects.length === 1 ? '' : 's'}.` : ''
  return `Remove ${s.name} from the catalog?${used} Nothing changes at the service itself.`
})
</script>

<template>
  <FormModal :visible="visible" :title="service ? `Edit ${service.name}` : 'New service'"
             :saving="form.saving.value" :error="form.formError.value" :deleteMessage="deleteMessage"
             @save="save" @close="emit('close')" @delete="remove">
    <Boxes>
      <Box :size="50">
        <Field label="Name" id="sf-name" :error="form.errors.value.name">
          <input id="sf-name" v-model.trim="data.name" class="w-100" required>
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Kind" id="sf-kind" :error="form.errors.value.kind" help="What it does for the projects, e.g. Privacy (GDPR), Payments, Email.">
          <input id="sf-kind" v-model.trim="data.kind" class="w-100" list="sf-kinds">
          <datalist id="sf-kinds"><option v-for="k in kinds" :key="k" :value="k"/></datalist>
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Link" id="sf-url" :error="form.errors.value.url" help="Its dashboard or login page.">
          <input id="sf-url" v-model.trim="data.url" type="url" class="w-100" placeholder="https://">
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Account" id="sf-account" :error="form.errors.value.account"
               help="Which login or team it’s under. Never a password: those stay in the password manager.">
          <input id="sf-account" v-model.trim="data.account" class="w-100" autocomplete="off">
        </Field>
      </Box>
      <Box :size="100">
        <Field label="Used by" :error="form.errors.value.projects">
          <MultiAutocomplete v-model="data.projects" :options="projectOptions" placeholder="Link a project…" aria-label="Projects"/>
        </Field>
      </Box>
      <Box :size="100">
        <Field label="Notes" id="sf-notes" :error="form.errors.value.notes" help="The plan, when it renews, what it’s set up for…">
          <textarea id="sf-notes" v-model="data.notes" class="w-100" rows="2"></textarea>
        </Field>
      </Box>
    </Boxes>
  </FormModal>
</template>
