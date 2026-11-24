<script setup>
// The backup planner: every job (what, when, where to), its last run and its copies, the
// agents that run them and the targets' free space. Re-read every minute while open.
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Server } from '@iconoir/vue'
import Container from '@/mini/components/Container.vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import Space from '@/mini/components/Space.vue'
import Button from '@/mini/components/Button.vue'
import LoadingBox from '@/mini/components/LoadingBox.vue'
import EditButton from '@/components/EditButton.vue'
import BackupJobForm from '@/components/forms/BackupJobForm.vue'
import BackupTargetForm from '@/components/forms/BackupTargetForm.vue'
import { api } from '@/api'
import { useCatalogStore } from '@/stores/catalog'
import { formatDateTime } from '@/utils/format'
import { SEVERITY_BOX, timeAgo } from '@/utils/status'

const catalog = useCatalogStore()
const data = ref(null)
const error = ref('')

async function load() {
  try {
    data.value = await api('backups/')
    error.value = ''
  } catch (e) {
    error.value = e.message || 'Could not load the backups.'
  }
}

let timer = null
onMounted(() => {
  catalog.load()
  load()
  timer = setInterval(load, 60_000)
})
onUnmounted(() => clearInterval(timer))

// Flags as on the project and platform pages: a coloured background, no border.
const FLAG = 'text-box border-0 XS'
const STATUS_FLAG = { ok: 'success-bg', partial: 'warning-bg', failed: 'danger-bg' }

// A job row's left border, like the environments' rows: its state at a glance.
function jobBorder(job) {
  if (job.problem) return job.problem.severity === 'danger' ? 'danger-border' : 'warning-border'
  return job.last_run ? 'success-border' : 'light-grey-border'
}
const targetsById = computed(() => Object.fromEntries((data.value?.targets || []).map(t => [t.id, t])))

// Jobs by platform, scheduled ones first.
const groups = computed(() => {
  const out = {}
  for (const job of data.value?.jobs || []) {
    const key = job.platform_detail.slug
    ;(out[key] ||= { platform: job.platform_detail, jobs: [] }).jobs.push(job)
  }
  for (const g of Object.values(out)) g.jobs.sort((a, b) => (b.enabled - a.enabled) || a.name.localeCompare(b.name))
  return Object.values(out)
})

function agentFor(slug) {
  return data.value?.agents.find(a => a.platform.slug === slug)
}

function size(bytes) {
  if (bytes == null) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++ }
  return `${bytes.toFixed(i ? 1 : 0)} ${units[i]}`
}

function schedule(job) {
  return `${job.frequency_label.replace(/ \(.*\)/, '').toLowerCase()} at ${String(job.hour).padStart(2, '0')}:00`
}

// Asked with "Back up now": the agent takes it at its next check-in (every 15 minutes).
const asking = ref(null)
async function backUpNow(job) {
  asking.value = job.id
  try {
    await api(`backup-jobs/${job.id}/run/`, { method: 'POST' })
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    asking.value = null
  }
}

// null = closed, {} = new, a row = editing it.
const editingJob = ref(null)
const editingTarget = ref(null)
function saved() {
  editingJob.value = null
  editingTarget.value = null
  load()
}
</script>

<template>
  <Container>
    <Boxes>
      <Box :size="100">
        <h1 class="m-0">Backups</h1>
        <p class="light-grey-text mt-0">
          What is backed up, when and where to. An agent on each platform runs its jobs (from its crontab, every 15 minutes):
          each backup is made in its first target, checked, then copied to the others.
        </p>
        <Space/>
        <p class="m-0">
          <Button size="S" class="backup-btn" :disabled="!data" @click="editingJob = {}" hard>+ New job</Button>
          <Button size="S" invert :disabled="!data" @click="editingTarget = {}" class="backup-btn ms-05" hard>+ New target</Button>
        </p>
      </Box>

      <Box :size="100" v-if="!data && !error"><LoadingBox dark/></Box>
      <Box :size="100" v-if="error"><p class="danger-box">{{ error }}</p></Box>

      <template v-if="data">
        <Box :size="100" v-for="g in groups" :key="g.platform.slug" class="wrap-anywhere">
          <h3 class="mb-0">
            <RouterLink :to="{ name: 'platform', params: { slug: g.platform.slug } }" class="platform-text">
              <Server width="0.9em" height="0.9em" aria-hidden="true" style="vertical-align: -0.1em" class="me-05"/>{{ g.platform.name }}
            </RouterLink>
          </h3>
          <p class="S m-0" v-if="agentFor(g.platform.slug)">
            <span :class="agentFor(g.platform.slug).silent ? 'danger-text' : 'muted-text'">
              Agent {{ agentFor(g.platform.slug).version }}: last check-in {{ timeAgo(agentFor(g.platform.slug).last_seen_at) }}.
            </span>
          </p>
          <p class="S muted-text m-0" v-else>No agent has checked in from here yet.</p>
          <table class="data-table S mt-05">
            <thead>
              <tr><th>Job</th><th>When</th><th>Last run</th><th>Copies</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="job in g.jobs" :key="job.id" :class="jobBorder(job)" style="border-left: 2px solid;">
                <td class="ps-1">
                  <strong>{{ job.name }}</strong>
                  <RouterLink v-if="job.project_detail" :to="{ name: 'project', params: { slug: job.project_detail.slug } }" class="ms-05">
                    {{ job.project_detail.name }}</RouterLink><span v-if="job.environment_name" class="muted-text">&nbsp;&nbsp;·&nbsp;&nbsp;{{ job.environment_name }}</span>
                  <div class="XS muted-text">{{ job.kind_label }}: <code class="XS my-05">{{ job.source }}</code></div>
                  <div v-if="job.problem" :class="[SEVERITY_BOX[job.problem.severity], 'XS mt-025']">{{ job.problem.text }}</div>
                </td>
                <td>
                  <template v-if="job.enabled">
                    {{ schedule(job) }}
                    <div class="XS muted-text" v-if="job.next_at">next {{ formatDateTime(job.next_at) }}</div>
                  </template>
                  <span v-else :class="[FLAG, 'light-grey-bg']">not scheduled</span>
                </td>
                <td>
                  <template v-if="job.last_run">
                    <span :class="[FLAG, STATUS_FLAG[job.last_run.status]]">{{ job.last_run.status_label }}</span>
                    <div class="XS">{{ formatDateTime(job.last_run.started_at) }}&nbsp;&nbsp;·&nbsp;&nbsp;{{ size(job.last_run.size) }}</div>
                    <div v-if="job.last_ok_at && job.last_run.status !== 'ok'" class="XS muted-text">last good {{ formatDateTime(job.last_ok_at) }}</div>
                  </template>
                  <span v-else class="muted-text">never</span>
                </td>
                <td>
                  <div v-for="t in job.targets" :key="t.id" class="XS">
                    {{ t.name }}<template v-if="job.usage[t.id]">: {{ job.usage[t.id].count }}&nbsp;&nbsp;·&nbsp;&nbsp;{{ size(job.usage[t.id].bytes) }}</template>
                  </div>
                </td>
                <td class="right nowrap">
                  <span v-if="job.waiting" class="XS info-box">asked, waiting for the agent</span>
                  <Button v-else size="XS" class="m-0 me-05" invert :disabled="asking === job.id" @click="backUpNow(job)" hard>Back up now</Button>
                  <EditButton :label="`Edit ${job.name}`" @click="editingJob = job"/>
                </td>
              </tr>
            </tbody>
          </table>
        </Box>
        <Box :size="100" v-if="!groups.length">
          <p class="muted-text">No backup job yet.</p>
        </Box>

        <Box :size="100" class="wrap-anywhere">
          <h3>Targets</h3>
          <table class="data-table S">
            <thead>
              <tr><th>Target</th><th>Folder</th><th>Where</th><th>Keeps</th><th>Free</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="t in data.targets" :key="t.id">
                <td>
                  <strong>{{ t.name }}</strong> ·
                  <RouterLink :to="{ name: 'platform', params: { slug: t.platform_detail.slug } }" class="platform-text">{{ t.platform_detail.name }}</RouterLink>
                </td>
                <td><code class="XS">{{ t.path }}</code><div v-if="t.mount" class="XS muted-text">must be mounted: {{ t.mount }}</div></td>
                <td>{{ t.location_label }}</td>
                <td>{{ t.keep ? `the newest ${t.keep}` : 'everything' }}</td>
                <td>
                  <span v-if="t.disk?.error" class="warning-text">{{ t.disk.error }}</span>
                  <template v-else-if="t.disk?.total">{{ size(t.disk.free) }} of {{ size(t.disk.total) }}</template>
                  <span v-else class="muted-text">not reported yet</span>
                </td>
                <td class="right"><EditButton :label="`Edit ${t.name}`" @click="editingTarget = t"/></td>
              </tr>
            </tbody>
          </table>
        </Box>

        <Box :size="100" class="wrap-anywhere">
          <h3>Recent runs</h3>
          <p v-if="!data.runs.length" class="muted-text">None yet.</p>
          <table v-else class="data-table S">
            <tbody>
              <tr v-for="r in data.runs" :key="r.id">
                <td class="nowrap">{{ formatDateTime(r.started_at) }}</td>
                <td><span :class="[FLAG, STATUS_FLAG[r.status]]">{{ r.status }}</span></td>
                <td>
                  {{ r.job_name }}<span v-if="r.requested" class="muted-text">&nbsp;&nbsp;·&nbsp;&nbsp;asked</span>
                  <div v-if="r.error" class="XS danger-text">{{ r.error }}</div>
                  <div v-for="f in r.files.filter(f => !f.ok)" :key="f.path" class="XS warning-text">{{ f.error }}: {{ f.path }}</div>
                </td>
                <td class="right">{{ size(r.size) }}</td>
              </tr>
            </tbody>
          </table>
        </Box>
      </template>
    </Boxes>

    <BackupJobForm :visible="!!editingJob" :job="editingJob?.id ? editingJob : null" :targets="data?.targets || []"
                   :choices="data?.choices || {}" :defaultExcludes="data?.default_excludes || []"
                   @close="editingJob = null" @saved="saved"/>
    <BackupTargetForm :visible="!!editingTarget" :target="editingTarget?.id ? editingTarget : null"
                      :locations="data?.choices.locations || []" @close="editingTarget = null" @saved="saved"/>
  </Container>
</template>

<style scoped>
.nowrap {
  white-space: nowrap;
}
table thead tr th {
  color: var(--grey);
}
table thead tr th, table tbody tr td, .attention-list li {
  color: var(--white);
  background-color: var(--false-black);
  border-bottom: 2px solid var(--black);
  padding: var(--padding);
}
</style>
