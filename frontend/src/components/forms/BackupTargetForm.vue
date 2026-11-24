<script setup>
// Create (target = null) or edit a backup target: a folder an agent writes backups to.
import { computed, reactive, watch } from 'vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import FormModal from '@/components/forms/FormModal.vue'
import Field from '@/components/forms/Field.vue'
import { api } from '@/api'
import { useForm } from '@/composables/useForm'
import { useCatalogStore } from '@/stores/catalog'

const props = defineProps({
  visible: Boolean,
  target: { type: Object, default: null },
  locations: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'saved'])

const catalog = useCatalogStore()
const form = useForm(['platform', 'name', 'path', 'mount', 'location', 'keep', 'notes'])
const data = reactive({})

watch(() => props.visible, (visible) => {
  if (!visible) return
  form.reset()
  const t = props.target
  Object.assign(data, {
    platform: t?.platform ?? catalog.platforms.find(p => p.kind === 'home_server')?.id ?? null,
    name: t?.name ?? '',
    path: t?.path ?? '',
    mount: t?.mount ?? '',
    location: t?.location ?? 'same_machine',
    keep: t?.keep ?? 0,
    notes: t?.notes ?? '',
  })
}, { immediate: true })

async function save() {
  const ok = await form.run(() => props.target
    ? api(`backup-targets/${props.target.id}/`, { method: 'PATCH', body: data })
    : api('backup-targets/', { method: 'POST', body: data }))
  if (ok) emit('saved')
}

async function remove() {
  const ok = await form.run(() => api(`backup-targets/${props.target.id}/`, { method: 'DELETE' }))
  if (ok) emit('saved')
}

const deleteMessage = computed(() => (props.target
  ? `Delete the target “${props.target.name}”? Jobs stop writing there; the backups already in it aren’t touched.` : ''))
</script>

<template>
  <FormModal :visible="visible" :title="target ? `Edit ${target.name}` : 'New backup target'"
             :saving="form.saving.value" :error="form.formError.value" :deleteMessage="deleteMessage"
             @save="save" @close="emit('close')" @delete="remove">
    <Boxes gap="0">
      <Box :size="66" class="py-0">
        <Field label="Name" id="btf-name" :error="form.errors.value.name">
          <input id="btf-name" v-model="data.name" class="w-100" required placeholder="NAS">
        </Field>
      </Box>
      <Box :size="33" class="py-0">
        <Field label="Platform" id="btf-platform" :error="form.errors.value.platform" help="Its agent writes here.">
          <select id="btf-platform" v-model="data.platform" class="w-100">
            <option v-for="p in catalog.platforms" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </Field>
      </Box>
      <Box :size="50" class="py-0">
        <Field label="Folder" id="btf-path" :error="form.errors.value.path"
               help="Absolute. It must also be inside the agent’s own target_roots.">
          <input id="btf-path" v-model.trim="data.path" class="w-100" required placeholder="/home/backups">
        </Field>
      </Box>
      <Box :size="50" class="py-0">
        <Field label="Must be mounted" id="btf-mount" :error="form.errors.value.mount"
               help="For a share: nothing is written while it isn’t mounted.">
          <input id="btf-mount" v-model.trim="data.mount" class="w-100" placeholder="/mnt/nas">
        </Field>
      </Box>
      <Box :size="50" class="py-0">
        <Field label="Where it is" id="btf-location" :error="form.errors.value.location">
          <select id="btf-location" v-model="data.location" class="w-100">
            <option v-for="l in locations" :key="l.value" :value="l.value">{{ l.label }}</option>
          </select>
        </Field>
      </Box>
      <Box :size="50" class="py-0">
        <Field label="Keep" id="btf-keep" :error="form.errors.value.keep"
               help="The newest N backups of each job. 0 keeps everything (you delete by hand).">
          <input id="btf-keep" v-model.number="data.keep" type="number" min="0" class="w-100">
        </Field>
      </Box>
      <Box :size="100" class="py-0">
        <Field label="Notes" id="btf-notes" :error="form.errors.value.notes">
          <textarea id="btf-notes" v-model="data.notes" class="w-100" rows="2"></textarea>
        </Field>
      </Box>
    </Boxes>
  </FormModal>
</template>
