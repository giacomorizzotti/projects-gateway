<script setup>
// The domains I own: expiry, registrar, DNS, and the projects and sites using each. Below,
// the names found in the catalog's URLs that aren't tracked yet: "+ Track" the ones that are mine.
import { computed, onMounted, ref } from 'vue'
import { Globe } from '@iconoir/vue'
import Container from '@/mini/components/Container.vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import Button from '@/mini/components/Button.vue'
import LoadingBox from '@/mini/components/LoadingBox.vue'
import EditButton from '@/components/EditButton.vue'
import DomainForm from '@/components/forms/DomainForm.vue'
import { api } from '@/api'
import { useCatalogStore } from '@/stores/catalog'
import CatalogCounts from '@/components/CatalogCounts.vue'
import { formatDate } from '@/utils/format'
import { expiryBorder, expiryClass, expiryBackground } from '@/utils/domains'
import { timeAgo } from '@/utils/status'

const catalog = useCatalogStore()
const suggestions = ref([])
async function loadSuggestions() {
  suggestions.value = await api('domains/suggestions/').catch(() => [])
}
onMounted(() => {
  catalog.load()
  loadSuggestions()
})

const domains = computed(() => [...catalog.domains].sort((a, b) =>
  (a.days_left ?? 1e9) - (b.days_left ?? 1e9) || a.name.localeCompare(b.name)))

const refreshing = ref(null)
async function refresh(domain) {
  refreshing.value = domain.id
  try {
    await api(`domains/${domain.id}/refresh/`, { method: 'POST' })
    await catalog.refresh()
  } finally {
    refreshing.value = null
  }
}

// null = closed; { domain } to edit, { name } to track a suggestion, {} for a new one.
const editing = ref(null)
function saved() {
  editing.value = null
  loadSuggestions()
}
</script>

<template>
  <Container>
    <Boxes spaceBot>
      <Box :size="100">
        <h1 class="m-0">Domains</h1>
        <p class="light-grey-text mt-0">
          The domains I own or renew. Expiry, registrar and DNS come from each registry once a day (RDAP; WHOIS for .it);
          .eu and .es publish no expiry, so their date is typed. Registrar and DNS link to the
          <RouterLink :to="{ name: 'services' }">services</RouterLink> they’re managed in, with the account.
          The projects using a domain come from the catalog’s URLs.
        </p>
        <CatalogCounts class="mt-05 mb-15"/>
        <p class="m-0">
          <Button size="S" class="domain-btn" @click="editing = {}" hard>+ Track a domain</Button>
        </p>
      </Box>

      <Box :size="100" v-if="catalog.loading && !catalog.choices"><LoadingBox dark/></Box>
      <Box :size="100" v-else-if="catalog.error"><p class="danger-box">{{ catalog.error }}</p></Box>

      <Box :size="100" v-else class="wrap-anywhere">
        <p v-if="!domains.length" class="light-grey-text">No domain tracked yet: pick yours from the list below.</p>
        <table v-else class="data-table S">
          <thead>
            <tr><th class="grey-text dark-grey-border">Domain</th><th class="grey-text dark-grey-border">Expires</th><th class="grey-text dark-grey-border">Registrar&nbsp;&nbsp;·&nbsp;&nbsp;DNS</th><th class="grey-text dark-grey-border">Used by</th><th class="dark-grey-border"></th></tr>
          </thead>
          <tbody>
            <tr v-for="d in domains" :key="d.id">
              <td class="dark-grey-border">
                <strong class="white-text p">
                  <Globe width="0.9em" height="0.9em" aria-hidden="true" style="vertical-align: -0.1em" class="me-05" :class="expiryClass(d)"/>{{ d.name }}
                </strong>
                <span v-if="d.client_name" class="light-grey-text bold S ms-05"><br/>{{ d.client_name }}</span>
                <div v-if="d.notes" class="XS grey-text">{{ d.notes }}</div>
              </td>
              <td class="dark-grey-border">
                <template v-if="d.expires_on">
                  <span :class="expiryClass(d)">{{ formatDate(d.expires_on) }}</span>
                  <span class="S false-white-text">&nbsp;&nbsp;[{{ d.days_left }} days]</span>
                  <div class="XS light-grey-text">
                    {{ d.auto_renew ? 'renews automatically' : 'renewed by hand' }}<template v-if="d.expires_by_hand">&nbsp;&nbsp;·&nbsp;&nbsp;date typed</template>
                  </div>
                </template>
                <span v-else class="warning-text">unknown: enter it</span>
              </td>
              <td class="dark-grey-border">
                <template v-if="d.registrar_service_details">
                  <a v-if="d.registrar_service_details.url" :href="d.registrar_service_details.url" target="_blank"
                     rel="noopener noreferrer" :title="`The registry says: ${d.registrar || '–'}`" class="service-text underline">{{ d.registrar_service_details.name }}</a>
                  <span v-else :title="`The registry says: ${d.registrar || '–'}`">{{ d.registrar_service_details.name }}</span>
                  <span v-if="d.registrar_service_details.account" class="XS light-grey-text">&nbsp;&nbsp;·&nbsp;&nbsp;{{ d.registrar_service_details.account }}</span>
                </template>
                <template v-else>{{ d.registrar || '–' }}<span v-if="d.registrar" class="XS grey-text-text">&nbsp;&nbsp;·&nbsp;&nbsp;not linked</span></template>
                <div class="XS grey-text" :title="d.nameservers.join('\n')">
                  DNS: {{ d.dns_service_details?.name || d.dns_provider || d.nameservers[0] || '–' }}<template
                    v-if="d.dns_service_details?.account && d.dns_service_details.id !== d.registrar_service_details?.id">&nbsp;&nbsp;·&nbsp;&nbsp;{{ d.dns_service_details.account }}</template>
                </div>
                <div v-if="d.lookup_error && !d.expires_by_hand" class="XS warning-text">{{ d.lookup_error }}</div>
                <div v-else-if="d.looked_up_at" class="XS grey-text">checked {{ timeAgo(d.looked_up_at) }}</div>
              </td>
              <td class="dark-grey-border">
                <div v-for="p in d.project_details" :key="p.slug">
                  <RouterLink :to="{ name: 'project', params: { slug: p.slug } }" class="project-text underline">{{ p.name }}</RouterLink>
                  <span class="XS muted-text ms-05"> {{ d.sites.filter(s => s.project.slug === p.slug).map(s => s.host).join(', ') }}</span>
                </div>
                <span v-if="!d.project_details.length" class="muted-text">nothing in the catalog</span>
              </td>
              <td class="right nowrap dark-grey-border">
                <Button size="XS" invert :disabled="refreshing === d.id" @click="refresh(d)" :title="`Ask ${d.name}'s registry now`">↻</Button>
                <EditButton :label="`Edit ${d.name}`" class="ms-05" @click="editing = { domain: d }"/>
              </td>
            </tr>
          </tbody>
        </table>
      </Box>

      <Box :size="100" v-if="suggestions.length" class="wrap-anywhere">
        <h3>In the catalog’s URLs, not tracked</h3>
        <p class="S muted-text">Track the ones you own or renew; the others (a client’s own, a provider’s) can stay here.</p>
        <table class="data-table S">
          <tbody>
            <tr v-for="s in suggestions" :key="s.name">
              <td><strong>{{ s.name }}</strong><div class="XS muted-text">{{ s.hosts.join(', ') }}</div></td>
              <td>
                <span v-for="(p, i) in s.projects" :key="p.slug"><template v-if="i">, </template>
                  <RouterLink :to="{ name: 'project', params: { slug: p.slug } }">{{ p.name }}</RouterLink></span>
              </td>
              <td class="right"><Button size="XS" @click="editing = { name: s.name }" style="min-width: 80px;">+ Track</Button></td>
            </tr>
          </tbody>
        </table>
      </Box>
    </Boxes>

    <DomainForm :visible="!!editing" :domain="editing?.domain || null" :name="editing?.name || ''"
                @close="editing = null" @saved="saved"/>
  </Container>
</template>

<style scoped>
.nowrap {
  white-space: nowrap;
}
</style>
