<script setup>
// "project depends on …": create (dependency = null) or edit one.
import { computed, reactive, watch } from 'vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import Autocomplete from '@/mini/components/Autocomplete.vue'
import FormModal from '@/components/forms/FormModal.vue'
import Field from '@/components/forms/Field.vue'
import { api } from '@/api'
import { useForm } from '@/composables/useForm'
import { useCatalogStore } from '@/stores/catalog'

const props = defineProps({
  visible: Boolean,
  project: { type: Object, required: true },
  dependency: { type: Object, default: null },
})
const emit = defineEmits(['close', 'saved'])

const catalog = useCatalogStore()
const form = useForm(['depends_on', 'kind', 'via', 'version', 'reference', 'environment', 'notes'])
const data = reactive({})

watch(() => props.visible, (visible) => {
  if (!visible) return
  form.reset()
  const d = props.dependency
  Object.assign(data, {
    depends_on: d?.depends_on ?? null,
    kind: d?.kind ?? 'other',
    via: d?.via ?? '',
    version: d?.version ?? '',
    reference: d?.reference ?? '',
    environment: d?.environment ?? '',
    notes: d?.notes ?? '',
  })
}, { immediate: true })

const projectOptions = computed(() => catalog.projects
  .filter(p => p.id !== props.project.id)
  .map(p => ({ id: p.id, label: p.name })))

async function save() {
  const body = { ...data, project: props.project.id, environment: data.environment || null }
  const ok = await form.run(() => props.dependency
    ? api(`dependencies/${props.dependency.id}/`, { method: 'PATCH', body })
    : api('dependencies/', { method: 'POST', body }))
  if (ok) emit('saved')
}

async function remove() {
  const ok = await form.run(() => api(`dependencies/${props.dependency.id}/`, { method: 'DELETE' }))
  if (ok) emit('saved')
}

const deleteMessage = computed(() => props.dependency
  ? `Remove “${props.project.name} depends on ${props.dependency.depends_on_detail.name}”`
    + (props.dependency.environment_name ? ` for ${props.dependency.environment_name}?` : '?') : '')
</script>

<template>
  <FormModal :visible="visible" :title="`${project.name} depends on…`"
             :saving="form.saving.value" :error="form.formError.value" :deleteMessage="deleteMessage"
             @save="save" @close="emit('close')" @delete="remove">
    <Boxes gap="0">
      <Box :size="66" class="py-0">
        <Field label="Project" :error="form.errors.value.depends_on">
          <Autocomplete v-model="data.depends_on" :options="projectOptions"
                        placeholder="Search a project…" aria-label="Depends on"/>
        </Field>
      </Box>
      <Box :size="33" class="py-0">
        <Field label="For" id="df-kind" :error="form.errors.value.kind">
          <select id="df-kind" v-model="data.kind" class="w-100">
            <option v-for="k in catalog.choices?.dependency_kinds" :key="k.value" :value="k.value">{{ k.label }}</option>
          </select>
        </Field>
      </Box>
      <Box :size="33" class="py-0">
        <Field label="Included as" id="df-via" :error="form.errors.value.via">
          <select id="df-via" v-model="data.via" class="w-100">
            <option value="">Not recorded</option>
            <option v-for="v in catalog.choices?.dependency_vias" :key="v.value" :value="v.value">{{ v.label }}</option>
          </select>
        </Field>
      </Box>
      <Box :size="33" class="py-0">
        <Field label="Version" id="df-version" :error="form.errors.value.version" help="@main, v1.6, a commit…">
          <input id="df-version" v-model.trim="data.version" class="w-100" maxlength="60">
        </Field>
      </Box>
      <Box :size="33" class="py-0">
        <Field label="In" id="df-environment" :error="form.errors.value.environment" help="When one environment includes it differently.">
          <select id="df-environment" v-model="data.environment" class="w-100">
            <option value="">The whole project</option>
            <option v-for="e in project.environments" :key="e.id" :value="e.id">{{ e.name }}</option>
          </select>
        </Field>
      </Box>
      <Box :size="100" class="py-0">
        <Field label="Reference" id="df-reference" :error="form.errors.value.reference" help="The URL, path or symlink it uses.">
          <input id="df-reference" v-model.trim="data.reference" class="w-100" maxlength="500">
        </Field>
      </Box>
      <Box :size="100" class="py-0">
        <Field label="Notes" id="df-notes" :error="form.errors.value.notes">
          <input id="df-notes" v-model="data.notes" class="w-100" maxlength="255">
        </Field>
      </Box>
    </Boxes>
  </FormModal>
</template>
