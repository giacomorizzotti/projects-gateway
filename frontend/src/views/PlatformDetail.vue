<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Container from '@/mini/components/Container.vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import Space from '@/mini/components/Space.vue'
import LoadingBox from '@/mini/components/LoadingBox.vue'
import RichText from '@/mini/components/RichText.vue'
import Button from '@/mini/components/Button.vue'
import EditButton from '@/components/EditButton.vue'
import ProjectCard from '@/components/ProjectCard.vue'
import PlatformForm from '@/components/forms/PlatformForm.vue'
import LinkForm from '@/components/forms/LinkForm.vue'
import { api } from '@/api'
import { useCatalogStore } from '@/stores/catalog'
import { ipFamilies } from '@/utils/format'

const props = defineProps({ slug: { type: String, required: true } })

const router = useRouter()
const catalog = useCatalogStore()
catalog.load()

const platform = ref(null)
const error = ref('')

async function fetchPlatform(slug = props.slug) {
  try {
    platform.value = await api(`platforms/${slug}/`)
  } catch (e) {
    error.value = e.status === 404 ? 'This platform doesn’t exist.' : e.message
  }
}

watch(() => props.slug, (slug) => {
  platform.value = null
  error.value = ''
  fetchPlatform(slug)
}, { immediate: true })

// Which form is open: { type: 'platform' | 'link', item }.
const editing = ref(null)
const open = (type, item = null) => { editing.value = { type, item } }
const close = () => { editing.value = null }
const isOpen = type => editing.value?.type === type

function onSaved(saved) {
  close()
  if (saved?.slug && saved.slug !== props.slug) router.replace({ name: 'platform', params: { slug: saved.slug } })
  else fetchPlatform()
}

function onDeleted() {
  close()
  router.push({ name: 'platforms' })
}

// What this platform hosts ("if it goes down, what breaks?"): a card per project, as on the
// dashboard, with only its environments here. From the catalog, which has the whole projects.
// Archived and discontinued ones, and those in a hidden group, come last.
const HIDDEN_STATUSES = ['archived', 'discontinued']
const hosted = computed(() => {
  const hiddenGroups = new Set((catalog.choices?.project_groups || []).filter(g => g.hidden).map(g => g.value))
  const shelved = p => HIDDEN_STATUSES.includes(p.status) || hiddenGroups.has(p.group)
  return catalog.projects
    .map(project => ({ project, envs: project.environments.filter(e => e.platform_detail?.slug === props.slug) }))
    .filter(row => row.envs.length)
    .sort((a, b) => shelved(a.project) - shelved(b.project) || a.project.name.localeCompare(b.project.name))
})
</script>

<template>
  <Container>
    <Boxes spaceTopBot class="align-items-start">
      <Box :size="100">
        <RouterLink :to="{ name: 'platforms' }" class="S platform-text">← Platforms</RouterLink>
      </Box>
      <Box :size="100" v-if="error"><p class="danger-box">{{ error }}</p></Box>
      <Box :size="100" v-else-if="!platform"><LoadingBox/></Box>

      <template v-else>
        <Box :size="66">
          <h1 class="m-0">{{ platform.name }}</h1>
          <p class="m-0">
            <span class="platform-box XS me-05">{{ platform.kind_label }}</span>
            <span class="false-white-box XS">{{ [platform.provider, platform.location, platform.os].filter(Boolean).join('  ·  ') }}</span>
          </p>
          <p class="mt-1 mb-0">
            <Button color="warning" size="S" @click="open('platform', platform)">Edit platform</Button>
          </p>
          <div v-if="platform.notes" class="mt-1 false-black-bg white-text p-15">
            <RichText :text="platform.notes"/>
          </div>
          <div v-if="platform.cleanup_notes" class="mt-15 p-1 border warning-border b-rad-5">
            <h4 class="mb-05 warning-text">Cleanup</h4>
            <RichText :text="platform.cleanup_notes" class=" S"/>
          </div>
          <p class="mt-15 flex align-items-center flex-wrap">
            <span v-for="l in platform.links" :key="l.id" class="me-1 flex align-items-center flex-nowrap pe-1">
              <a :href="l.url" target="_blank" rel="noopener noreferrer" class="btn m-0">{{ l.label }}</a>
              <EditButton :label="`Edit link ${l.label}`" @click="open('link', l)"/>
            </span>
            <Button size="S" invert @click="open('link')" class="m-0">+ Add link</Button>
          </p>
        </Box>
        <Box :size="33">
          <table class="data-table S wrap-anywhere">
            <tbody>
              <tr v-if="platform.dynamic_dns"><th style="vertical-align: middle;">Dynamic DNS</th><td><code class="black-bg">{{ platform.dynamic_dns }}</code></td></tr>
              <tr v-for="f in ipFamilies(platform.public_ips)" :key="f.label"><th style="vertical-align: middle;">Public {{ f.label }}</th><td><code v-for="ip in f.ips" :key="ip" class="me-05 mb-0 black-bg">{{ ip }}</code></td></tr>
              <tr v-if="platform.hostnames.length"><th style="vertical-align: middle;">Hostnames</th><td><code v-for="ip in platform.hostnames" :key="ip" class="me-05 mb-0 black-bg">{{ ip }}</code></td></tr>
            </tbody>
          </table>
        </Box>

        <Box :size="100">
          <h3 class="m-0">Hosted here <span class="flag regular light-grey-border b-rad-3">{{ hosted.length }} projects</span></h3>
          <p v-if="!hosted.length" class="light-grey-text">Nothing recorded on this platform.</p>
        </Box>
        <Box :size="100" class="p-y">
          <Boxes gap="2">
            <Box v-for="row in hosted" :key="row.project.slug" :size="33" padding="0">
              <ProjectCard :project="row.project" :environments="row.envs" :showPlatform="false"/>
            </Box>
          </Boxes>
        </Box>
      </template>
    </Boxes>

    <template v-if="platform">
      <PlatformForm :visible="isOpen('platform')" :platform="platform"
                    @close="close" @saved="onSaved" @deleted="onDeleted"/>
      <LinkForm :visible="isOpen('link')" :owner="{ platform: platform.id }" :ownerName="platform.name"
                :link="isOpen('link') ? editing.item : null" @close="close" @saved="onSaved"/>
    </template>
  </Container>
</template>

<style lang="scss" scoped>
  table tbody tr th, table tbody tr td{
    color: var(--white);
    background-color: var(--false-black);
    border-bottom: 2px solid var(--black);
    padding: var(--padding);
  }
</style>