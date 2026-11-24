<script setup>
// Create (domain = null, `name` prefilled from a suggestion) or edit a domain I own.
// The registry fills the expiry when it publishes it. Where it's renewed and where its DNS
// is edited are Services (left empty, they're linked by themselves when a service's name
// matches what the registry says). A client or a service can be created on the spot, as
// in the project form.
import { computed, reactive, ref, watch } from 'vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import MultiAutocomplete from '@/mini/components/MultiAutocomplete.vue'
import FormModal from '@/components/forms/FormModal.vue'
import Field from '@/components/forms/Field.vue'
import { api, ApiError } from '@/api'
import { useForm } from '@/composables/useForm'
import { useCatalogStore } from '@/stores/catalog'

const props = defineProps({
  visible: Boolean,
  domain: { type: Object, default: null },
  name: { type: String, default: '' },
})
const emit = defineEmits(['close', 'saved'])

const catalog = useCatalogStore()
const form = useForm(['name', 'registrar_service', 'dns_service', 'client', 'auto_renew', 'expires_on', 'projects', 'notes'])
const NEW_CLIENT = '__new__'
const NEW_SERVICE = '__new__'
const data = reactive({})
const newClientName = ref('')
const newServiceName = reactive({ registrar_service: '', dns_service: '' })

watch(() => props.visible, (visible) => {
  if (!visible) return
  form.reset()
  const d = props.domain
  Object.assign(data, {
    name: d?.name ?? props.name,
    registrar_service: d?.registrar_service ?? null,
    dns_service: d?.dns_service ?? null,
    client: d?.client ?? null,
    auto_renew: d?.auto_renew ?? false,
    expires_on: d?.expires_on ?? null,
    projects: [...(d?.projects ?? [])],
    notes: d?.notes ?? '',
  })
  newClientName.value = ''
  Object.assign(newServiceName, { registrar_service: '', dns_service: '' })
}, { immediate: true })

const projectOptions = computed(() => catalog.projects.map(p => ({ id: p.id, label: p.name })))
const serviceOptions = computed(() => [...catalog.services].sort((a, b) => a.name.localeCompare(b.name)))

// What the registry says, under each field.
const registrarHelp = computed(() => (props.domain?.registrar
  ? `Where it’s renewed, and with which account. The registry says: ${props.domain.registrar}.`
  : 'Where it’s renewed, and with which account.') + ' Empty: linked by itself when a service’s name matches the registry.')
const dnsHelp = computed(() => {
  const ns = props.domain?.nameservers ?? []
  return (ns.length ? `Where the zone is edited. Nameservers: ${ns.join(', ')}.` : 'Where the zone is edited.')
    + ' Empty: linked by itself when a service’s name matches them.'
})

// A new service typed in a field, created once even when both fields name it.
async function serviceId(field, created) {
  if (data[field] !== NEW_SERVICE) return data[field]
  const name = newServiceName[field].trim()
  const key = name.toLowerCase()
  if (!created[key]) {
    // Its errors are about the service's name: show them under this field.
    const service = await api('services/', { method: 'POST', body: { name, kind: 'Domains' } })
      .catch(e => { throw new ApiError(e.status, { [field]: e.data?.name || e.data?.slug || [e.message] }) })
    catalog.services.push(service)
    created[key] = service.id
  }
  return created[key]
}

async function save() {
  const ok = await form.run(async () => {
    if (data.client === NEW_CLIENT) {
      // Its errors are about the client's name: show them under the client field.
      const client = await api('clients/', { method: 'POST', body: { name: newClientName.value } })
        .catch(e => { throw new ApiError(e.status, { client: e.data?.name || [e.message] }) })
      catalog.clients.push(client)
      data.client = client.id
    }
    const created = {}
    data.registrar_service = await serviceId('registrar_service', created)
    data.dns_service = await serviceId('dns_service', created)
    const body = { ...data, expires_on: data.expires_on || null }
    return props.domain
      ? api(`domains/${props.domain.id}/`, { method: 'PATCH', body })
      : api('domains/', { method: 'POST', body })
  })
  if (ok) {
    catalog.refresh()
    emit('saved')
  }
}

async function remove() {
  const ok = await form.run(() => api(`domains/${props.domain.id}/`, { method: 'DELETE' }))
  if (ok) {
    catalog.refresh()
    emit('saved')
  }
}

const deleteMessage = computed(() => (props.domain
  ? `Stop tracking ${props.domain.name}? Only the record: nothing changes at the registrar.` : ''))
</script>

<template>
  <FormModal :visible="visible" :title="domain ? `Edit ${domain.name}` : 'Track a domain'"
             :saving="form.saving.value" :error="form.formError.value" :deleteMessage="deleteMessage"
             @save="save" @close="emit('close')" @delete="remove">
    <Boxes>
      <Box :size="50">
        <Field label="Domain" id="df-name" :error="form.errors.value.name" help="The registered name, e.g. example.com.">
          <input id="df-name" v-model.trim="data.name" class="w-100" required>
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Expires on" id="df-expires" :error="form.errors.value.expires_on"
               help="Filled from the registry where it publishes it; .eu and .es don’t.">
          <input id="df-expires" v-model="data.expires_on" type="date" class="w-100">
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Registrar" id="df-registrar" :error="form.errors.value.registrar_service" :help="registrarHelp">
          <select id="df-registrar" v-model="data.registrar_service" class="w-100">
            <option :value="null">Not linked</option>
            <option v-for="s in serviceOptions" :key="s.id" :value="s.id">{{ s.name }}</option>
            <option :value="NEW_SERVICE">New service…</option>
          </select>
          <input v-if="data.registrar_service === NEW_SERVICE" v-model="newServiceName.registrar_service" class="w-100 mt-05"
                 placeholder="New service’s name, e.g. Aruba" aria-label="New registrar service’s name">
        </Field>
      </Box>
      <Box :size="50">
        <Field label="DNS" id="df-dns" :error="form.errors.value.dns_service" :help="dnsHelp">
          <select id="df-dns" v-model="data.dns_service" class="w-100">
            <option :value="null">Not linked</option>
            <option v-for="s in serviceOptions" :key="s.id" :value="s.id">{{ s.name }}</option>
            <option :value="NEW_SERVICE">New service…</option>
          </select>
          <input v-if="data.dns_service === NEW_SERVICE" v-model="newServiceName.dns_service" class="w-100 mt-05"
                 placeholder="New service’s name, e.g. Cloudflare" aria-label="New DNS service’s name">
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Client" id="df-client" :error="form.errors.value.client" help="When you renew it for a client.">
          <select id="df-client" v-model="data.client" class="w-100">
            <option :value="null">Mine</option>
            <option v-for="c in catalog.clients" :key="c.id" :value="c.id">{{ c.name }}</option>
            <option :value="NEW_CLIENT">New client…</option>
          </select>
          <input v-if="data.client === NEW_CLIENT" v-model="newClientName" class="w-100 mt-05"
                 placeholder="New client’s name" aria-label="New client’s name">
        </Field>
      </Box>
      <Box :size="50" class="flex align-items-end">
        <Field :error="form.errors.value.auto_renew">
          <label class="S"><input type="checkbox" v-model="data.auto_renew"> Renews automatically</label>
        </Field>
      </Box>
      <Box :size="100">
        <Field label="Also used by" :error="form.errors.value.projects"
               help="Projects whose URLs are under it are linked by themselves; add the others (a redirect, a parked name).">
          <MultiAutocomplete v-model="data.projects" :options="projectOptions" placeholder="Link a project…" aria-label="Projects"/>
        </Field>
      </Box>
      <Box :size="100">
        <Field label="Notes" id="df-notes" :error="form.errors.value.notes">
          <textarea id="df-notes" v-model="data.notes" class="w-100" rows="2"></textarea>
        </Field>
      </Box>
    </Boxes>
  </FormModal>
</template>
