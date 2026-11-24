<script setup>
// Create (job = null) or edit a backup job: what is backed up, when, and to which targets
// (made in the first, copied to the others).
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
  job: { type: Object, default: null },
  targets: { type: Array, default: () => [] },
  choices: { type: Object, default: () => ({}) },
  defaultExcludes: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'saved'])

const catalog = useCatalogStore()
const form = useForm(['name', 'slug', 'project', 'environment', 'platform', 'kind', 'source', 'credentials',
  'excludes', 'folder', 'prefix', 'frequency', 'hour', 'target_ids', 'enabled', 'notes'])
const data = reactive({})
const placement = reactive({ first: null, copies: [] })

watch(() => props.visible, (visible) => {
  if (!visible) return
  form.reset()
  const j = props.job
  Object.assign(data, {
    name: j?.name ?? '',
    slug: j?.slug ?? '',
    project: j?.project ?? null,
    environment: j?.environment ?? null,
    platform: j?.platform ?? catalog.platforms.find(p => p.kind === 'home_server')?.id ?? null,
    kind: j?.kind ?? 'files',
    source: j?.source ?? '',
    credentials: j?.credentials ?? '',
    excludes: (j?.excludes ?? props.defaultExcludes).join('\n'),
    folder: j?.folder ?? '',
    prefix: j?.prefix ?? '',
    frequency: j?.frequency ?? 'daily',
    hour: j?.hour ?? 0,
    enabled: j?.enabled ?? true,
    notes: j?.notes ?? '',
  })
  const ids = (j?.targets ?? []).map(t => t.id)
  placement.first = ids[0] ?? null
  placement.copies = ids.slice(1)
}, { immediate: true })

const platformTargets = computed(() => props.targets.filter(t => t.platform === data.platform))
const projectEnvironments = computed(() =>
  catalog.projects.find(p => p.id === data.project)?.environments ?? [])
const sourceLabel = computed(() => ({ mysql: 'Database', files: 'Folder', sqlite: 'Database file' })[data.kind])
const sourceHelp = computed(() => ({
  mysql: 'Its name in MySQL.',
  files: 'Absolute path; inside the agent’s source_roots.',
  sqlite: 'Absolute path to the .sqlite3 file; inside the agent’s source_roots.',
})[data.kind])

async function save() {
  const body = {
    ...data,
    excludes: data.kind === 'files' ? data.excludes.split('\n').map(s => s.trim()).filter(Boolean) : [],
    credentials: data.kind === 'mysql' ? data.credentials : '',
    target_ids: [placement.first, ...placement.copies.filter(id => id !== placement.first)].filter(Boolean),
  }
  const ok = await form.run(() => props.job
    ? api(`backup-jobs/${props.job.id}/`, { method: 'PATCH', body })
    : api('backup-jobs/', { method: 'POST', body }))
  if (ok) emit('saved')
}

async function remove() {
  const ok = await form.run(() => api(`backup-jobs/${props.job.id}/`, { method: 'DELETE' }))
  if (ok) emit('saved')
}

const deleteMessage = computed(() => (props.job
  ? `Delete the job “${props.job.name}” and its run history? The backups already made aren’t touched.` : ''))
</script>

<template>
  <FormModal :visible="visible" :title="job ? `Edit ${job.name}` : 'New backup job'"
             :saving="form.saving.value" :error="form.formError.value" :deleteMessage="deleteMessage"
             @save="save" @close="emit('close')" @delete="remove">
    <Boxes>
      <Box :size="50">
        <Field label="Name" id="bjf-name" :error="form.errors.value.name">
          <input id="bjf-name" v-model="data.name" class="w-100" required>
        </Field>
      </Box>
      <Box :size="25">
        <Field label="Slug" id="bjf-slug" :error="form.errors.value.slug">
          <input id="bjf-slug" v-model.trim="data.slug" class="w-100" placeholder="from the name">
        </Field>
      </Box>
      <Box :size="25">
        <Field label="Platform" id="bjf-platform" :error="form.errors.value.platform" help="Its agent runs it.">
          <select id="bjf-platform" v-model="data.platform" class="w-100">
            <option v-for="p in catalog.platforms" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Project" id="bjf-project" :error="form.errors.value.project">
          <select id="bjf-project" v-model="data.project" class="w-100">
            <option :value="null">None (several projects)</option>
            <option v-for="p in catalog.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Environment" id="bjf-env" :error="form.errors.value.environment">
          <select id="bjf-env" v-model="data.environment" class="w-100" :disabled="!projectEnvironments.length">
            <option :value="null">The whole project</option>
            <option v-for="e in projectEnvironments" :key="e.id" :value="e.id">{{ e.name }}</option>
          </select>
        </Field>
      </Box>
      <Box :size="33">
        <Field label="Kind" id="bjf-kind" :error="form.errors.value.kind">
          <select id="bjf-kind" v-model="data.kind" class="w-100">
            <option v-for="k in choices.kinds" :key="k.value" :value="k.value">{{ k.label }}</option>
          </select>
        </Field>
      </Box>
      <Box :size="data.kind === 'mysql' ? 33 : 66">
        <Field :label="sourceLabel" id="bjf-source" :error="form.errors.value.source" :help="sourceHelp">
          <input id="bjf-source" v-model.trim="data.source" class="w-100" required>
        </Field>
      </Box>
      <Box :size="33" v-if="data.kind === 'mysql'">
        <Field label="Option file" id="bjf-cnf" :error="form.errors.value.credentials"
               help="Its name in the agent’s credentials folder (chmod 600), e.g. shop.cnf. Never the password.">
          <input id="bjf-cnf" v-model.trim="data.credentials" class="w-100">
        </Field>
      </Box>
      <Box :size="100" v-if="data.kind === 'files'">
        <Field label="Leave out" id="bjf-excludes" :error="form.errors.value.excludes" help="zip -x patterns, one per line.">
          <textarea id="bjf-excludes" v-model="data.excludes" class="w-100" rows="3"></textarea>
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Folder in each target" id="bjf-folder" :error="form.errors.value.folder">
          <input id="bjf-folder" v-model.trim="data.folder" class="w-100" placeholder="the slug">
        </Field>
      </Box>
      <Box :size="50">
        <Field label="File name prefix" id="bjf-prefix" :error="form.errors.value.prefix"
               help="e.g. shop → shop_DB_BK_20261113000001.sql.gz">
          <input id="bjf-prefix" v-model.trim="data.prefix" class="w-100" placeholder="the slug">
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Every" id="bjf-frequency" :error="form.errors.value.frequency">
          <select id="bjf-frequency" v-model="data.frequency" class="w-100">
            <option v-for="f in choices.frequencies" :key="f.value" :value="f.value">{{ f.label }}</option>
          </select>
        </Field>
      </Box>
      <Box :size="25">
        <Field label="At (hour)" id="bjf-hour" :error="form.errors.value.hour">
          <input id="bjf-hour" v-model.number="data.hour" type="number" min="0" max="23" class="w-100">
        </Field>
      </Box>
      <Box :size="25" class="flex align-items-end">
        <Field :error="form.errors.value.enabled">
          <label class="S"><input type="checkbox" v-model="data.enabled"> On the schedule</label>
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Made in" id="bjf-first" :error="form.errors.value.target_ids">
          <select id="bjf-first" v-model="placement.first" class="w-100">
            <option :value="null" disabled>Choose a target</option>
            <option v-for="t in platformTargets" :key="t.id" :value="t.id">{{ t.name }} ({{ t.path }})</option>
          </select>
        </Field>
      </Box>
      <Box :size="50">
        <Field label="Copied to">
          <label v-for="t in platformTargets.filter(t => t.id !== placement.first)" :key="t.id" class="S block">
            <input type="checkbox" :value="t.id" v-model="placement.copies"> {{ t.name }}
          </label>
          <span v-if="platformTargets.length < 2" class="S muted-text">No other target on this platform.</span>
        </Field>
      </Box>
      <Box :size="100">
        <Field label="Notes" id="bjf-notes" :error="form.errors.value.notes">
          <textarea id="bjf-notes" v-model="data.notes" class="w-100" rows="2"></textarea>
        </Field>
      </Box>
    </Boxes>
  </FormModal>
</template>
