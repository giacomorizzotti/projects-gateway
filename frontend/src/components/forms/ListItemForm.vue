<script setup>
// Create (item = null) or edit one entry of a simple list on the Settings page: a project
// group, a client, a technology… `fields` says what it has:
//   [{ key, label, type: 'text' | 'select' | 'checkbox', options: [{ value, label }], help }]
// Saved through `endpoint` (e.g. 'groups/'): POST to create, PATCH/DELETE `endpoint + id/`.
import { reactive, watch } from 'vue'
import FormModal from '@/components/forms/FormModal.vue'
import Field from '@/components/forms/Field.vue'
import { api } from '@/api'
import { useForm } from '@/composables/useForm'

const props = defineProps({
  visible: Boolean,
  endpoint: { type: String, required: true },
  noun: { type: String, required: true },          // "group", "client"… for the title
  item: { type: Object, default: null },
  fields: { type: Array, required: true },
  defaults: { type: Object, default: () => ({}) },
  // Asked before deleting; empty: no Delete button (e.g. a group that still has projects).
  deleteMessage: { type: String, default: '' },
  // Shown under the fields (e.g. why it can't be deleted).
  hint: { type: String, default: '' },
})
const emit = defineEmits(['close', 'saved'])

const form = useForm(props.fields.map(f => f.key))
const data = reactive({})

watch(() => props.visible, (visible) => {
  if (!visible) return
  form.reset()
  for (const f of props.fields) data[f.key] = props.item?.[f.key] ?? props.defaults[f.key] ?? (f.type === 'checkbox' ? false : '')
}, { immediate: true })

async function save() {
  const ok = await form.run(() => props.item
    ? api(`${props.endpoint}${props.item.id}/`, { method: 'PATCH', body: data })
    : api(props.endpoint, { method: 'POST', body: data }))
  if (ok) emit('saved')
}

async function remove() {
  const ok = await form.run(() => api(`${props.endpoint}${props.item.id}/`, { method: 'DELETE' }))
  if (ok) emit('saved')
}
</script>

<template>
  <FormModal :visible="visible" :title="item ? `Edit ${item.name}` : `New ${noun}`"
             :saving="form.saving.value" :error="form.formError.value" :deleteMessage="item ? deleteMessage : ''"
             @save="save" @close="emit('close')" @delete="remove">
    <template v-for="f in fields" :key="f.key">
      <Field v-if="f.type === 'checkbox'" :error="form.errors.value[f.key]" :help="f.help">
        <label class="S"><input type="checkbox" v-model="data[f.key]"> {{ f.label }}</label>
      </Field>
      <Field v-else :label="f.label" :id="`li-${f.key}`" :error="form.errors.value[f.key]" :help="f.help">
        <select v-if="f.type === 'select'" :id="`li-${f.key}`" v-model="data[f.key]" class="w-100">
          <option v-for="o in f.options" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <input v-else :id="`li-${f.key}`" v-model.trim="data[f.key]" class="w-100" required>
      </Field>
    </template>
    <p v-if="item && hint" class="S muted-text">{{ hint }}</p>
  </FormModal>
</template>
