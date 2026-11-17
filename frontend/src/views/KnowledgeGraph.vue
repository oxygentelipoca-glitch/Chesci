<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import * as echarts from 'echarts'
import { getGraph, getReactions } from '../api/chemistry.js'
import MainLayout from '../layouts/MainLayout.vue'

const chartRef = ref(null)
const selected = ref(null)
const empty = ref(false)
const searchQuery = ref('')
const allNodes = ref([])
const allLinks = ref([])
const visibleLinks = ref([])
const noSearchResult = ref(false)
const showAllNodes = ref(false)
const showConditions = ref(false)
const viewSummary = ref('正在加载图谱…')
const reactions = ref([])
let chart = null
let resizeObserver = null

const coreCategories = new Set(['reactant', 'product', 'both'])
const categoryLabels = {
  reactant: '反应物',
  product: '产物',
  both: '反应物 / 产物',
  catalyst: '催化剂',
  solvent: '溶剂',
}
const visibleRelationCount = computed(() => visibleLinks.value.length)

function aggregateLinks(links) {
  const groups = new Map()
  for (const link of links) {
    const key = `${link.category || 'reaction'}:${link.source}->${link.target}`
    let group = groups.get(key)
    if (!group) {
      group = {
        source: link.source,
        target: link.target,
        category: link.category || 'reaction',
        reactionIds: new Set(),
        rawCount: 0,
      }
      groups.set(key, group)
    }
    group.rawCount += 1
    if (link.reaction_id != null) group.reactionIds.add(link.reaction_id)
  }
  return [...groups.values()].map(group => ({
    source: group.source,
    target: group.target,
    category: group.category,
    reaction_count: group.reactionIds.size || group.rawCount,
  }))
}

function focusedGraph(query) {
  const matches = allNodes.value
    .filter(node => String(node.name || '').toLocaleLowerCase().includes(query))
    .sort((a, b) => (b.reaction_count || 0) - (a.reaction_count || 0))
  if (!matches.length) return { nodes: [], links: [], highlights: [], matchedCount: 0 }

  const focusNodes = matches.slice(0, 12)
  const focusIds = new Set(focusNodes.map(node => node.id))
  const catalystFocus = focusNodes.some(node => node.category === 'catalyst')
    && !focusNodes.some(node => coreCategories.has(node.category))
  const candidateLinks = aggregateLinks(allLinks.value.filter(link =>
    link.category === 'reaction'
    || ((showConditions.value || catalystFocus) && link.category === 'catalysis')
  ))

  const neighborWeight = new Map()
  for (const link of candidateLinks) {
    if (focusIds.has(link.source)) {
      neighborWeight.set(link.target, (neighborWeight.get(link.target) || 0) + link.reaction_count)
    }
    if (focusIds.has(link.target)) {
      neighborWeight.set(link.source, (neighborWeight.get(link.source) || 0) + link.reaction_count)
    }
  }
  const neighborIds = [...neighborWeight.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, (chartRef.value?.clientWidth || window.innerWidth) < 540 ? 8 : 16)
    .map(([id]) => id)
  const visibleIds = new Set([...focusIds, ...neighborIds])
  const nodes = allNodes.value.filter(node => visibleIds.has(node.id))
  const links = candidateLinks.filter(link =>
    visibleIds.has(link.source)
    && visibleIds.has(link.target)
    && (focusIds.has(link.source) || focusIds.has(link.target))
  )
  return { nodes, links, highlights: [...focusIds], matchedCount: matches.length }
}

function overviewGraph() {
  const coreNodes = allNodes.value.filter(node => coreCategories.has(node.category))
  const reactionLinks = aggregateLinks(allLinks.value.filter(link => link.category === 'reaction'))
  const degree = new Map(coreNodes.map(node => [node.id, 0]))
  for (const link of reactionLinks) {
    degree.set(link.source, (degree.get(link.source) || 0) + 1)
    degree.set(link.target, (degree.get(link.target) || 0) + 1)
  }
  const rankedNodes = coreNodes
    .filter(node => degree.get(node.id) > 0)
    .sort((a, b) => (degree.get(b.id) - degree.get(a.id))
      || ((b.reaction_count || 0) - (a.reaction_count || 0)))
  const defaultLimit = (chartRef.value?.clientWidth || window.innerWidth) < 540 ? 10 : 18
  const mainNodes = showAllNodes.value ? rankedNodes : rankedNodes.slice(0, defaultLimit)
  const mainIds = new Set(mainNodes.map(node => node.id))
  const nodes = [...mainNodes]
  const links = reactionLinks.filter(link => mainIds.has(link.source) && mainIds.has(link.target))

  if (showConditions.value) {
    const conditionLinks = aggregateLinks(allLinks.value.filter(link => link.category === 'catalysis'))
      .filter(link => mainIds.has(link.target))
    const catalystWeight = new Map()
    for (const link of conditionLinks) {
      catalystWeight.set(link.source, (catalystWeight.get(link.source) || 0) + link.reaction_count)
    }
    const catalystIds = new Set([...catalystWeight.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, showAllNodes.value ? 18 : 10)
      .map(([id]) => id))
    nodes.push(...allNodes.value.filter(node => catalystIds.has(node.id)))
    links.push(...conditionLinks.filter(link => catalystIds.has(link.source)))
  }
  return { nodes, links, highlights: [] }
}

function updateGraph() {
  if (!allNodes.value.length) return
  const query = searchQuery.value.trim().toLocaleLowerCase()
  noSearchResult.value = false
  selected.value = null
  const graph = query ? focusedGraph(query) : overviewGraph()
  visibleLinks.value = graph.links
  noSearchResult.value = Boolean(query) && graph.matchedCount === 0

  if (query) {
    viewSummary.value = graph.matchedCount
      ? `${graph.matchedCount > 12 ? '显示前 12 个匹配项 · ' : ''}${graph.nodes.length} 个节点 · ${graph.links.length} 条关联`
      : '没有匹配的化合物'
  } else {
    const mode = showAllNodes.value ? '全部反应网络' : '重点网络'
    viewSummary.value = `${mode} · ${graph.nodes.length} 个节点 · ${graph.links.length} 条合并关系 · 数据库 ${allNodes.value.length} 节点`
  }
  renderGraph(graph.nodes, graph.links, Boolean(query), graph.highlights)
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char])
}

function renderGraph(nodes, links, isFocused, highlights = []) {
  if (!chartRef.value) return
  const compact = chartRef.value.clientWidth < 540
  if (chart) chart.dispose()
  chart = echarts.init(chartRef.value)
  const categoryNames = [...new Set(nodes.map(node => categoryLabels[node.category]).filter(Boolean))]
  const categoryIndex = Object.fromEntries(categoryNames.map((name, index) => [name, index]))
  const colors = { reactant: '#65A9BA', product: '#16806A', both: '#497FA3', catalyst: '#C18A48' }
  const nodeNameById = new Map(nodes.map(node => [node.id, node.name]))
  const graphNodes = nodes.map(node => {
    const categoryName = categoryLabels[node.category] || '反应物'
    const isHighlight = highlights.includes(node.id)
    const count = Math.max(1, node.reaction_count || 1)
    return {
      ...node,
      category: categoryIndex[categoryName] ?? 0,
      symbolSize: Math.min(42, 22 + Math.log2(count + 1) * 3),
      itemStyle: {
        color: colors[node.category] || colors.reactant,
        borderColor: isHighlight ? '#E5A23B' : '#fff',
        borderWidth: isHighlight ? 3 : 1.5,
        shadowBlur: isHighlight ? 12 : 3,
        shadowColor: isHighlight ? 'rgba(229,162,59,.28)' : 'rgba(20,40,60,.10)',
      },
      label: {
        show: true, position: 'right', distance: 6,
        color: '#344054', fontSize: compact ? 10 : (isFocused ? 12 : 11),
        formatter: params => params.name.length > (compact ? 12 : 16)
          ? `${params.name.slice(0, compact ? 11 : 15)}…`
          : params.name,
      },
    }
  })
  const graphLinks = links.map(link => ({
    ...link,
    label: { show: false },
    lineStyle: {
      color: link.category === 'catalysis' ? '#C9A36B' : '#91A9B8',
      width: Math.min(4, 1.2 + Math.log2((link.reaction_count || 1) + 1) * 0.45),
      opacity: link.category === 'catalysis' ? 0.5 : 0.62,
      curveness: 0.06,
    },
  }))

  chart.setOption({
    backgroundColor: '#fff',
    animationDuration: 450,
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: params => {
        if (params.dataType === 'node') {
          const category = categoryNames[params.data.category] || '化合物'
          return `<div style="font-weight:700">${escapeHtml(params.name)}</div>`
            + `<div>${escapeHtml(category)} · 出现 ${Number(params.data.reaction_count || 1)} 次</div>`
        }
        const source = nodeNameById.get(params.data.source) || params.data.source
        const target = nodeNameById.get(params.data.target) || params.data.target
        const relation = params.data.category === 'catalysis' ? '催化关系' : '反应关系'
        return `<div style="font-weight:700">${escapeHtml(source)} → ${escapeHtml(target)}</div>`
          + `<div>${relation} · ${params.data.reaction_count || 1} 条反应记录</div>`
      },
    },
    legend: {
      top: 10, left: 12, data: categoryNames,
      textStyle: { fontSize: 11, color: '#667085' }, itemWidth: 10, itemHeight: 10,
    },
    series: [{
      type: 'graph', layout: 'force', roam: true, draggable: true,
      left: 18, right: 32, top: 42, bottom: 40,
      zoom: isFocused ? 1.08 : 1,
      scaleLimit: { min: 0.45, max: 3.2 },
      force: {
        repulsion: compact ? 180 : (isFocused ? 340 : 260),
        gravity: 0.08,
        edgeLength: compact ? [75, 115] : (isFocused ? [115, 170] : [100, 155]),
        friction: 0.62,
        layoutAnimation: true,
      },
      data: graphNodes, links: graphLinks,
      categories: categoryNames.map(name => ({ name })),
      label: { show: true }, labelLayout: { hideOverlap: true },
      edgeLabel: { show: false },
      edgeSymbol: ['none', 'arrow'], edgeSymbolSize: [0, 7],
      emphasis: {
        focus: 'adjacency', scale: 1.12,
        label: { show: true, fontSize: 13, fontWeight: 600 },
        lineStyle: { width: 3, opacity: 0.9 },
      },
      lineStyle: { opacity: 0.6 },
    }],
  }, { notMerge: true })

  chart.off('click')
  chart.on('click', params => {
    if (params.dataType === 'node') {
      selected.value = allNodes.value.find(node => node.id === params.data.id) || params.data
    }
  })
  if (!resizeObserver) {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(chartRef.value)
  }
}

watch([searchQuery, showAllNodes, showConditions], updateGraph)

onMounted(async () => {
  try {
    const data = await getGraph()
    if (!data.nodes?.length) { empty.value = true; return }
    allNodes.value = data.nodes
    allLinks.value = data.links || []
    await nextTick()
    updateGraph()
  } catch {
    empty.value = true
  }
  try {
    const result = await getReactions({ limit: 200 })
    reactions.value = result.items || result.reactions || []
  } catch {
    reactions.value = []
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  resizeObserver = null
  chart = null
})
</script>

<template>
  <MainLayout>
    <div class="kg-root">
      <header class="page-intro"><h1>知识图谱</h1><p>搜索一个化合物，查看与它直接相连的反应。点击节点可查看记录详情。</p></header>

      <div class="kg-toolbar">
        <input v-model="searchQuery" placeholder="搜索化合物，如：苯甲醛、肉桂酸、Piperidine" class="kg-search" aria-label="搜索图谱中的化合物" />
        <button v-if="searchQuery" class="kg-clear" @click="searchQuery = ''">清除搜索</button>
        <button v-else class="kg-mode" @click="showAllNodes = !showAllNodes">
          {{ showAllNodes ? '收起至重点网络' : '展开全部反应网络' }}
        </button>
        <label class="kg-toggle">
          <input v-model="showConditions" type="checkbox" />
          <span>显示催化关系</span>
        </label>
        <span class="kg-count">{{ viewSummary }}</span>
      </div>
      <p class="kg-hint">重复的同一化合物关系已合并；悬停查看记录数，点击节点查看详情。溶剂不作为反应路径边显示。</p>

      <div v-if="empty" class="empty-state">
        <p>图谱暂不可用</p>
        <p class="hint">请检查反应数据库或服务连接。</p>
      </div>
      <div v-else class="kg-layout">
        <div class="kg-canvas-wrap">
          <div class="kg-canvas" ref="chartRef"></div>
          <div v-if="noSearchResult" class="kg-overlay">没有找到匹配的化合物，请检查名称或尝试英文名。</div>
          <div v-else-if="searchQuery && !visibleRelationCount" class="kg-overlay">
            找到该词条，但当前图谱中没有可显示的反应关系。
          </div>
        </div>
        <aside v-if="selected" class="kg-detail">
          <button class="kg-detail-close" aria-label="关闭详情" @click="selected = null">×</button>
          <span class="kg-detail-kicker">化合物详情</span>
          <h3>{{ selected.name }}</h3>
          <div class="kg-detail-row">
            <span>分类</span>
            <strong>{{ categoryLabels[selected.category] || selected.category }}</strong>
          </div>
          <div class="kg-detail-row">
            <span>出现次数</span>
            <strong>{{ selected.reaction_count || 1 }}</strong>
          </div>
          <button class="kg-focus-btn" @click="searchQuery = selected.name">聚焦此化合物</button>
        </aside>
      </div>

      <details class="reaction-list" v-if="reactions.length">
        <summary>反应记录 <span>{{ reactions.length }} 条（按需展开）</span></summary>
        <div class="reaction-table-wrap">
          <table class="rxn-table">
            <thead>
              <tr><th>ID</th><th>CAS</th><th>反应物</th><th>产物</th><th>收率</th></tr>
            </thead>
            <tbody>
              <tr v-for="reaction in reactions" :key="reaction.id">
                <td>{{ reaction.id || reaction.reaction_id || '-' }}</td>
                <td class="rxn-cas">{{ reaction.cas_registry_id || '-' }}</td>
                <td class="rxn-text">{{ reaction.reactants_text || (reaction.reactants || []).join(', ') || '-' }}</td>
                <td class="rxn-text">{{ reaction.products_text || (reaction.products || []).join(', ') || '-' }}</td>
                <td>{{ reaction.yield_ != null ? reaction.yield_ + '%' : (reaction.yield_text || '-') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
    </div>
  </MainLayout>
</template>

<style scoped>
.kg-root { max-width: 1440px; }
.kg-toolbar { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; margin-bottom: 7px; }
.kg-search { flex: 1 1 300px; min-width: 180px; max-width: 480px; padding: 10px 13px; border: 1px solid var(--border); border-radius: 9px; font-size: 13px; outline: none; }
.kg-search:focus { border-color: var(--primary-light); box-shadow: 0 0 0 3px rgba(74,144,164,.12); }
.kg-clear, .kg-mode { border: 1px solid var(--border); border-radius: 8px; background: #fff; color: var(--primary); padding: 9px 12px; font-size: 12px; font-weight: 600; cursor: pointer; white-space: nowrap; }
.kg-clear:hover, .kg-mode:hover { background: var(--primary-pale); }
.kg-toggle { display: inline-flex; align-items: center; gap: 7px; color: #526273; font-size: 12px; white-space: nowrap; cursor: pointer; }
.kg-toggle input { accent-color: var(--primary); }
.kg-count { margin-left: auto; color: var(--text-light); font-size: 12px; }
.kg-hint { color: var(--text-light); font-size: 12px; margin: 0 0 12px; }
.kg-layout { display: grid; grid-template-columns: minmax(0, 1fr) 230px; gap: 14px; align-items: start; }
.kg-canvas-wrap:only-child { grid-column:1 / -1 }
.kg-canvas-wrap { position: relative; min-width: 0; }
.kg-canvas { width: 100%; height: min(70vh, 720px); min-height: 500px; background: #fff; border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.kg-overlay { position: absolute; inset: 0; display: grid; place-items: center; padding: 20px; border: 1px solid var(--border); border-radius: 12px; background: rgba(255,255,255,.92); color: var(--text-light); text-align: center; font-size: 13px; pointer-events: none; }
.kg-detail { position: relative; background: #fff; border: 1px solid var(--border); border-radius: 12px; padding: 18px 16px; box-shadow: 0 5px 20px rgba(24,45,62,.06); }
.kg-detail-close { position: absolute; top: 8px; right: 10px; border: 0; background: transparent; color: #98A2B3; font-size: 22px; cursor: pointer; }
.kg-detail-kicker { color: var(--text-light); text-transform: uppercase; letter-spacing: .06em; font-size: 10px; }
.kg-detail h3 { margin: 8px 22px 16px 0; color: var(--primary); font-size: 16px; line-height: 1.45; overflow-wrap: anywhere; }
.kg-detail-row { display: flex; justify-content: space-between; gap: 10px; padding: 9px 0; border-top: 1px solid #EEF1F4; font-size: 12px; }
.kg-detail-row span { color: var(--text-light); }
.kg-detail-row strong { color: #344054; text-align: right; }
.kg-focus-btn { margin-top: 14px; width: 100%; padding: 9px; border: 1px solid var(--primary-light); border-radius: 8px; background: var(--primary-pale); color: var(--primary); font-size: 12px; font-weight: 600; cursor: pointer; }
.empty-state { text-align: center; padding: 80px 24px; color: var(--text-light); }
.empty-state .hint { font-size: 13px; margin-top: 8px; }
.reaction-list { margin-top: 16px; background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 0 16px; }
.reaction-list summary { padding: 14px 0; color: var(--primary); font-size: 14px; font-weight: 650; cursor: pointer; }
.reaction-list summary span { margin-left: 6px; color: var(--text-light); font-size: 12px; font-weight: 400; }
.reaction-table-wrap { overflow: auto; max-height: 420px; padding-bottom: 14px; }
.rxn-table { width: 100%; font-size: 12px; border-collapse: collapse; }
.rxn-table th { position: sticky; top: 0; text-align: left; padding: 8px 6px; border-bottom: 2px solid var(--border); background: #fff; color: var(--text-light); font-weight: 600; }
.rxn-table td { padding: 7px 6px; border-bottom: 1px solid var(--border); color: #333; }
.rxn-table .rxn-cas { font-family: var(--mono); font-size: 11px; color: var(--text-light); max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rxn-table .rxn-text { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rxn-table tbody tr:hover { background: #f8fafc; }
@media (max-width: 960px) {
  .kg-layout { grid-template-columns: minmax(0, 1fr); }
  .kg-detail { display: grid; grid-template-columns: 1fr 1fr; column-gap: 16px; }
  .kg-detail h3 { grid-column: 1 / -1; margin-bottom: 8px; }
  .kg-detail-close { top: 12px; }
  .kg-focus-btn { grid-column: 1 / -1; }
  .kg-canvas { height: 62vh; min-height: 420px; }
}
@media (max-width: 600px) {
  .kg-toolbar { align-items: stretch; }
  .kg-search { flex-basis: 100%; max-width: none; }
  .kg-count { flex-basis: 100%; margin-left: 0; }
  .kg-canvas { height: 58vh; min-height: 360px; }
}
</style>
