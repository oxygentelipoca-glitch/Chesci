<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import * as echarts from 'echarts'
import { getGraph, getReactions } from '../api/chemistry.js'

const chartRef = ref(null)
const selected = ref(null)
const empty = ref(false)
const searchQuery = ref('')
const allNodes = ref([])
const allLinks = ref([])
let chart = null

const reactions = ref([])

onMounted(async () => {
  try {
    const data = await getGraph()
    if (!data.nodes?.length) { empty.value = true; return }
    allNodes.value = data.nodes
    allLinks.value = data.links
    await nextTick()
    renderGraph(data.nodes, data.links, false)
  } catch (e) { empty.value = true }

  // 加载反应列表
  try {
    const r2 = await getReactions({ limit: 200 })
    reactions.value = (r2.items || r2.reactions || [])
  } catch (e) {}
})

watch(searchQuery, val => {
  if (!val.trim()) { renderGraph(allNodes.value, allLinks.value, false); return }
  const q = val.trim().toLowerCase()
  const matchedIds = new Set()
  allNodes.value.forEach(n => { if (n.name.toLowerCase().includes(q)) matchedIds.add(n.id) })
  if (matchedIds.size === 0) return

  // 找到匹配节点及其邻居
  const neighborIds = new Set(matchedIds)
  allLinks.value.forEach(l => {
    if (matchedIds.has(l.source) || matchedIds.has(l.target)) {
      neighborIds.add(l.source)
      neighborIds.add(l.target)
    }
  })

  const filteredNodes = allNodes.value.filter(n => neighborIds.has(n.id))
  const filteredLinks = allLinks.value.filter(l => neighborIds.has(l.source) && neighborIds.has(l.target))
  renderGraph(filteredNodes, filteredLinks, true, [...matchedIds])
})

function renderGraph(nodes, links, isFiltered, highlightIds = []) {
  if (!chartRef.value) return
  if (chart) chart.dispose()
  chart = echarts.init(chartRef.value)

  const productCount = {}
  links.forEach(l => { productCount[l.target] = (productCount[l.target] || 0) + 1 })
  const maxProduct = Math.max(...Object.values(productCount), 1)

  const categories = [
    { name: '反应物', itemStyle: { color: '#7EB8C9' } },
    { name: '产物', itemStyle: { color: '#065F46' } },
    { name: '反应物/产物', itemStyle: { color: '#4A90A4' } },
    { name: '催化剂', itemStyle: { color: '#B8A07C' } },
    { name: '溶剂', itemStyle: { color: '#8899AA' } },
  ]
  const catMap = { reactant: 0, product: 1, both: 2, catalyst: 3, solvent: 4 }

  const graphNodes = nodes.map(n => {
    const cat = catMap[n.category] ?? 0
    const size = n.symbolSize || (cat === 3 ? 18 : 32)
    const isHighlight = highlightIds.includes(n.id)
    return {
      ...n, category: cat, symbolSize: isHighlight ? size + 12 : size,
      itemStyle: isHighlight ? { borderColor: '#F59E0B', borderWidth: 3, shadowBlur: 16, shadowColor: 'rgba(245,158,11,0.4)' } : {},
      label: { show: false },
    }
  })

  // 统计同一 source→target 的边数，分配不同曲率避免重叠
  const edgeGroups = {}
  links.forEach(l => {
    const key = `${l.source}->${l.target}`
    if (!edgeGroups[key]) edgeGroups[key] = []
    edgeGroups[key].push(l)
  })

  const graphLinks = []
  Object.values(edgeGroups).forEach(group => {
    group.forEach((l, i) => {
      // 交替正负曲率：0.25, -0.25, 0.4, -0.4...
      const curv = (i % 2 === 0 ? 0.25 + Math.floor(i/2) * 0.2 : -(0.25 + Math.floor(i/2) * 0.2))
      const colors = ['#4A90A4', '#7EB8C9', '#B8A07C', '#163A5F']
      graphLinks.push({
        ...l,
        label: { show: true, fontSize: 9, color: '#8899AA', formatter: l.label?.length > 6 ? l.label.slice(0,6)+'…' : l.label },
        lineStyle: { color: colors[i % colors.length], width: 1.8, curveness: curv, opacity: 0.7 },
      })
    })
  })

  chart.setOption({
    backgroundColor: '#FAFBFC',
    animationDuration: 800,
    tooltip: {
      trigger: 'item',
      formatter: p => p.dataType === 'node'
        ? `<div style="font-weight:700;font-size:14px">${p.name}</div>`
          + (p.data.category ? `<div style="color:#666;font-size:12px">${['反应物','产物','反应物/产物','催化剂','溶剂'][catMap[p.data.category] ?? 0]}</div>` : '')
          + `<div style="color:#888;font-size:11px">${p.data.reaction_count || 1} 次出现</div>`
        : `<div style="font-size:13px">${p.data.label}</div>`
    },
    legend: { bottom: 8, data: categories.map(c => c.name), textStyle: { fontSize: 11, color: '#6B7C93' } },
    series: [{
      type: 'graph', layout: 'force', roam: true, draggable: true,
      zoom: isFiltered ? 1.2 : 0.8,
      scaleLimit: { min: 0.2, max: 5 },
      force: {
        repulsion: isFiltered ? 400 : 500,
        gravity: 0.02,
        edgeLength: isFiltered ? [180, 320] : [220, 400],
        friction: 0.15,
        layoutAnimation: true,
      },
      data: graphNodes, links: graphLinks, categories,
      label: { show: false },
      edgeLabel: { show: true, fontSize: 9, distance: 8 },
      edgeSymbol: ['none', 'arrow'], edgeSymbolSize: [0, 8],
      emphasis: { scale: 1.3, label: { show: true, fontSize: 16, fontWeight: 700 }, lineStyle: { width: 3 } },
      itemStyle: { borderColor: '#fff', borderWidth: 2, shadowBlur: 4, shadowColor: 'rgba(0,0,0,0.06)' },
      lineStyle: { opacity: 0.5 },
    }]
  })

  // 点击节点
  chart.off('click')
  chart.on('click', params => {
    if (params.dataType === 'node') {
      selected.value = allNodes.value.find(n => n.id === params.data.id) || params.data
    }
  })

  new ResizeObserver(() => chart.resize()).observe(chartRef.value)
}
</script>

<template>
  <MainLayout>
    <div class="kg-root">
      <h2>知识图谱可视化</h2>
      <p class="subtitle">搜索化合物查看关联反应 · 滚轮缩放 · 拖拽探索</p>

      <div class="kg-toolbar">
         <input v-model="searchQuery" placeholder="🔍 搜索化合物，如：Piperidine、Pyridine、Acid..." class="kg-search" />
        <button v-if="searchQuery" class="kg-clear" @click="searchQuery = ''">✕ 清除</button>
        <span class="kg-count">{{ searchQuery ? '筛选模式' : '全部' }} · {{ allNodes.length }} 节点 {{ allLinks.length }} 边</span>
      </div>

      <div v-if="empty" class="empty-state">
        <p>📭 图谱数据为空</p>
        <p class="hint">在「路线规划」中上传化学反应式后，知识图谱将自动构建</p>
      </div>
      <div v-else class="kg-layout">
        <div class="kg-canvas" ref="chartRef"></div>
         <div v-if="selected" class="kg-detail">
           <h3>🧪 {{ selected.name }}</h3>
           <table>
             <tr><td>分类</td><td>{{ {reactant:'反应物',product:'产物',both:'反应物/产物',catalyst:'催化剂',solvent:'溶剂'}[selected.category] || selected.category }}</td></tr>
             <tr><td>出现次数</td><td>{{ selected.reaction_count || 1 }}</td></tr>
             <tr v-if="selected.color"><td>颜色</td><td><span :style="{display:'inline-block',width:16,height:16,borderRadius:3,background:selected.color}"></span></td></tr>
           </table>
           <button class="kg-focus-btn" @click="searchQuery = selected.name">🔗 聚焦此化合物</button>
        </div>
      </div>

      <!-- 反应列表 -->
      <div class="reaction-list" v-if="reactions.length">
        <h3>📋 反应列表 ({{ reactions.length }} 条)</h3>
        <table class="rxn-table">
          <thead>
            <tr>
              <th>ID</th><th>CAS</th><th>反应物</th><th>产物</th><th>收率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in reactions" :key="r.id">
              <td>{{ r.id || r.reaction_id || '-' }}</td>
              <td class="rxn-cas">{{ r.cas_registry_id || '-' }}</td>
              <td class="rxn-text">{{ r.reactants_text || (r.reactants||[]).join(', ') || '-' }}</td>
              <td class="rxn-text">{{ r.products_text || (r.products||[]).join(', ') || '-' }}</td>
              <td>{{ r.yield_ != null ? r.yield_ + '%' : (r.yield_text || '-') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </MainLayout>
</template>

<style scoped>
.kg-root { }
.kg-root h2 { font-size: 18px; font-weight: 700; color: var(--primary); margin-bottom: 4px; }
.subtitle { color: var(--text-light); font-size: 13px; margin-bottom: 12px; }

.kg-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.kg-search { flex: 1; max-width: 420px; padding: 9px 14px; border: 1.5px solid var(--border); border-radius: var(--radius); font-size: 13px; outline: none; }
.kg-search:focus { border-color: var(--primary-light); }
.kg-clear { padding: 8px 14px; border: 1px solid var(--border); border-radius: var(--radius); background: #fff; color: var(--text-light); cursor: pointer; font-size: 12px; }
.kg-clear:hover { background: #fef2f2; color: #dc2626; }
.kg-count { font-size: 12px; color: var(--text-light); margin-left: auto; }

.kg-layout { display: flex; gap: 18px; }
.kg-canvas { flex: 1; height: 540px; background: #fff; border: 1px solid var(--border); border-radius: var(--radius); }
.kg-detail { width: 220px; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px; flex-shrink: 0; }
.kg-detail h3 { font-size: 14px; margin-bottom: 10px; color: var(--primary); }
.kg-detail table { width: 100%; font-size: 12px; }
.kg-detail td { padding: 4px 0; border-bottom: 1px solid var(--border); }
.kg-detail td:first-child { color: var(--text-light); width: 50px; }
.kg-focus-btn { margin-top: 10px; width: 100%; padding: 7px; border: 1px solid var(--primary-light); border-radius: var(--radius); background: var(--primary-pale); color: var(--primary); font-size: 12px; cursor: pointer; }

.empty-state { text-align: center; padding: 80px 24px; color: var(--text-light); }
.empty-state .hint { font-size: 13px; margin-top: 8px; }

.reaction-list { margin-top: 24px; background: #fff; border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; }
.reaction-list h3 { font-size: 15px; color: var(--primary); margin-bottom: 12px; }
.rxn-table { width: 100%; font-size: 12px; border-collapse: collapse; }
.rxn-table th { text-align: left; padding: 8px 6px; border-bottom: 2px solid var(--border); color: var(--text-light); font-weight: 600; }
.rxn-table td { padding: 7px 6px; border-bottom: 1px solid var(--border); color: #333; }
.rxn-table .rxn-cas { font-family: var(--mono); font-size: 11px; color: var(--text-light); max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rxn-table .rxn-text { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rxn-table tbody tr:hover { background: #f8fafc; }
@media (max-width: 768px) { .kg-layout { flex-direction: column; } .kg-detail { width: 100%; } }
</style>
