<script setup>
// The GitHub side: profile, what the last sync found, "Sync now", token expiry.
// The token itself never reaches the browser: only whether there is one.
import { computed, onMounted, ref } from 'vue'
import { Github } from '@iconoir/vue'
import Space from '@/mini/components/Space.vue'
import Button from '@/mini/components/Button.vue'
import { api } from '@/api'
import { useCatalogStore } from '@/stores/catalog'
import { formatDate, formatDateTime } from '@/utils/format'

const emit = defineEmits(['showAttention'])

const catalog = useCatalogStore()
const status = ref(null)
const syncing = ref(false)
const error = ref('')
const result = ref(null)

onMounted(async () => {
  try {
    status.value = await api('github/')
  } catch (e) {
    error.value = e.message
  }
})

async function syncNow() {
  syncing.value = true
  error.value = ''
  result.value = null
  try {
    const data = await api('github/sync/', { method: 'POST' })
    status.value = data
    result.value = data.result
    catalog.refresh()
  } catch (e) {
    if (e.data?.owner) status.value = e.data   // a failed sync still returns the status
    error.value = e.message
  } finally {
    syncing.value = false
  }
}

const expiresInDays = computed(() => {
  const at = status.value?.token_expires_at
  return at ? Math.floor((new Date(at) - Date.now()) / 86_400_000) : null
})

const counts = computed(() => status.value?.counts || {})
const attention = computed(() => (counts.value.unlinked || 0) + (counts.value.missing || 0))
</script>

<template>
  <h4 class="light italic grey-text h5">GitHub profile</h4>
  <div class="fb-bg border dark-grey-border p-15">
    <p v-if="!status && !error" class="muted-text m-0">Loading GitHub…</p>

    <template v-if="status">
      <div class="flex flex-wrap gap-15 align-items-start">
        <img v-if="status.profile?.avatar_url" :src="status.profile.avatar_url" alt="" width="56" height="56" class="gh-avatar mt-05">
        <div style="flex: 1 1 14rem">
          <h3 class="m-0">
            <Github width="0.9em" height="0.9em" aria-hidden="true" style="vertical-align: -0.1em" class="me-05 repository-text"/>{{ status.profile?.name || status.owner }}
            <a :href="status.profile?.html_url || `https://github.com/${status.owner}`" target="_blank" rel="noopener noreferrer" class="S light">@{{ status.profile?.login || status.owner }}</a>
          </h3>
          <p v-if="status.profile?.bio" class="S mt-0 mb-0">{{ status.profile.bio }}</p>
          <p v-if="counts.repos" class="S muted-text m-0">
            {{ counts.repos }} repos&nbsp;&nbsp;·&nbsp;&nbsp;{{ counts.public }} public&nbsp;&nbsp;·&nbsp;&nbsp;{{ counts.private }} private&nbsp;&nbsp;·&nbsp;&nbsp;{{ counts.archived }} archived
          </p>
          <Space/>
          <p class="m-0 flex align-items-center">
            <Button invert size="S" class="repository-btn m-0" :disabled="syncing || !status.configured" @click="syncNow" hard>{{ syncing ? 'Syncing…' : 'Sync now' }}</Button>
            <span class="XS muted-text">
              <template v-if="status.synced_at">Synced {{ formatDateTime(status.synced_at) }}</template>
              <template v-else>Never synced</template>
            </span>
          </p>
        </div>
      </div>

      <p v-if="!status.configured" class="info-box S mb-0">
        No GitHub token yet. Create a fine-grained token (resource owner {{ status.owner }}, all repositories,
        permission Metadata: read-only), put it in the gateway’s <code>.env</code> as <code>GITHUB_TOKEN=</code>,
        and restart the gateway.
      </p>
      <p v-if="expiresInDays !== null && expiresInDays <= 14" class="warning-box S mb-0">
        <template v-if="expiresInDays < 0">The GitHub token expired on {{ formatDate(status.token_expires_at) }}.</template>
        <template v-else>The GitHub token expires on {{ formatDate(status.token_expires_at) }} ({{ expiresInDays }} days).</template>
        Create a new one and update <code>.env</code>.
      </p>
      <Space height="2"/>
      <p class="m-0">
        <span v-if="result" class="dark-grey-box S success-text me-05">
          {{ result.repos }} repos read<template v-if="result.created">, {{ result.created }} new</template>.
        </span>
        <span v-if="attention" class="dark-grey-box S warning-text me-05">
          <template v-if="counts.unlinked">{{ counts.unlinked }} GitHub repo{{ counts.unlinked === 1 ? '' : 's' }} with no project. </template>
          <template v-if="counts.missing">{{ counts.missing }} of yours not found on GitHub (deleted, renamed, or outside the token’s repos). </template>
          <a href="#" @click.prevent="emit('showAttention')">Show them</a>
        </span>
      </p>
    </template>

    <p v-if="error" class="danger-box S mb-0" role="alert">{{ error }}</p>
    <p v-else-if="status?.last_error" class="danger-box S mb-0">Last sync failed: {{ status.last_error }}</p>
  </div>
</template>
