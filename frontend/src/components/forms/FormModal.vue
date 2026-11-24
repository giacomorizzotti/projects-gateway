<script setup>
// A form in a mini Modal: title, fields (default slot), the general error, and
// Delete / Cancel / Save. Delete only appears with a `deleteMessage`, and asks first.
import { ref } from 'vue'
import Modal from '@/mini/components/Modal.vue'
import Button from '@/mini/components/Button.vue'
import ConfirmDialog from '@/mini/components/ConfirmDialog.vue'

const props = defineProps({
  visible: Boolean,
  title: { type: String, required: true },
  saving: Boolean,
  error: { type: String, default: '' },
  deleteMessage: { type: String, default: '' },
  saveText: { type: String, default: 'Save' },
})
const emit = defineEmits(['save', 'close', 'delete'])

const confirmRef = ref(null)

async function askDelete() {
  const ok = await confirmRef.value.show({
    title: 'Delete?', message: props.deleteMessage, confirmText: 'Delete', cancelText: 'Keep',
  })
  if (ok) emit('delete')
}
</script>

<template>
  <Modal :visible="visible" @close="emit('close')">
    <form novalidate @submit.prevent="emit('save')">
      <h3 class="mt-0 me-3">{{ title }}</h3>
      <slot/>
      <p v-if="error" class="danger-box S" role="alert">{{ error }}</p>
      <div class="flex flex-wrap gap-05 align-items-center mt-1">
        <Button v-if="deleteMessage" danger invert :disabled="saving" @click="askDelete">Delete</Button>
        <span class="ms-auto"></span>
        <Button color="grey" invert @click="emit('close')">Cancel</Button>
        <Button type="submit" :disabled="saving">{{ saving ? 'Saving…' : saveText }}</Button>
      </div>
    </form>
  </Modal>
  <ConfirmDialog ref="confirmRef"/>
</template>
