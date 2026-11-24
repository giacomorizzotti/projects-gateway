<script setup>
// Create (platform = null) or edit a platform.
import { computed, reactive, watch } from 'vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import FormModal from '@/components/forms/FormModal.vue'
import Field from '@/components/forms/Field.vue'
import { api } from '@/api'
import { linesToList, listToLines, useForm } from '@/composables/useForm'
import { isIPv6 } from '@/utils/format'
import { useCatalogStore } from '@/stores/catalog'

const props = defineProps({
  visible: Boolean,
  platform: { type: Object, default: null },
})
const emit = defineEmits(['close', 'saved', 'deleted'])

const catalog = useCatalogStore()
const form = useForm(['name', 'slug', 'kind', 'provider', 'location', 'os', 'dynamic_dns',
  'public_ips', 'hostnames', 'notes', 'cleanup_notes'])
const data = reactive({})

watch(() => props.visible, (visible) => {
  if (!visible) return
  form.reset()
  const p = props.platform
  Object.assign(data, {
    name: p?.name ?? '',
    slug: p?.slug ?? '',
    kind: p?.kind ?? 'vps',
    provider: p?.provider ?? '',
    location: p?.location ?? '',
    os: p?.os ?? '',
    dynamic_dns: p?.dynamic_dns ?? '',
    public_ipv4: listToLines((p?.public_ips || []).filter(ip => !isIPv6(ip))),
    public_ipv6: listToLines((p?.public_ips || []).filter(isIPv6)),
    hostnames: listToLines(p?.hostnames),
    notes: p?.notes ?? '',
    cleanup_notes: p?.cleanup_notes ?? '',
  })
}, { immediate: true })

// The API reports a bad entry of the whole list, named in quotes: shown under its family's box.
function ipError(family) {
  const message = form.errors.value.public_ips
  if (!message) return ''
  const entry = String(message).match(/"([^"]+)"/)?.[1] || ''
  return (isIPv6(entry) ? 'IPv6' : 'IPv4') === family ? message : ''
}

async function save() {
  let saved = null
  const { public_ipv4, public_ipv6, ...rest } = data
  // Stored as one list: the checks compare each family with its own.
  const body = { ...rest, public_ips: [...linesToList(public_ipv4), ...linesToList(public_ipv6)], hostnames: linesToList(data.hostnames) }
  const ok = await form.run(async () => {
    saved = props.platform
      ? await api(`platforms/${props.platform.slug}/`, { method: 'PATCH', body })
      : await api('platforms/', { method: 'POST', body })
  })
  if (ok) {
    catalog.refresh()
    emit('saved', saved)
  }
}

async function remove() {
  const ok = await form.run(() => api(`platforms/${props.platform.slug}/`, { method: 'DELETE' }))
  if (ok) {
    catalog.refresh()
    emit('deleted')
  }
}

const deleteMessage = computed(() => {
  if (!props.platform) return ''
  const n = props.platform.environment_count ?? props.platform.environments?.length ?? 0
  return `Delete “${props.platform.name}”?`
    + (n ? ` Its ${n} environment${n === 1 ? '' : 's'} stay, with no platform.` : '')
})
</script>

<template>
  <FormModal :visible="visible" :title="platform ? `Edit ${platform.name}` : 'New platform'"
             :saving="form.saving.value" :error="form.formError.value" :deleteMessage="deleteMessage"
             @save="save" @close="emit('close')" @delete="remove">
    <Boxes>
      <Box :size="40">
        <Field label="Name" id="plf-name" :error="form.errors.value.name">
          <input id="plf-name" v-model="data.name" class="w-100" required>
        </Field>
      </Box>
      <Box :size="25">
        <Field label="Slug" id="plf-slug" :error="form.errors.value.slug">
          <input id="plf-slug" v-model.trim="data.slug" class="w-100" placeholder="from the name">
        </Field>
      </Box>
      <Box :size="33">
        <Field label="Kind" id="plf-kind" :error="form.errors.value.kind">
          <select id="plf-kind" v-model="data.kind" class="w-100">
            <option v-for="k in catalog.choices?.platform_kinds" :key="k.value" :value="k.value">{{ k.label }}</option>
          </select>
        </Field>
      </Box>
      <Box :size="33">
        <Field label="Provider" id="plf-provider" :error="form.errors.value.provider">
          <input id="plf-provider" v-model="data.provider" class="w-100" placeholder="A hosting company, home…">
        </Field>
      </Box>
      <Box :size="33">
        <Field label="Location" id="plf-location" :error="form.errors.value.location">
          <input id="plf-location" v-model="data.location" class="w-100">
        </Field>
      </Box>
      <Box :size="33">
        <Field label="OS" id="plf-os" :error="form.errors.value.os">
          <input id="plf-os" v-model="data.os" class="w-100" placeholder="Ubuntu 24.04…">
        </Field>
      </Box>
      <Box :size="33">
        <Field label="Public IPv4" id="plf-ipv4" :error="ipError('IPv4')"
               help="One per line: an address, or a network (198.51.100.0/24) when a CDN gives each site its own.">
          <textarea id="plf-ipv4" v-model="data.public_ipv4" class="w-100" rows="2"></textarea>
        </Field>
      </Box>
      <Box :size="33">
        <Field label="Public IPv6" id="plf-ipv6" :error="ipError('IPv6')"
               help="One per line, e.g. 2a02:4780::/32. Without any, a site’s IPv6 answer isn’t compared.">
          <textarea id="plf-ipv6" v-model="data.public_ipv6" class="w-100" rows="2"></textarea>
        </Field>
      </Box>
      <Box :size="33">
        <Field label="Hostnames" id="plf-hostnames" :error="form.errors.value.hostnames" help="One per line.">
          <textarea id="plf-hostnames" v-model="data.hostnames" class="w-100" rows="2"></textarea>
        </Field>
      </Box>
      <Box :size="33">
        <Field label="Dynamic DNS" id="plf-ddns" :error="form.errors.value.dynamic_dns" help="For a dynamic IP: the name that always points to it.">
          <input id="plf-ddns" v-model.trim="data.dynamic_dns" class="w-100">
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Notes" id="plf-notes" :error="form.errors.value.notes" help="No secrets: say where they live instead.">
          <textarea id="plf-notes" v-model="data.notes" class="w-100" rows="4"></textarea>
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Cleanup to do" id="plf-cleanup" :error="form.errors.value.cleanup_notes">
          <textarea id="plf-cleanup" v-model="data.cleanup_notes" class="w-100" rows="4"></textarea>
        </Field>
      </Box>
    </Boxes>
  </FormModal>
</template>
