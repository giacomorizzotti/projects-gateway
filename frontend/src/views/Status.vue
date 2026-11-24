<script setup>
// Live status: what needs attention, every checked URL, the last 30 days of outages.
// Re-read every minute while the page is open.
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Repository } from '@iconoir/vue'
import Container from '@/mini/components/Container.vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import Space from '@/mini/components/Space.vue'
import Button from '@/mini/components/Button.vue'
import LoadingBox from '@/mini/components/LoadingBox.vue'
import Tabs from '@/mini/components/Tabs.vue'
import { usePersistedRef } from '@/mini/composables/usePersistedRef'
import StatusDot from '@/components/StatusDot.vue'
import { useStatusStore } from '@/stores/status'
import { formatDate, formatDateTime, hostOf, ipFamilies } from '@/utils/format'
import { KIND_LABEL, SEVERITY_BOX, SEVERITY_FLAG, checkWarnings, daysLeft, duration, shortPath, timeAgo } from '@/utils/status'

const status = useStatusStore()
let timer = null
onMounted(() => {
  status.load({ force: true })
  timer = setInterval(() => status.load({ force: true }), 60_000)
})
onUnmounted(() => clearInterval(timer))

const monitor = computed(() => status.data?.monitor)
const checks = computed(() => status.data?.checks || [])

const filter = usePersistedRef('gateway.status.filter', 'all')     // all | down | warnings
const downChecks = computed(() => checks.value.filter(c => c.state === 'down'))
const warnedChecks = computed(() => checks.value.filter(c => checkWarnings(c).length))
const FILTERS = computed(() => [
  { value: 'all', label: `All (${checks.value.length})` },
  { value: 'down', label: `Down (${downChecks.value.length})` },
  { value: 'warnings', label: `Warnings (${warnedChecks.value.length})` },
])
const shownChecks = computed(() =>
  filter.value === 'down' ? downChecks.value : filter.value === 'warnings' ? warnedChecks.value : checks.value)

// Newest first. A "came back up" gets how long it was down, from the "down" before it.
const events = computed(() => {
  const list = status.data?.events || []
  return list.map((e, i) => {
    if (e.state !== 'up') return e
    const before = list.slice(i + 1).find(o => o.environment === e.environment && o.url === e.url)
    return before?.state === 'down' ? { ...e, lasted: duration(before.at, e.at) } : e
  })
})

// An item's link in the colour of what it opens (itemLink below): its project, its platform,
// or the page it points to. Items carry only project, platform and page; their kind "service"
// is a failed systemd unit, not one of the catalog's services.
const PAGE_CLASS = {
  platforms: 'platform-text',
  repositories: 'repository-text',
  services: 'service-text',
  domains: 'domain-text',
  backups: 'backup-text',
}
function itemLinkClass(item) {
  if (item.project) return 'project-text'
  if (item.platform) return 'platform-text'
  return PAGE_CLASS[item.page] || ''
}

function itemLink(item) {
  if (item.project) return { name: 'project', params: { slug: item.project.slug } }
  if (item.platform) return { name: 'platform', params: { slug: item.platform.slug } }
  if (item.page && item.page !== 'status') return { name: item.page }
  return null
}

function certificate(c) {
  if (c.tls_expires_at) return { text: formatDate(c.tls_expires_at), soon: daysLeft(c.tls_expires_at) < 21 }
  return { text: c.tls_error || (c.url.startsWith('https') ? '' : 'no TLS'), soon: !!c.tls_error }
}

const checkError = ref('')
async function checkNow() {
  checkError.value = await status.checkNow()
}

const CHANNEL = { telegram: 'Telegram', email: 'email' }
const channels = computed(() => (monitor.value?.notify_channels || []).map(c => CHANNEL[c] || c).join(' and '))

// The host's git repos, nginx sites, services and maldet's scans (deploy/scan_local.py, every 15 minutes).
const scan = computed(() => status.data?.local)
const maldet = computed(() => scan.value?.maldet)
const localTab = usePersistedRef('gateway.status.localTab', 'repos')     // repos | nginx | services | malware
const LOCAL_TABS = computed(() => [
  { value: 'repos', label: `Repos (${scan.value?.repos.length ?? 0})` },
  { value: 'nginx', label: `nginx (${scan.value?.nginx.length ?? 0})` },
  { value: 'services', label: `Services (${scan.value?.failed_units.length ?? 0} failed)` },
  ...(maldet.value ? [{ value: 'malware', label: `Malware (${maldet.value.open_hits.length} flagged)` }] : []),
])

function nameState(n) {
  if (!n.ips?.length) return { text: 'doesn’t resolve', cls: 'grey-text' }
  if (n.here === false) {
    const where = ipFamilies(n.ips).map(f => `${f.label} ${f.ips.join(', ')}`).join('&nbsp;&nbsp;·&nbsp;&nbsp;')
    return { text: `points elsewhere (${where})`, cls: 'warning-text' }
  }
  return null
}
</script>

<template>
  <Container>
    <Boxes spaceBot>
      <Box :size="100">
        <h1 class="m-0">Status</h1>
        <p class="light-grey-text m-0">
          Every public URL, checked from the gateway every {{ monitor?.every_minutes ?? 15 }} minutes.
          A site is down only if it still fails 5 minutes later, while other sites answer.
        </p>
        <p v-if="monitor?.checks_ran_at" class="m-0 grey-text">
          Last check {{ timeAgo(monitor.checks_ran_at) }}: {{ monitor.checks_count }} URLs in {{ monitor.checks_seconds }} s.
        </p>
        <Space/>
        <p class="m-0 S" v-if="monitor">
          <Button :disabled="status.checking" @click="checkNow" hard>{{ status.checking ? 'Checking…' : 'Check now' }}</Button>
          <span v-if="checkError" class="danger-text ms-1">{{ checkError }}</span>
        </p>
        <p class="XS grey-text mt-05" v-if="monitor">
          <template v-if="channels">
            Notifications by {{ channels }} when something turns red, and when it clears<template v-if="monitor.notify_sent_at">; last sent {{ formatDateTime(monitor.notify_sent_at) }}</template>.
          </template>
          <template v-else>No notifications: no channel is set up in <code class="XS black-bg">.env</code>.</template>
          <span v-if="monitor.notify_error" class="danger-text"> Last delivery failed: {{ monitor.notify_error }}</span>
        </p>
      </Box>

      <Box :size="100" v-if="!status.data && status.loading"><LoadingBox dark/></Box>
      <Box :size="100" v-else-if="status.error && !status.data"><p class="danger-box">{{ status.error }}</p></Box>

      <template v-if="status.data">
        <Box :size="100">
          <h3>Needs attention</h3>
          <p v-if="!status.attention.length" class="success-box">Nothing needs attention.</p>
          <ul v-else class="attention-list">
            <li v-for="(item, i) in status.attention" :key="i" class="flex align-items-start">
              <span :class="[SEVERITY_BOX[item.severity], 'S attention-kind']">{{ KIND_LABEL[item.kind] || item.kind }}</span>
              <span class="wrap-anywhere">
                <RouterLink v-if="itemLink(item)" :to="itemLink(item)" :class="itemLinkClass(item)"><strong>{{ item.title }}</strong></RouterLink>
                <strong v-else>{{ item.title }}</strong>
                <span v-if="item.detail" class="block S grey-text">{{ item.detail }}</span>
              </span>
            </li>
          </ul>
        </Box>

        <Box :size="100" class="wrap-anywhere">
          <h3>Sites</h3>
          <Tabs v-model="filter" :tabs="FILTERS" label="Show">
            <p v-if="!shownChecks.length" class="grey-text">None.</p>
            <table v-else class="data-table S">
              <thead>
                <tr><th></th><th>Project</th><th>URL</th><th>Answer</th><th>Certificate</th><th>Address</th></tr>
              </thead>
              <tbody>
                <tr v-for="c in shownChecks" :key="c.id">
                  <td><StatusDot :checks="[c]"/></td>
                  <td>
                    <RouterLink :to="{ name: 'project', params: { slug: c.project.slug } }">{{ c.project.name }}</RouterLink>
                    <span class="grey-text">&nbsp;&nbsp;·&nbsp;&nbsp;{{ c.environment_name }}</span>
                  </td>
                  <td>
                    <a :href="c.url" target="_blank" rel="noopener noreferrer">{{ hostOf(c.url) }}</a>
                    <div v-if="c.final_url && hostOf(c.final_url) !== hostOf(c.url)" class="XS grey-text">→ {{ hostOf(c.final_url) }}</div>
                  </td>
                  <td class="white-text">
                    <template v-if="c.state === 'down'">
                      <span class="danger-text">{{ c.error }}</span>
                      <div class="XS grey-text">since {{ formatDateTime(c.since) }}</div>
                    </template>
                    <template v-else-if="c.failing_since">
                      <span class="warning-text">{{ c.error }}</span>
                      <div class="XS grey-text">since {{ formatDateTime(c.failing_since) }}&nbsp;&nbsp;·&nbsp;&nbsp;checking again</div>
                    </template>
                    <template v-else>
                      {{ c.status_code }}<span class="grey-text">&nbsp;&nbsp;·&nbsp;&nbsp;{{ c.response_ms }} ms</span>
                      <div v-if="c.attempts > 1" class="XS grey-text">at attempt {{ c.attempts }}</div>
                    </template>
                  </td>
                  <td class="light-grey-text">
                    <span :class="{ 'warning-text': certificate(c).soon }">{{ certificate(c).text }}</span>
                    <div v-if="c.tls_elsewhere?.length" class="XS warning-text" :title="`Also on it: ${c.tls_names.join(', ')}`">
                      can’t renew here: also covers {{ c.tls_elsewhere.join(', ') }}
                    </div>
                  </td>
                  <td class="white-text">
                    <span v-if="!c.ips.length">–</span>
                    <div v-for="f in ipFamilies(c.ips)" :key="f.label">
                      <span :class="{ 'warning-text': c.dns_match === false }">{{ f.ips[0] }}</span>
                      <span v-if="f.ips.length > 1" class="grey-text" :title="f.ips.join('\n')"> +{{ f.ips.length - 1 }}</span>
                      <span class="XS light-grey-text ms-05">{{ f.label }}</span>
                    </div>
                    <div v-if="c.platform" class="XS grey-text">
                      {{ c.dns_match === false ? 'not' : c.dns_match ? 'on' : '' }}
                      <RouterLink :to="{ name: 'platform', params: { slug: c.platform.slug } }" class="platform-text">{{ c.platform.name }}</RouterLink>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </Tabs>
        </Box>

        <Box :size="100" class="wrap-anywhere">
          <h3>{{ scan?.platform?.name || scan?.host || 'The server' }}: repos, nginx, services<template v-if="maldet">, malware</template></h3>
          <p v-if="monitor.scan_error" class="warning-box S">{{ monitor.scan_error }}</p>
          <template v-if="scan">
            <p class="XS grey-text">
              Scanned {{ timeAgo(scan.scanned_at) }} by <code class="XS black-bg">deploy/scan_local.py</code>, every 15 minutes from the host’s crontab.
            </p>
            <Tabs v-model="localTab" :tabs="LOCAL_TABS" label="Local scan">
              <table v-if="localTab === 'repos'" class="data-table S">
                <thead>
                  <tr><th>Repo</th><th>Branch</th><th>State</th><th>Last commit</th><th>Catalog</th></tr>
                </thead>
                <tbody>
                  <tr v-for="r in scan.repos" :key="r.path">
                    <td><code class="XS black-bg">{{ shortPath(r.path) }}</code></td>
                    <td>
                      {{ r.branch || 'detached' }}
                      <div v-if="r.upstream" class="XS grey-text">→ {{ r.upstream }}</div>
                    </td>
                    <td>
                      <span v-if="r.error" class="danger-box XS">{{ r.error }}</span>
                      <span v-if="r.changes" class="warning-box XS me-05">{{ r.changes }} changed</span>
                      <span v-if="r.untracked" class="text-box XS me-05">{{ r.untracked }} untracked</span>
                      <span v-if="r.ahead" class="info-box XS me-05">{{ r.ahead }} to push</span>
                      <span v-if="!r.error && !Object.keys(r.remotes || {}).length" class="text-box XS">no remote</span>
                    </td>
                    <td>
                      <template v-if="r.head"><code class="XS black-bg">{{ r.head }}</code> {{ formatDate(r.date) }}
                        <div class="XS grey-text">{{ r.subject }}</div></template>
                    </td>
                    <td>
                      <RouterLink v-if="r.catalog" :to="{ name: 'repositories' }" class="repository-text">
                        <Repository width="0.9em" height="0.9em" aria-hidden="true" style="vertical-align: -0.1em" class="me-025"/>{{ r.catalog.name }}
                      </RouterLink>
                      <span v-else class="grey-text">not in the catalog</span>
                    </td>
                  </tr>
                </tbody>
              </table>

              <table v-else-if="localTab === 'nginx'" class="data-table S">
                <thead>
                  <tr><th>Site</th><th>Names</th><th>Catalog</th></tr>
                </thead>
                <tbody>
                  <tr v-for="s in scan.nginx" :key="s.file">
                    <td><code class="XS black-bg">{{ s.file }}</code><div v-if="s.error" class="XS danger-text">{{ s.error }}</div></td>
                    <td>
                      <div v-for="n in s.names" :key="n.name">
                        {{ n.name }}
                        <span v-if="nameState(n)" :class="['XS', nameState(n).cls]">&nbsp;&nbsp;·&nbsp;&nbsp;{{ nameState(n).text }}</span>
                      </div>
                    </td>
                    <td>
                      <template v-for="n in s.names" :key="n.name">
                        <div v-for="c in n.catalog" :key="`${n.name}-${c.project.slug}-${c.environment}`">
                          <RouterLink :to="{ name: 'project', params: { slug: c.project.slug } }">{{ c.project.name }}</RouterLink>
                          <span class="grey-text">&nbsp;&nbsp;·&nbsp;&nbsp;{{ c.environment }}</span>
                        </div>
                      </template>
                      <span v-if="s.names.every(n => !n.catalog.length)" class="grey-text">
                        {{ s.names.every(n => n.known) ? '' : 'not in the catalog' }}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>

              <template v-else-if="localTab === 'malware' && maldet">
                <p v-if="maldet.error" class="warning-box S">Can’t read {{ maldet.log }}: {{ maldet.error }}</p>
                <p v-else-if="!maldet.open_hits.length" class="success-box S">No flagged file.</p>
                <table v-else class="data-table S">
                  <thead><tr><th>Flagged file</th><th>Signature</th><th>Found</th></tr></thead>
                  <tbody>
                    <tr v-for="h in maldet.open_hits" :key="`${h.pid}-${h.file}`">
                      <td><code class="XS black-bg">{{ h.file }}</code></td>
                      <td><span class="danger-box XS">{{ h.signature }}</span></td>
                      <td>{{ formatDateTime(h.at) }}<div v-if="h.report" class="XS grey-text"><code class="XS black-bg">sudo maldet --report {{ h.report }}</code></div></td>
                    </tr>
                  </tbody>
                </table>
                <table v-if="maldet.latest.length" class="data-table S">
                  <thead><tr><th>Latest scan of</th><th>When</th><th>Files</th><th>Hits</th></tr></thead>
                  <tbody>
                    <tr v-for="sc in maldet.latest" :key="sc.paths">
                      <td><code class="XS black-bg">{{ sc.paths }}</code></td>
                      <td>{{ formatDateTime(sc.at) }}<div class="XS grey-text">{{ sc.seconds }} s</div></td>
                      <td>{{ sc.files }}</td>
                      <td><span :class="sc.hits ? 'danger-text' : 'grey-text'">{{ sc.hits }}</span></td>
                    </tr>
                  </tbody>
                </table>
                <p class="XS grey-text">
                  From maldet’s log (<code class="XS black-bg">{{ maldet.log }}</code>). Its daily scan looks at files changed in the last day, so a flagged
                  file stays here until it’s deleted, quarantined, or ignored as a false positive in <code class="XS black-bg">/usr/local/maldetect/ignore_paths</code>.
                </p>
              </template>

              <template v-else>
                <p v-if="!scan.failed_units.length" class="success-box S">No failed service.</p>
                <table v-else class="data-table S">
                  <thead><tr><th>Failed service</th><th>Description</th></tr></thead>
                  <tbody>
                    <tr v-for="u in scan.failed_units" :key="u.unit">
                      <td><code class="XS black-bg">{{ u.unit }}</code></td>
                      <td>{{ u.description }}</td>
                    </tr>
                  </tbody>
                </table>
                <p class="XS grey-text">
                  {{ scan.running_units }} services running.
                  To look at one: <code class="XS black-bg">sudo systemctl status &lt;name&gt;</code>; to clear a failure that no longer matters: <code class="XS black-bg">sudo systemctl reset-failed &lt;name&gt;</code>.
                </p>
              </template>
            </Tabs>
          </template>
        </Box>

        <Box :size="100" class="wrap-anywhere">
          <h3>Last {{ monitor.history_days }} days</h3>
          <p v-if="!events.length" class="grey-text">No site went down.</p>
          <table v-else class="data-table S">
            <tbody>
              <tr v-for="e in events" :key="e.id">
                <td class="nowrap">{{ formatDateTime(e.at) }}</td>
                <td>
                  <span :class="[e.state === 'down' ? 'danger-bg' : 'success-bg', 'flag border-0 p-05']">{{ e.state === 'down' ? 'went down' : 'came back' }}</span>
                </td>
                <td>
                  <RouterLink :to="{ name: 'project', params: { slug: e.project.slug } }">{{ e.project.name }}</RouterLink>
                  <span class="grey-text">&nbsp;&nbsp;·&nbsp;&nbsp;{{ e.environment_name }}&nbsp;&nbsp;·&nbsp;&nbsp;{{ hostOf(e.url) }}</span>
                  <div v-if="e.detail || e.lasted" class="XS grey-text">{{ e.detail || `after ${e.lasted}` }}</div>
                </td>
              </tr>
            </tbody>
          </table>
        </Box>
      </template>
    </Boxes>
  </Container>
</template>

<style scoped>
.attention-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.attention-list li {
  padding: calc(var(--padding) * .5) 0;
  border-bottom: 2px solid var(--light-grey);
}
.attention-kind {
  flex: none;
  min-width: 6.5em;
  text-align: center;
}
.nowrap {
  white-space: nowrap;
}
table thead tr th {
  color: var(--grey);
}
.attention-list li {
  margin: 0;
}
table thead tr th, table tbody tr td, .attention-list li {
  color: var(--white);
  background-color: var(--false-black);
  border-bottom: 2px solid var(--black);
  padding: var(--padding);
}
</style>
