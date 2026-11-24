<script setup>
// Draws one of the trees from utils/trees.js as a left-to-right SVG: a dot, its label, and
// curves from the end of the label to its children. Click a dot to fold a branch; click a
// project or platform name to open its page. d3-hierarchy only computes the layout.
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { hierarchy, tree as d3tree } from 'd3-hierarchy'

const props = defineProps({
  root: { type: Object, required: true },
})

const router = useRouter()
const ROW = 24
const GAP = 36
const MAX_CHARS = 42

// Folded branches, by node key. A new tree (another mode, other filters) starts unfolded.
const folded = ref(new Set())
watch(() => props.root, () => { folded.value = new Set() })

function toggle(node) {
  if (!node.data.children?.length) return
  const next = new Set(folded.value)
  next.has(node.data.key) ? next.delete(node.data.key) : next.add(node.data.key)
  folded.value = next
}

function foldToDepth(depth) {
  const next = new Set()
  hierarchy(props.root).each(n => { if (n.depth >= depth && n.children) next.add(n.data.key) })
  folded.value = next
}

const clip = text => (text && text.length > MAX_CHARS ? text.slice(0, MAX_CHARS - 1) + '…' : text || '')

// Text width with the page's real font (a canvas measures it), so curves start right after
// each label.
let ctx = null
function textWidth(text, size) {
  if (!ctx) {
    ctx = document.createElement('canvas').getContext('2d')
    ctx.fontFamily = getComputedStyle(document.body).fontFamily
  }
  ctx.font = `${size}px ${ctx.fontFamily}`
  return ctx.measureText(text).width
}

const layout = computed(() => {
  const h = hierarchy(props.root, d => (folded.value.has(d.key) ? null : d.children))
  d3tree().nodeSize([ROW, 1]).separation((a, b) => (a.parent === b.parent ? 1 : 1.25))(h)
  const nodes = h.descendants()

  // Each column is as wide as its widest label.
  for (const n of nodes) {
    n.labelText = clip(n.data.label)
    n.subText = clip(n.data.sub)
    n.width = 14 + textWidth(n.labelText, 14) + (n.subText ? 8 + textWidth(n.subText, 12) : 0)
  }
  const widths = []
  for (const n of nodes) widths[n.depth] = Math.max(widths[n.depth] || 0, n.width)
  const colX = [0]
  for (let d = 1; d < widths.length; d++) colX[d] = colX[d - 1] + widths[d - 1] + GAP
  for (const n of nodes) n.y = colX[n.depth]

  const minX = Math.min(...nodes.map(n => n.x))
  const maxX = Math.max(...nodes.map(n => n.x))
  const width = colX[colX.length - 1] + widths[widths.length - 1] + 16
  return { nodes, links: h.links(), width: Math.ceil(width) + 16, height: maxX - minX + ROW * 2, offset: ROW - minX }
})

function linkPath({ source, target }) {
  const sx = source.y + source.width
  const tx = target.y - 6
  const mid = (sx + tx) / 2
  return `M${sx},${source.x}C${mid},${source.x} ${mid},${target.x} ${tx},${target.x}`
}

function open(node, event) {
  if (!node.data.to) return toggle(node)
  if (event.metaKey || event.ctrlKey) return     // let the browser open a new tab
  event.preventDefault()
  router.push(node.data.to)
}

const href = node => (node.data.to ? router.resolve(node.data.to).href : undefined)
const isFolded = node => folded.value.has(node.data.key)
</script>

<template>
  <div>
    <p class="S m-0 mb-05">
      <a href="#" @click.prevent="folded = new Set()">Unfold all</a> ·
      <a href="#" @click.prevent="foldToDepth(1)">Fold to the first level</a> ·
      <a href="#" @click.prevent="foldToDepth(2)">to the second</a>
    </p>
    <div class="tree-scroll">
      <svg :width="layout.width" :height="layout.height" class="project-tree" role="img"
           :aria-label="`${root.label} tree`">
        <g :transform="`translate(8,${layout.offset})`">
          <path v-for="l in layout.links" :key="l.target.data.key" :d="linkPath(l)" class="tree-link"/>
          <g v-for="n in layout.nodes" :key="n.data.key" :transform="`translate(${n.y},${n.x})`"
             :class="['tree-node', `tree-${n.data.type}`, { 'tree-repeat': n.data.repeat }]">
            <title v-if="n.data.title || n.data.repeat">{{ n.data.repeat ? 'Shown in full in another branch' : '' }}{{ n.data.repeat && n.data.title ? '&nbsp;&nbsp;·&nbsp;&nbsp;' : '' }}{{ n.data.title }}</title>
            <circle r="5" :style="{ '--tone': `var(--${n.data.tone})` }"
                    :class="{ folded: isFolded(n), branch: n.data.children?.length }"
                    @click="toggle(n)"/>
            <a :href="href(n)" @click="open(n, $event)" class="tree-label">
              <text x="10" dy="0.32em">
                <tspan class="tree-name">{{ n.labelText }}</tspan>
                <tspan v-if="n.subText" class="tree-sub" dx="8">{{ n.subText }}</tspan>
              </text>
            </a>
          </g>
        </g>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.tree-scroll {
  overflow-x: auto;
  padding-bottom: 0.5rem;
}

.project-tree {
  display: block;
  font-size: 14px;
}

.tree-link {
  fill: none;
  stroke: var(--light-grey);
  stroke-width: 1.5;
}

.tree-node circle {
  fill: var(--white);
  stroke: var(--tone);
  stroke-width: 2;
}

.tree-node circle.branch {
  cursor: pointer;
}

/* A folded branch: a filled dot, so it's clear something is hidden there. */
.tree-node circle.folded {
  fill: var(--tone);
}

.tree-name {
  fill: var(--white);
}

.tree-root .tree-name,
.tree-group .tree-name,
.tree-platform .tree-name {
  font-weight: 600;
}

.tree-via .tree-name {
  font-style: italic;
}

.tree-sub {
  fill: var(--grey);
  font-size: 12px;
}

.tree-repeat circle {
  stroke-dasharray: 2 2;
}

.tree-repeat .tree-name {
  fill: var(--grey);
}

.tree-label {
  cursor: pointer;
}

.tree-label:hover .tree-name,
.tree-label:focus-visible .tree-name {
  text-decoration: underline;
}
</style>
