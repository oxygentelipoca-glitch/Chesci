<script setup>
import { onMounted, ref } from 'vue'
import { getStats, getExtractionLogs } from '../api/chemistry.js'
import ReactionScheme from '../components/ReactionScheme.vue'

const stats = ref(null)
const logs = ref(null)
const statsError = ref(false)
const logsError = ref(false)
const statusLabels = { success:'已完成', failed:'失败', partial:'部分完成', pending:'等待处理' }
const metrics = [['反应记录', 'reactions'], ['反应图式', 'schemes'], ['来源文献', 'literatures']]
const tools = [
  { name:'知识图谱', path:'/knowledge-graph', detail:'沿化合物节点追踪反应关系' },
  { name:'文献检索', path:'/literature', detail:'在本地记录或学术索引中查找来源' },
  { name:'实验助手', path:'/experiment', detail:'依据反应数据整理实验方案草案' },
]
onMounted(() => {
  getStats().then(data => { stats.value = data }).catch(() => { statsError.value = true })
  getExtractionLogs({ limit:5 }).then(data => { logs.value = data.items || [] }).catch(() => { logsError.value = true })
})
</script>
<template>
  <MainLayout>
    <header class="page-intro"><h1>研究工作台</h1></header>
    <section class="case">
      <div><p class="case-label">合成路线演示</p><h2>从苯甲醛到肉桂酸</h2>
        <p class="case-copy">输入实验室条件，比较候选反应的收率、温度与文献依据。</p>
        <RouterLink class="primary-link" :to="{path:'/route-planning', query:{demo:'cinnamic-acid'}}">打开演示案例</RouterLink>
        <RouterLink class="plain-link" to="/route-planning">规划其他反应</RouterLink>
      </div>
      <ReactionScheme class="case-scheme" />
    </section>
    <div class="bench">
      <section class="records"><h2>反应数据库</h2>
        <dl class="metrics"><div v-for="[label,key] in metrics" :key="key"><dt>{{ label }}</dt><dd>{{ stats?.[key]?.toLocaleString() ?? '—' }}</dd></div></dl>
        <p v-if="statsError" class="muted">暂时无法读取数据库统计。</p>
        <h3>最近提取批次</h3>
        <p v-if="logsError" class="muted">暂时无法读取提取记录。</p>
        <p v-else-if="!logs" class="muted">正在读取提取记录…</p>
        <p v-else-if="!logs.length" class="muted">暂无提取记录。可在路线规划页导入第一份 PDF。</p>
        <ul v-else><li v-for="t in logs" :key="t.id ?? t.batch_number"><strong>批次 {{ t.batch_number }}</strong><span>{{ statusLabels[t.status] || t.status }} · {{ t.reactions_found }} 条反应</span><time>{{ t.created_at?.slice(0,10) }}</time></li></ul>
      </section>
      <section class="tools"><h2>研究工具</h2><RouterLink v-for="tool in tools" :key="tool.path" :to="tool.path"><span><strong>{{ tool.name }}</strong><small>{{ tool.detail }}</small></span><span aria-hidden="true">›</span></RouterLink></section>
    </div>
  </MainLayout>
</template>
<style scoped>
.case { display:grid; grid-template-columns:1.13fr 1fr; align-items:center; gap:30px; padding:clamp(24px,4vw,54px); background:#143d43; color:#f7fcf9; border-radius:16px }
.case-label { color:#b5ded0; font-size:14px; font-weight:600; margin-bottom:9px }
.case h2 { font-size:clamp(27px,3.5vw,48px); line-height:1.25; letter-spacing:-.055em }
.case-copy { color:#d6e6e5; margin:14px 0 24px }
.primary-link { background:#c2ecd7; color:#133d37 }
.primary-link:hover { background:#e3f6ea }
.plain-link { color:#eff8f4; margin-left:18px; border-bottom:1px solid #81a4a1 }
.case-scheme { color:#d7f2e8; border-left:1px solid #48686b; padding:12px 0 12px 22px }
.bench { margin-top:28px; display:grid; grid-template-columns:1.4fr 1fr; gap:clamp(22px,4vw,56px) }
.bench h2 { font-size:20px; margin-bottom:14px }
.metrics { display:grid; grid-template-columns:repeat(3,1fr); padding:18px 0; background:white; border:1px solid var(--border); border-radius:10px }
.metrics div { padding:0 18px; border-left:1px solid var(--border) }
.metrics div:first-child { border:0 }
dt,small,.muted,li span,time { color:var(--text-light) }
dd { font-size:30px; font-weight:600; font-variant-numeric:tabular-nums; line-height:1.2; margin-top:4px }
h3 { margin:20px 0 6px; font-size:15px }
ul { list-style:none }
li { display:flex; gap:10px; align-items:baseline; flex-wrap:wrap; border-bottom:1px solid var(--border); padding:9px 0 }
time { margin-left:auto; font-size:12px }
.tools a { display:flex; align-items:center; justify-content:space-between; border-top:1px solid var(--border); padding:11px 3px; color:var(--primary) }
.tools a:hover strong { text-decoration:underline }
.tools strong,.tools small { display:block }
.tools strong { font-size:16px }
.tools small { font-size:13px; margin-top:2px }
.tools a>span:last-child { font-size:23px }
@media(max-width:760px){.case,.bench { grid-template-columns:1fr }.case { gap:18px }.case-scheme { border-left:0; border-top:1px solid #48686b; padding:14px 0 0; max-width:430px }.metrics div { padding:0 12px }}
</style>
