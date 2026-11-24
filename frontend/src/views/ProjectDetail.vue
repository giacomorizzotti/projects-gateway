<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Folder, Repository } from '@iconoir/vue'
import Container from '@/mini/components/Container.vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import Button from '@/mini/components/Button.vue'
import LoadingBox from '@/mini/components/LoadingBox.vue'
import MarkdownText from '@/mini/components/MarkdownText.vue'
import EditButton from '@/components/EditButton.vue'
import ProjectForm from '@/components/forms/ProjectForm.vue'
import EnvironmentForm from '@/components/forms/EnvironmentForm.vue'
import DependencyForm from '@/components/forms/DependencyForm.vue'
import LinkForm from '@/components/forms/LinkForm.vue'
import { api } from '@/api'
import { useCatalogStore } from '@/stores/catalog'
import { dependencyHow, dependencyUpdate, envClass, formatDate, statusBoxClass, envBorderColor } from '@/utils/format'
import { expiryClass } from '@/utils/domains'

const props = defineProps({ slug: { type: String, required: true } })

const router = useRouter()
const catalog = useCatalogStore()
catalog.load()

// The domains I own that this project uses (its URLs, or linked by hand).
const projectDomains = computed(() =>
  catalog.domains.filter(d => d.project_details.some(p => p.slug === props.slug)))

const project = ref(null)
const error = ref('')

async function fetchProject(slug = props.slug) {
  try {
    project.value = await api(`projects/${slug}/`)
  } catch (e) {
    error.value = e.status === 404 ? 'This project doesn’t exist.' : e.message
  }
}

watch(() => props.slug, (slug) => {
  project.value = null
  error.value = ''
  fetchProject(slug)
}, { immediate: true })

// "Used by", grouped by how they include this project (all the CDN @main ones together…).
const dependentsSorted = computed(() => [...(project.value?.dependents || [])].sort((a, b) =>
  (a.via_label || '~').localeCompare(b.via_label || '~') || (a.version || '').localeCompare(b.version || '')
  || a.project_detail.name.localeCompare(b.project_detail.name)))

// Which form is open: { type: 'project' | 'environment' | 'dependency' | 'link', item }.
const editing = ref(null)
const open = (type, item = null) => { editing.value = { type, item } }
const close = () => { editing.value = null }
const isOpen = type => editing.value?.type === type
// Each form only ever gets its own kind of item (or null for "new").
const itemFor = type => (isOpen(type) ? editing.value.item : null)

function onProjectSaved(saved) {
  close()
  if (saved.slug !== props.slug) router.replace({ name: 'project', params: { slug: saved.slug } })
  else fetchProject()
}

function onProjectDeleted() {
  close()
  router.push({ name: 'dashboard' })
}

function onChildSaved() {
  close()
  fetchProject()
}
</script>

<template>
  <Container>
    <Boxes spaceTop>
      <Box :size="100">
        <RouterLink :to="{ name: 'dashboard' }"><span class="project-text">← Projects</span></RouterLink>
      </Box>
      <Box :size="100" v-if="error"><p class="danger-box">{{ error }}</p></Box>
      <Box :size="100" v-else-if="!project"><LoadingBox/></Box>
      <Box :size="100" padding="0" v-else>
        <Boxes spaceBot>
          <Box :size="100">
            <h1 class="m-0 giant">{{ project.name }}</h1>
            <p v-if="project.client_name" class="mt-0 mb-1 light-grey-text bold">{{ project.client_name }}</p>
            <p class="mt-0 mb-1 ">
              <span class="dark-grey-box XS me-05">{{ project.group_label }}</span>
              <span :class="[statusBoxClass(project.status) || 'success-box', 'XS me-05']">{{ project.status_label }}</span>
            </p>
            <p v-if="project.description" class="L mt-0 mb-15">{{ project.description }}</p>
            <div v-if="project.notes" class="dark-grey-bg p-15 mb-2">
              <MarkdownText :text="project.notes" :markdown="project.notes_markdown" class=""/>
            </div>
            <p class="m-0">
              <Button color="warning" size="" @click="open('project', project)" class="m-0" hard>Edit project</Button>
            </p>
          </Box>

          <Box :size="66">
            <h3 class="flex flex-wrap align-items-center">
              Environments
              <Button size="S" invert class="m-0 ms-1" @click="open('environment')">+ Add</Button>
            </h3>
            <p v-if="!project.environments.length" class="muted-text">No environments.</p>
            <Boxes gap="2">          <!-- A card per environment, bordered in its kind's colour: the dashboard's layout. -->
              <Box v-for="env in project.environments" :key="env.id" :size="50" padding="0">
                <div :class="['environment-card p-15 border dark-grey-border fb-bg wrap-anywhere S']">
                  <div class="flex justify-content-between align-items-start mb-1">
                    <div>
                      <span :class="[envClass(env.kind), 'XS me-05']">{{ env.kind === 'other' ? env.name : env.kind_label }}</span>
                      <span v-if="!env.checks_enabled" class="danger-box XS me-05">no health checks</span>
                      <p v-if="env.kind !== 'other' && env.name !== env.kind_label" class="muted-text m-0 mt-025">{{ env.name }}</p>
                    </div>
                    <EditButton :label="`Edit ${env.name}`" class="ms-05" @click="open('environment', env)"/>
                  </div>
                  <p v-if="env.urls.length" class="lh-15 L">
                    <template v-for="(url, i) in env.urls" :key="url"><br v-if="i"/>
                      <a :href="url" target="_blank" rel="noopener noreferrer">{{ url }}</a>
                    </template>
                  </p>
                  <p v-if="env.path" class=" lh-15"><code class="XS bk-bg">{{ env.path }}</code></p>
                  <p v-if="env.notes" class="dark-grey-bg p-1 lh-15">{{ env.notes }}</p>
                  <p v-if="env.platform_detail" class="m-0 mt-1 lh-15">
                    <span class="grey-text XS">Platform:</span><br/>
                    <RouterLink :to="{ name: 'platform', params: { slug: env.platform_detail.slug } }" class="underline platform-text">
                      {{ env.platform_detail.name }}
                    </RouterLink>
                  </p>
                  <p v-if="env.runtime || env.deploy" class="m-0 mt-1 lh-15">
                    <span class="grey-text XS">Runtime &amp; deploy:</span>
                    <template v-if="env.runtime"><br/>{{ env.runtime }}</template>
                    <template v-if="env.deploy"><br/><span class="light-grey-text">{{ env.deploy }}</span></template>
                  </p>
                </div>
              </Box>
            </Boxes>
          </Box>


          <Box :size="33">
            <h3 class=""><RouterLink :to="{ name: 'repositories' }" class="white-text underline">Repositories</RouterLink></h3>
            <p v-if="!project.repositories.length" class="muted-text">No repository. Link one with “Edit project”.</p>
            <Boxes v-else class="env-list wrap-anywhere">
              <Box size="100" v-for="repo in project.repositories" :key="repo.id" class="fb-bg p-15 repository-border" style="border-top: 3px solid;">
                <RouterLink :to="{ name: 'repositories' }" class="bold repository-text">
                  <Repository width="0.9em" height="0.9em" aria-hidden="true" style="vertical-align: -0.1em" class="me-05"/>{{ repo.name }}
                </RouterLink>
                <span class="flag repository-bg b-rad-3 white-text XS ms-05">{{ repo.hosting }}</span>
                <span v-if="repo.archived" class="flag light-grey-bg border-0 b-rad-3 p-05 ms-05">archived</span>
                <div class="S">
                  <a v-if="repo.github_url" :href="repo.github_url" target="_blank" rel="noopener noreferrer" class="repository-text">{{ repo.github_url }}</a>
                  <code v-else-if="repo.remote_url">{{ repo.remote_url }}</code>
                </div>
              </Box>
            </Boxes>
          </Box>

          <Box :size="66" v-if="projectDomains.length">
            <h3>Domains</h3>
            <ul class="env-list wrap-anywhere">
              <li v-for="d in projectDomains" :key="d.id" class="mt-0 mb-05">
                <RouterLink :to="{ name: 'domains' }" class="bold">{{ d.name }}</RouterLink>
                <span class="S">
                  ·
                  <template v-if="d.expires_on">
                    expires <span :class="expiryClass(d)">{{ formatDate(d.expires_on) }}</span>
                    <span class="muted-text">({{ d.auto_renew ? 'renews automatically' : 'renewed by hand' }})</span>
                  </template>
                  <span v-else class="warning-text">expiry unknown</span>
                  <span v-if="d.registrar_service_details || d.registrar" class="muted-text">&nbsp;&nbsp;·&nbsp;&nbsp;{{ d.registrar_service_details?.name || d.registrar }}</span>
                </span>
              </li>
            </ul>
          </Box>

          <Box :size="33">
            <h3 class=""><RouterLink :to="{ name: 'services' }" class="white-text underline">Services</RouterLink></h3>
            <ul v-if="project.services.length" class="env-list">
              <li v-for="s in project.services" :key="s.id">
                <a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer">{{ s.name }}</a>
                <span v-else>{{ s.name }}</span>
                <span v-if="s.kind" class="muted-text S">&nbsp;&nbsp;·&nbsp;&nbsp;{{ s.kind }}</span>
              </li>
            </ul>
            <p v-else class="italic light-grey-text">No services</p>
          </Box>

          <Box :size="100">
            <h3 class="flex flex-wrap align-items-center">
              Links
              <Button size="S" invert class="ms-05" @click="open('link')">+ Add</Button>
            </h3>
            <p v-if="!project.links.length" class="muted-text">None.</p>
            <p v-else>
              <span v-for="l in project.links" :key="l.id" class="fw-bg me-1 flex align-items-center flex-nowrap pe-1">
                <a :href="l.url" target="_blank" rel="noopener noreferrer" class="btn m-0">{{ l.label }}</a>
                <EditButton :label="`Edit link ${l.label}`" @click="open('link', l)"/>
              </span>
            </p>
          </Box>

          <Box :size="50">
            <h3 class="flex flex-wrap align-items-center">
              <RouterLink :to="{ name: 'dashboard' }" class="white-text underline">Depends on</RouterLink>
              
              <Button size="S" invert class="ms-05" @click="open('dependency')">+ Add</Button>
            </h3>
            <p v-if="!project.dependencies.length" class="muted-text">Nothing.</p>
            <!-- A box per dependency, like the repositories beside it. -->
            <Boxes v-else class="wrap-anywhere" gap="2">
              <Box :size="100" v-for="d in project.dependencies" :key="d.id" class="fb-bg p-15 project-border" style="border-top: 3px solid;">
                <div class="flex justify-content-between align-items-start">
                  <RouterLink :to="{ name: 'project', params: { slug: d.depends_on_detail.slug } }" class="bold project-text">
                    <Folder width="0.9em" height="0.9em" aria-hidden="true" style="vertical-align: -0.1em" class="me-05"/>{{ d.depends_on_detail.name }}
                  </RouterLink>
                  <EditButton :label="`Edit dependency on ${d.depends_on_detail.name}`" class="ms-05" @click="open('dependency', d)"/>
                </div>
                <p class="S m-0 mt-05">
                  <span class="muted-text">{{ d.kind_label }}</span>
                  <template v-if="dependencyHow(d)">&nbsp;&nbsp;·&nbsp;&nbsp;{{ dependencyHow(d) }}</template>
                  <span v-if="dependencyUpdate(d)" :class="[dependencyUpdate(d).cls, 'flag border-0 ms-1']" :title="dependencyUpdate(d).title">{{ dependencyUpdate(d).label }}</span>
                </p>
                <p v-if="d.reference" class="m-0 mt-05"><code class="XS black-bg">{{ d.reference }}</code></p>
                <p v-if="d.notes" class="muted-text XS m-0 mt-05">{{ d.notes }}</p>
              </Box>
            </Boxes>
          </Box>

          <Box :size="50">
            <h3 class="">Used by</h3>
            <p v-if="!project.dependents.length" class="muted-text">Nothing.</p>
            <ul v-else class="env-list wrap-anywhere">
              <li v-for="d in dependentsSorted" :key="d.id" class="mt-0 mb-15 ps-15 project-border" style="border-left: 3px solid;">
                <RouterLink :to="{ name: 'project', params: { slug: d.project_detail.slug } }" class="project-text bold">
                  <Folder width="0.9em" height="0.9em" aria-hidden="true" style="vertical-align: -0.1em" class="me-05"/>{{ d.project_detail.name }}
                </RouterLink><br/>
                <span class="light-grey-text S">{{ dependencyHow(d) || d.kind_label }}</span>
                <span v-if="dependencyUpdate(d)" :class="[dependencyUpdate(d).cls, 'flag border-0 ms-1']" :title="dependencyUpdate(d).title">{{ dependencyUpdate(d).label }}</span>
                <div v-if="d.notes" class="muted-text XS">{{ d.notes }}</div>
              </li>
            </ul>
          </Box>

          <Box :size="33">
            <h3 class="">Technologies</h3>
            <p v-if="!project.technology_names.length" class="muted-text">None recorded.</p>
            <p v-else>
              <span v-for="t in project.technology_names" :key="t" class="technology-box S me-05">{{ t }}</span>
            </p>
          </Box>

        </Boxes>
      </Box>
    </Boxes>

    <template v-if="project">
      <ProjectForm :visible="isOpen('project')" :project="project"
                   @close="close" @saved="onProjectSaved" @deleted="onProjectDeleted"/>
      <EnvironmentForm :visible="isOpen('environment')" :project="project" :environment="itemFor('environment')"
                       @close="close" @saved="onChildSaved"/>
      <DependencyForm :visible="isOpen('dependency')" :project="project" :dependency="itemFor('dependency')"
                      @close="close" @saved="onChildSaved"/>
      <LinkForm :visible="isOpen('link')" :owner="{ project: project.id }" :ownerName="project.name" :link="itemFor('link')"
                @close="close" @saved="onChildSaved"/>
    </template>
  </Container>
</template>
