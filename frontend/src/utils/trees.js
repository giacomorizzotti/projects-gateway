// The hierarchies the tree view can draw, as plain nested nodes:
//   { key, label, sub, type, to, tone, children, repeat }
// key: unique per position in the tree (a project can appear in several places).
// to: a router location, for nodes that open a page. tone: a colour name, mini's or one of
// main.scss's $entities (project, platform, env-prod, …).
import { dependencyHow, dependencyUpdate, envColor } from '@/utils/format'

const STATUS_TONE = { active: 'project', development: 'info', maintenance: 'warning', discontinued: 'danger', archived: 'grey' }
const UPDATE_TONE = { live: 'info', manual: 'warning' }

const byName = (a, b) => a.label.localeCompare(b.label)

function projectNode(key, p, extra = {}) {
  return { key, label: p.name, type: 'project', to: { name: 'project', params: { slug: p.slug } },
           tone: STATUS_TONE[p.status] || 'project', children: [], ...extra }
}

function envNode(key, env, sub) {
  return { key, label: env.name, sub, type: 'env', tone: envColor(env.kind), children: [] }
}

// Buckets ({ id, label, sub?, tone?, projects }) → projects → environments (with their platform).
// Empty buckets are left out.
function bucketTree(label, prefix, buckets) {
  return {
    key: 'root', label, type: 'root', tone: 'black',
    children: buckets
      .filter(b => b.projects.length)
      .map(b => ({
        key: `${prefix}:${b.id}`, label: b.label, sub: b.sub, type: 'group', tone: b.tone || 'dark-grey',
        children: b.projects.map(p => projectNode(`${prefix}:${b.id}/${p.id}`, p, {
          children: p.environments.map(e => envNode(`${prefix}:${b.id}/${p.id}/${e.id}`, e, e.platform_detail?.name)),
        })),
      })),
  }
}

export function byGroup(projects, groups) {
  return bucketTree('Projects', 'g',
    groups.map(g => ({ id: g.value, label: g.label, projects: projects.filter(p => p.group === g.value) })))
}

// Clients A–Z with their project count, then the projects with no client.
export function byClient(projects, clients) {
  const buckets = [
    ...clients.map(c => ({ id: c.id, label: c.name, projects: projects.filter(p => p.client === c.id) })),
    { id: 'none', label: 'No client', tone: 'grey', projects: projects.filter(p => !p.client) },
  ]
  for (const b of buckets) b.sub = String(b.projects.length)
  return bucketTree('Clients', 'c', buckets)
}

// Platforms → projects → their environments on that platform.
export function byPlatform(projects, platforms) {
  const rows = [...platforms.map(pl => ({ id: pl.id, name: pl.name, slug: pl.slug, sub: pl.kind_label })),
                { id: null, name: 'No platform recorded' }]
  return {
    key: 'root', label: 'Platforms', type: 'root', tone: 'black',
    children: rows
      .map(pl => ({
        key: `pl:${pl.id}`, label: pl.name, sub: pl.sub, type: 'platform', tone: 'platform',
        to: pl.slug ? { name: 'platform', params: { slug: pl.slug } } : null,
        children: projects
          .map(p => ({ p, envs: p.environments.filter(e => (e.platform ?? null) === pl.id) }))
          .filter(({ envs }) => envs.length)
          .map(({ p, envs }) => projectNode(`pl:${pl.id}/${p.id}`, p, {
            children: envs.map(e => envNode(`pl:${pl.id}/${p.id}/${e.id}`, e, e.urls[0] ? hostLabel(e.urls[0]) : e.path)),
          })),
      }))
      .filter(pl => pl.children.length),
  }
}

function hostLabel(url) {
  try { return new URL(url).host } catch { return url }
}

// Shared projects → who uses them, grouped by how they include them ("CDN @main", "Symlink"…).
// Roots: the projects that depend on nothing (a UI library) and the services others call (the
// auth server, an API).
// A project used in several places is drawn in full once, at its shallowest place, and as a
// "see above" leaf elsewhere. `projects` is the visible set: their ancestors are kept too,
// so a filtered tree still shows the path from mini down to them.
export function byDependency(projects, dependencies, allProjects) {
  const byId = new Map(allProjects.map(p => [p.id, p]))
  const usedBy = new Map()      // provider id → dependency rows
  const uses = new Map()        // dependent id → dependency rows
  for (const d of dependencies) {
    if (!byId.has(d.project) || !byId.has(d.depends_on)) continue
    if (!usedBy.has(d.depends_on)) usedBy.set(d.depends_on, [])
    usedBy.get(d.depends_on).push(d)
    if (!uses.has(d.project)) uses.set(d.project, [])
    uses.get(d.project).push(d)
  }

  // The visible projects plus everything they depend on, transitively.
  const keep = new Set()
  const stack = projects.map(p => p.id)
  while (stack.length) {
    const id = stack.pop()
    if (keep.has(id)) continue
    keep.add(id)
    for (const d of uses.get(id) || []) stack.push(d.depends_on)
  }
  const visibleUsers = id => (usedBy.get(id) || []).filter(d => keep.has(d.project))

  // Roots: what depends on nothing (a UI library), and the services others call (login, APIs,
  // backends: the auth server, an API), so they head their own tree too.
  const roots = [...keep].filter(id => {
    const users = visibleUsers(id)
    if (!users.length) return false
    return users.some(d => d.kind !== 'ui_library') || !(uses.get(id) || []).some(d => keep.has(d.depends_on))
  })

  // Breadth-first, so each provider is expanded at its shallowest place.
  const expanded = new Set()
  const root = { key: 'root', label: 'Dependencies', type: 'root', tone: 'black', children: [] }
  const queue = []
  for (const id of roots.sort((a, b) => byId.get(a).name.localeCompare(byId.get(b).name))) {
    const node = projectNode(`d:${id}`, byId.get(id))
    root.children.push(node)
    expanded.add(id)
    queue.push([node, id])
  }
  while (queue.length) {
    const [node, id] = queue.shift()
    const rows = visibleUsers(id)
    const groups = new Map()
    for (const d of rows) {
      const how = dependencyHow(d, { withEnvironment: false }) || 'How not recorded'
      if (!groups.has(how)) groups.set(how, [])
      groups.get(how).push(d)
    }
    // With several ways of being included, one branch per way; otherwise straight to the users.
    const grouped = groups.size > 1 && rows.length > 3
    for (const [how, list] of [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))) {
      const update = dependencyUpdate(list[0])
      const parent = grouped
        ? { key: `${node.key}/via:${how}`, label: how, sub: `${list.length}`, type: 'via',
            tone: UPDATE_TONE[update?.label] || 'grey', title: update?.title, children: [] }
        : node
      if (grouped) node.children.push(parent)
      for (const d of list.sort((a, b) => byId.get(a.project).name.localeCompare(byId.get(b.project).name))) {
        const user = byId.get(d.project)
        const sub = [grouped ? '' : how, d.environment_name].filter(Boolean).join('&nbsp;&nbsp;·&nbsp;&nbsp;')
        const child = projectNode(`${parent.key}/${d.id}`, user, { sub, title: d.notes || update?.title })
        if (visibleUsers(user.id).length) {
          if (expanded.has(user.id)) {
            child.repeat = true
          } else {
            expanded.add(user.id)
            queue.push([child, user.id])
          }
        }
        parent.children.push(child)
      }
    }
  }
  root.children.sort(byName)
  const shown = new Set([...keep].filter(id => usedBy.has(id) || uses.has(id)))
  return { root, untouched: projects.filter(p => !shown.has(p.id)).length }
}
