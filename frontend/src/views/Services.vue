<script setup>
// The web services the projects use (Iubenda, Paddle, an SMTP account…): what each is for,
// which account it's under, and which projects and domains use it (as registrar or DNS).
// A card each, grouped by kind, as the dashboard's projects.
import { computed, onMounted, ref } from 'vue'
import { Cloud } from '@iconoir/vue'
import Container from '@/mini/components/Container.vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import Button from '@/mini/components/Button.vue'
import LoadingBox from '@/mini/components/LoadingBox.vue'
import EditButton from '@/components/EditButton.vue'
import ServiceForm from '@/components/forms/ServiceForm.vue'
import { useCatalogStore } from '@/stores/catalog'
import CatalogCounts from '@/components/CatalogCounts.vue'
import { hostOf } from '@/utils/format'

const catalog = useCatalogStore()
onMounted(() => catalog.load())

const groups = computed(() => {
  const byKind = {}
  for (const s of catalog.services) (byKind[s.kind || 'Other'] ||= []).push(s)
  return Object.entries(byKind)
    .sort(([a], [b]) => (a === 'Other') - (b === 'Other') || a.localeCompare(b))
    .map(([kind, services]) => ({ kind, services: services.sort((a, b) => a.name.localeCompare(b.name)) }))
})

// The domains each service registers or hosts the DNS of: { [service id]: { registrar: [...], dns: [...] } }.
const domainsOf = computed(() => {
  const out = {}
  for (const d of [...catalog.domains].sort((a, b) => a.name.localeCompare(b.name))) {
    if (d.registrar_service) (out[d.registrar_service] ||= { registrar: [], dns: [] }).registrar.push(d.name)
    if (d.dns_service) (out[d.dns_service] ||= { registrar: [], dns: [] }).dns.push(d.name)
  }
  return out
})

// null = closed; { service } to edit, {} for a new one.
const editing = ref(null)
</script>

<template>
  <Container>
    <Boxes spaceTop>
      <Box :size="100">
        <h1 class="mb-0">Services</h1>
        <p class="light-grey-text mt-0">
          The web services the projects use: GDPR and cookies, payments, email, analytics… What each is for, the account it’s under, and who uses it.
          Never passwords: those stay in the password manager.
        </p>
        <CatalogCounts class="mt-05 mb-15"/>
        <p class="m-0">
          <Button size="S" class="service-btn" :disabled="!catalog.choices" @click="editing = {}" hard>+ New service</Button>
        </p>
      </Box>

      <Box :size="100" v-if="catalog.loading && !catalog.choices"><LoadingBox dark/></Box>
      <Box :size="100" v-else-if="catalog.error"><p class="danger-box">{{ catalog.error }}</p></Box>

      <Box :size="100" v-else-if="!groups.length"><p class="muted-text m-0">No service yet.</p></Box>
    </Boxes>

    <Boxes>
      <!-- One section per kind, a card per service: the dashboard's layout. -->
      <Box size="100" v-for="g in (catalog.error ? [] : groups)" :key="g.kind" class="mb-1">
        <Boxes class="align-items-start" gap="2">
          <Box :size="100" padding="0">
            <h3 class="p light m-0 grey-text">{{ g.kind }} <span class="flag border-0 service-text">{{ g.services.length }}</span></h3>
          </Box>
          <Box v-for="s in g.services" :key="s.id" :size="33" padding="0">
            <div class="service-card p-15 service-border wrap-anywhere fb-bg" style="border-top: 3px solid;">
              <div class="flex justify-content-between align-items-start">
                <h4 class="m-0 service-text">
                  <Cloud width="0.9em" height="0.9em" aria-hidden="true" style="vertical-align: -0.1em" class="me-1 service-text"/>
                  <a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer" class="service-text underline">{{ s.name }}</a>
                  <template v-else>{{ s.name }}</template>
                </h4>
                <EditButton :label="`Edit ${s.name}`" class="ms-05" @click="editing = { service: s }"/>
              </div>
              <p v-if="s.url" class="XS light-grey-text mt-0 mb-05">{{ hostOf(s.url) }}</p>
              <p v-if="s.notes" class="S false-white-text mt-0 mb-075" style="white-space: pre-line;">{{ s.notes }}</p>
              <p v-if="s.account" class="S m-0"><span class="muted-text">Account:</span> {{ s.account || '–' }}</p>
              <p v-if="s.project_details.length" class="S m-0">
                <span class="grey-text">Used by: </span>
                <span v-for="(p, i) in s.project_details" :key="p.slug"><template v-if="i">, </template>
                  <RouterLink :to="{ name: 'project', params: { slug: p.slug } }" class="project-text">{{ p.name }}</RouterLink></span>
              </p>
              <p v-else-if="!domainsOf[s.id]" class="grey-text S m-0">No project uses it.</p>
              <p v-if="domainsOf[s.id]?.registrar.length" class="mt-025 lh-15 XS">
                <span class="grey-text">Registrar of</span> {{ domainsOf[s.id].registrar.join(', ') }}
              </p>
              <p v-if="domainsOf[s.id]?.dns.length" class="light-grey-text S m-0">
                <span class="grey-text">DNS of</span> {{ domainsOf[s.id].dns.join(', ') }}
              </p>
            </div>
          </Box>
        </Boxes>
      </Box>
    </Boxes>

    <ServiceForm :visible="!!editing" :service="editing?.service || null" @close="editing = null" @saved="editing = null"/>
  </Container>
</template>

<style scoped>
/* The cards of a row as tall as the tallest. */
.service-card {
  height: 100%;
}
</style>
