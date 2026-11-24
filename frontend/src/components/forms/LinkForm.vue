<script setup>
// A labelled link on a project or a platform: owner is { project: id } or { platform: id }.
import { computed, reactive, watch } from 'vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import FormModal from '@/components/forms/FormModal.vue'
import Field from '@/components/forms/Field.vue'
import { api } from '@/api'
import { useForm } from '@/composables/useForm'

const props = defineProps({
  visible: Boolean,
  owner: { type: Object, required: true },
  ownerName: { type: String, default: '' },
  link: { type: Object, default: null },
})
const emit = defineEmits(['close', 'saved'])

const form = useForm(['label', 'url'])
const data = reactive({})

watch(() => props.visible, (visible) => {
  if (!visible) return
  form.reset()
  Object.assign(data, { label: props.link?.label ?? '', url: props.link?.url ?? '' })
}, { immediate: true })

async function save() {
  const body = { ...data, project: props.owner.project ?? null, platform: props.owner.platform ?? null }
  const ok = await form.run(() => props.link
    ? api(`links/${props.link.id}/`, { method: 'PATCH', body })
    : api('links/', { method: 'POST', body }))
  if (ok) emit('saved')
}

async function remove() {
  const ok = await form.run(() => api(`links/${props.link.id}/`, { method: 'DELETE' }))
  if (ok) emit('saved')
}

const deleteMessage = computed(() => (props.link ? `Delete the “${props.link.label}” link?` : ''))
</script>

<template>
  <FormModal :visible="visible" :title="link ? 'Edit link' : `New link${ownerName ? ' on ' + ownerName : ''}`"
             :saving="form.saving.value" :error="form.formError.value" :deleteMessage="deleteMessage"
             @save="save" @close="emit('close')" @delete="remove">
    <Boxes>
      <Box :size="33">
        <Field label="Label" id="lf-label" :error="form.errors.value.label">
          <input id="lf-label" v-model="data.label" class="w-100" required placeholder="Admin, Docs, Console…">
        </Field>
      </Box>
      <Box :size="66">
        <Field label="URL" id="lf-url" :error="form.errors.value.url">
          <input id="lf-url" v-model.trim="data.url" type="url" class="w-100" required placeholder="https://…">
        </Field>
      </Box>
    </Boxes>
  </FormModal>
</template>
