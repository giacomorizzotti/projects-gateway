<script setup>
// Create (repository = null) or edit a repository. The GitHub fields (language, pushed…)
// are filled by the GitHub sync and aren't edited here.
import { computed, reactive, watch } from 'vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import Sep from '@/mini/components/Sep.vue'
import MultiAutocomplete from '@/mini/components/MultiAutocomplete.vue'
import FormModal from '@/components/forms/FormModal.vue'
import Field from '@/components/forms/Field.vue'
import { api } from '@/api'
import { useForm } from '@/composables/useForm'
import { useCatalogStore } from '@/stores/catalog'

const props = defineProps({
  visible: Boolean,
  repository: { type: Object, default: null },
})
const emit = defineEmits(['close', 'saved'])

const catalog = useCatalogStore()
const form = useForm(['name', 'slug', 'hosting', 'remote_url', 'local_path', 'private', 'projects', 'notes'])
const data = reactive({})

// A new repository is on GitHub, while that hosting exists (Settings page); otherwise the first.
function defaultHosting() {
  const hostings = catalog.choices?.repository_hostings || []
  return (hostings.find(h => h.value === 'github') || hostings[0])?.value ?? ''
}

watch(() => props.visible, (visible) => {
  if (!visible) return
  form.reset()
  const r = props.repository
  Object.assign(data, {
    name: r?.name ?? '',
    slug: r?.slug ?? '',
    hosting: r?.hosting ?? defaultHosting(),
    remote_url: r?.remote_url ?? '',
    local_path: r?.local_path ?? '',
    private: r?.private ?? true,
    projects: [...(r?.projects ?? [])],
    notes: r?.notes ?? '',
  })
}, { immediate: true })

const projectOptions = computed(() => catalog.projects.map(p => ({ id: p.id, label: p.name })))

async function save() {
  const ok = await form.run(() => props.repository
    ? api(`repositories/${props.repository.slug}/`, { method: 'PATCH', body: data })
    : api('repositories/', { method: 'POST', body: data }))
  if (ok) {
    catalog.refresh()
    emit('saved')
  }
}

async function remove() {
  const ok = await form.run(() => api(`repositories/${props.repository.slug}/`, { method: 'DELETE' }))
  if (ok) {
    catalog.refresh()
    emit('saved')
  }
}

const deleteMessage = computed(() => (props.repository
  ? `Delete “${props.repository.name}” from the gateway? Only the record: the repo itself isn’t touched.` : ''))
</script>

<template>
  <FormModal :visible="visible" :title="repository ? `Edit ${repository.name}` : 'New repository'"
             :saving="form.saving.value" :error="form.formError.value" :deleteMessage="deleteMessage"
             @save="save" @close="emit('close')" @delete="remove">
    <Boxes gap="0">
      <Box :size="66" class="py-0">
        <Field label="Name" id="rf-name" :error="form.errors.value.name">
          <input id="rf-name" v-model="data.name" class="w-100" required>
        </Field>
      </Box>
      <Box :size="33" class="py-0">
        <Field label="Slug" id="rf-slug" :error="form.errors.value.slug">
          <input id="rf-slug" v-model.trim="data.slug" class="w-100" placeholder="from the name">
        </Field>
      </Box>
      <Box :size="33" class="py-0">
        <Field label="Hosting" id="rf-hosting" :error="form.errors.value.hosting">
          <select id="rf-hosting" v-model="data.hosting" class="w-100">
            <option v-for="h in catalog.choices?.repository_hostings" :key="h.value" :value="h.value">{{ h.label }}</option>
          </select>
        </Field>
      </Box>
      <Sep/>
      <Box :size="50" class="py-0">
        <Field label="Remote" id="rf-remote" :error="form.errors.value.remote_url" help="The git remote, e.g. git@github.com:owner/repo.git">
          <input id="rf-remote" v-model.trim="data.remote_url" class="w-100">
        </Field>
      </Box>
      <Box :size="50" class="py-0">
        <Field label="Local path" id="rf-path" :error="form.errors.value.local_path" help="Where it’s cloned on the gateway’s host, if it is.">
          <input id="rf-path" v-model.trim="data.local_path" class="w-100">
        </Field>
      </Box>
      <Box :size="100" class="py-0">
        <Field label="Projects" :error="form.errors.value.projects">
          <MultiAutocomplete v-model="data.projects" :options="projectOptions"
                             placeholder="Link a project…" aria-label="Projects"/>
        </Field>
      </Box>
      <Box :size="100" class="py-0">
        <Field label="Notes" id="rf-notes" :error="form.errors.value.notes">
          <textarea id="rf-notes" v-model="data.notes" class="w-100" rows="2"></textarea>
        </Field>
      </Box>
      <Box :size="100" class="py-0">
        <Field :error="form.errors.value.private">
          <label class="S">Visibility</label>
          <label class="S chip"><input type="checkbox" v-model="data.private"> Private</label>
        </Field>
      </Box>
    </Boxes>
  </FormModal>
</template>
