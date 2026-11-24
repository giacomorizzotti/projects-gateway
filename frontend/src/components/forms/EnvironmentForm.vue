<script setup>
// Create (environment = null) or edit one environment of `project`.
import { computed, reactive, watch } from 'vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import FormModal from '@/components/forms/FormModal.vue'
import Field from '@/components/forms/Field.vue'
import { api } from '@/api'
import { linesToList, listToLines, useForm } from '@/composables/useForm'
import { useCatalogStore } from '@/stores/catalog'

const props = defineProps({
  visible: Boolean,
  project: { type: Object, required: true },
  environment: { type: Object, default: null },
})
const emit = defineEmits(['close', 'saved'])

const catalog = useCatalogStore()
const form = useForm(['name', 'kind', 'platform', 'urls', 'path', 'runtime', 'deploy',
  'checks_enabled', 'notes'])

const data = reactive({})
const kindLabel = kind => (kind && kind !== 'other' ? catalog.labels.environment_kinds?.[kind] ?? '' : '')

watch(() => props.visible, (visible) => {
  if (!visible) return
  form.reset()
  const e = props.environment
  Object.assign(data, {
    kind: e?.kind ?? 'prod',
    name: e?.name ?? kindLabel('prod'),
    platform: e?.platform ?? '',
    urls: listToLines(e?.urls),
    path: e?.path ?? '',
    runtime: e?.runtime ?? '',
    deploy: e?.deploy ?? '',
    checks_enabled: e?.checks_enabled ?? true,
    notes: e?.notes ?? '',
  })
}, { immediate: true })

// The name follows the kind (PROD, DEV…) until it's edited by hand.
watch(() => data.kind, (kind, old) => {
  if (old && (!data.name || data.name === kindLabel(old))) data.name = kindLabel(kind)
})

async function save() {
  const body = { ...data, project: props.project.id, platform: data.platform || null, urls: linesToList(data.urls) }
  const ok = await form.run(() => props.environment
    ? api(`environments/${props.environment.id}/`, { method: 'PATCH', body })
    : api('environments/', { method: 'POST', body }))
  if (ok) {
    catalog.refresh()
    emit('saved')
  }
}

async function remove() {
  const ok = await form.run(() => api(`environments/${props.environment.id}/`, { method: 'DELETE' }))
  if (ok) {
    catalog.refresh()
    emit('saved')
  }
}

const deleteMessage = computed(() =>
  props.environment ? `Delete the “${props.environment.name}” environment of ${props.project.name}?` : '')
</script>

<template>
  <FormModal :visible="visible"
             :title="environment ? `${project.name}&nbsp;&nbsp;·&nbsp;&nbsp;${environment.name}` : `New environment for ${project.name}`"
             :saving="form.saving.value" :error="form.formError.value" :deleteMessage="deleteMessage"
             @save="save" @close="emit('close')" @delete="remove">
    <Boxes gap="0">
      <Box :size="25" class="py-0">
        <Field label="Kind" id="ef-kind" :error="form.errors.value.kind">
          <select id="ef-kind" v-model="data.kind" class="w-100">
            <option v-for="k in catalog.choices?.environment_kinds" :key="k.value" :value="k.value">{{ k.label }}</option>
          </select>
        </Field>
      </Box>
      <Box :size="33" class="py-0">
        <Field label="Name" id="ef-name" :error="form.errors.value.name">
          <input id="ef-name" v-model="data.name" class="w-100" required placeholder="PROD, DEV, DEM 2025…">
        </Field>
      </Box>
      <Box :size="40" class="py-0">
        <Field label="Platform" id="ef-platform" :error="form.errors.value.platform">
          <select id="ef-platform" v-model="data.platform" class="w-100">
            <option value="">Not recorded</option>
            <option v-for="pl in catalog.platforms" :key="pl.id" :value="pl.id">{{ pl.name }}</option>
          </select>
        </Field>
      </Box>
      <Box :size="100" class="py-0">
        <Field label="URLs" id="ef-urls" :error="form.errors.value.urls" help="One per line, http(s) only. The first one is shown on the dashboard.">
          <textarea id="ef-urls" v-model="data.urls" class="w-100" rows="2" placeholder="https://…"></textarea>
        </Field>
      </Box>
      <Box :size="50" class="py-0">
        <Field label="Path" id="ef-path" :error="form.errors.value.path" help="Folder on the platform, or the local repo.">
          <input id="ef-path" v-model="data.path" class="w-100">
        </Field>
      </Box>
      <Box :size="50" class="py-0">
        <Field label="Runtime" id="ef-runtime" :error="form.errors.value.runtime" help="e.g. Docker Compose, gunicorn + nginx, static.">
          <input id="ef-runtime" v-model="data.runtime" class="w-100">
        </Field>
      </Box>
      <Box :size="100" class="py-0">
        <Field label="Deploy" id="ef-deploy" :error="form.errors.value.deploy" help="How it gets there: git pull, FTP, deploy script…">
          <input id="ef-deploy" v-model="data.deploy" class="w-100">
        </Field>
      </Box>
      <Box :size="100" class="py-0">
        <Field label="Notes" id="ef-notes" :error="form.errors.value.notes">
          <textarea id="ef-notes" v-model="data.notes" class="w-100" rows="2"></textarea>
        </Field>
      </Box>
      <Box :size="100" class="">
        <Field :error="form.errors.value.checks_enabled" help="Off for hosts the gateway can’t reach (internal networks).">
          <label class="S chip"><input type="checkbox" v-model="data.checks_enabled"> Health checks on its URLs</label>
        </Field>
      </Box>
    </Boxes>
  </FormModal>
</template>
