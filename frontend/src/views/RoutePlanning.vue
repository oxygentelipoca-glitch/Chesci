<script setup>
import { ref } from 'vue'
import { useReactionSearch } from '../composables/useReactionSearch.js'
import ReactionCard from '../components/ReactionCard.vue'
import { generateExperimentPlan } from '../api/chemistry.js'
import MainLayout from '../layouts/MainLayout.vue'

const {
  query, loading, searchResults, result, reactions,
  upstream, downstream, compound, error,
  handleSearch, runAnalysis, scoreFor,
} = useReactionSearch()

// 页面局部状态：步骤进度 + 选中卡片
const steps = ref([])
const activeRoute = ref(0)
const startingMaterial = ref('')
const minYield = ref('')
const maxTemperature = ref('')
const maxSteps = ref('')
const planLoading = ref(false)
const experimentPlan = ref(null)

const rankedReactions = () => {
  if (Array.isArray(result.value?.filter_matches?.items)) {
    return result.value.filter_matches.items
  }
  return reactions.value
}

function useDemoCase() {
  startingMaterial.value = '苯甲醛'
  query.value = '肉桂酸'
}

async function startAnalysis(cname) {
  const target = cname || query.value.trim()
  if (!target) return
  steps.value = [{ label: '正在分析合成路线', status: 'active' }]
  activeRoute.value = 0
  experimentPlan.value = null

  const constraints = {
    starting_material: startingMaterial.value.trim() || undefined,
    min_yield: minYield.value !== '' ? Number(minYield.value) : undefined,
    max_temperature: maxTemperature.value !== '' ? Number(maxTemperature.value) : undefined,
    max_steps: maxSteps.value !== '' ? Number(maxSteps.value) : undefined,
  }
  const d = await runAnalysis(target, constraints)
  if (d) {
    steps.value[0].status = 'done'
    steps.value[0].detail = `✔ 找到 ${d.reactions?.length || 0} 条相关反应`
    steps.value.push({ label: '生成分析报告', status: 'done', detail: '✔ 报告已生成' })
  } else {
    steps.value[0].status = 'done'
    steps.value[0].detail = '✘ 分析失败'
  }
}

async function createPlan(reaction) {
  planLoading.value = true
  experimentPlan.value = null
  try {
    const literatureContext = (result.value?.literature?.sources || [])
      .map((source, index) => `[${index + 1}] ${source.title || '未命名文献'}；${source.authors || ''}；${source.journal || ''}；${source.year || ''}；DOI: ${source.doi || '未提供'}`)
      .join('\n')
    experimentPlan.value = await generateExperimentPlan({
      compound: { name: query.value.trim(), starting_material: startingMaterial.value.trim() },
      route: {
        name: reaction.reaction_type || reaction.literature_title || `反应 ${reaction.id}`,
        type: reaction.reaction_type || '未提供',
        equation: reaction.equation_zh || reaction.equation || `${reaction.reactants_zh || reaction.reactants_text || ''} → ${reaction.products_zh || reaction.products_text || ''}`,
        yield: String(reaction.yield_ ?? reaction.yield_val ?? '未提供').replace('%', ''),
        catalyst: (reaction.conditions_summary || []).map(c => c.catalysts).filter(Boolean).join('；') || '未提供',
        solvent: (reaction.conditions_summary || []).map(c => c.solvents).filter(Boolean).join('；') || '未提供',
        temperature: (reaction.conditions_summary || []).map(c => c.temperature).filter(Boolean).join('；') || '未提供',
        time: (reaction.conditions_summary || []).map(c => c.time).filter(Boolean).join('；') || '未提供',
        literature_title: reaction.literature_title || '',
      },
      literature_context: literatureContext,
    })
  } catch (e) {
    experimentPlan.value = { error: e.response?.data?.message || '方案生成失败，请稍后重试。' }
  } finally {
    planLoading.value = false
  }
}
</script>

<template>
  <MainLayout>
    <div class="rp-root">
      <!-- Input Panel -->
      <div class="input-panel">
        <div class="ip-header">
          <h2>合成路线规划</h2>
          <p>结合起始原料与实验室条件筛选候选反应，查看来源并生成方案草案</p>
        </div>
        <div class="demo-row"><span>演示案例：苯甲醛 → 肉桂酸</span><button type="button" @click="useDemoCase">填入案例</button></div>
        <div class="ip-row">
          <div class="ip-search">
            <label class="field"><span>起始原料</span><input v-model="startingMaterial" placeholder="例如：苯甲醛（可选）" /></label>
            <label class="field"><span>目标产物</span><input v-model="query" @keyup.enter="startAnalysis()" @input="handleSearch" placeholder="例如：肉桂酸或 CAS 号" /></label>
            <button @click="startAnalysis()" :disabled="loading">{{ loading ? '分析中...' : '开始分析' }}</button>
          </div>
        </div>
        <details class="constraint-panel">
          <summary>实验室条件筛选（可选）</summary>
          <div class="constraint-grid">
            <label class="field"><span>最低收率 (%)</span><input v-model="minYield" type="number" min="0" max="100" placeholder="不限" /></label>
            <label class="field"><span>最高温度 (°C)</span><input v-model="maxTemperature" type="number" placeholder="不限" /></label>
            <label class="field"><span>最多反应步骤</span><input v-model="maxSteps" type="number" min="1" placeholder="不限" /></label>
          </div>
          <p class="constraint-note">当前先按反应数据库中的文本和条件字段匹配；未录入的实验室设备或试剂信息不会被系统假定。</p>
        </details>
        <!-- Quick search results -->
        <div v-if="searchResults.length && !loading" class="quick-drop">
          <div v-for="c in searchResults" :key="c.id" class="qd-item" @click="startAnalysis(c.cas_registry_id || query.trim())">
            <span class="qd-cas">{{ c.cas_registry_id || '—' }}</span>
            <span class="qd-eq">{{ c.reactants_text || '?' }} → {{ c.products_text || '?' }}</span>
          </div>
        </div>
      </div>

      <!-- Analysis Steps -->
      <div v-if="loading || steps.length" class="steps-panel">
        <div v-for="(s, i) in steps" :key="i" class="step-row" :class="s.status">
          <div class="step-dot"></div>
          <div class="step-info">
            <strong>Step {{ i + 1 }}</strong>
            <span>{{ s.label }}</span>
          </div>
          <span class="step-detail">{{ s.detail || '处理中...' }}</span>
        </div>
      </div>

      <!-- Results -->
      <div v-if="result && !error && !loading" class="results-area">
        <!-- Route Tree -->
        <div class="result-left">
          <h3>路线树</h3>
          <div class="route-tree">
            <div class="tree-node" v-for="(u, i) in upstream" :key="i">
              <div class="tn-compound">{{ u.compound }}</div>
              <div class="tn-arrow">↓</div>
              <div class="tn-reaction">{{ u.reaction }}</div>
            </div>
            <div class="tn-arrow">↓</div>
            <div class="tn-target">🎯 {{ compound?.name || query }}</div>
            <p v-if="result.starting_material" class="route-source">筛选起始原料：{{ result.starting_material }}</p>
            <div v-if="downstream.length" class="tn-arrow">↓</div>
            <div class="tree-node" v-for="(d, i) in downstream" :key="'d' + i">
              <div class="tn-reaction">{{ d.reaction }}</div>
              <div class="tn-arrow">↓</div>
              <div class="tn-compound">{{ d.compound }}</div>
            </div>
          </div>
        </div>

        <!-- Route Cards -->
        <div class="result-right">
          <h3>路线评分</h3>
          <div class="route-cards">
            <ReactionCard
              v-for="(reaction, idx) in rankedReactions()"
              :key="reaction.id"
              :reaction="reaction"
              :score="scoreFor(reaction.id)"
              :rank="idx + 1"
              :selected="activeRoute === idx"
              :show-generate-btn="true"
              :generating="planLoading"
              @select="activeRoute = idx"
              @generate="createPlan"
            />
            <p v-if="!rankedReactions().length" class="no-routes">当前数据库中没有同时匹配目标产物、起始原料和筛选条件的反应记录。可放宽条件或检查导入数据。</p>
          </div>

          <section v-if="result.literature?.sources?.length" class="literature-panel">
            <h3>相关文献</h3>
            <article v-for="(paper, index) in result.literature.sources" :key="`${paper.title}-${index}`" class="paper-row">
              <strong>{{ paper.title || '未提供标题' }}</strong>
              <span>{{ [paper.authors, paper.journal, paper.year].filter(Boolean).join(' · ') || '文献信息不完整' }}</span>
              <a v-if="paper.doi" :href="`https://doi.org/${paper.doi}`" target="_blank" rel="noopener noreferrer">DOI: {{ paper.doi }}</a>
            </article>
          </section>

          <div v-if="experimentPlan" class="plan-panel">
            <h3>实验方案草案</h3>
            <p v-if="experimentPlan.review_notice" class="plan-notice">{{ experimentPlan.review_notice }}</p>
            <p v-if="experimentPlan.error" class="plan-error">{{ experimentPlan.error }}</p>
            <pre v-else>{{ experimentPlan.plan }}</pre>
          </div>

          <!-- LLM Analysis Report -->
          <div v-if="result.answer" class="answer-panel">
            <h3>🤖 AI 分析报告</h3>
            <div class="answer-content" v-html="result.answer.replace(/\n/g, '<br>')"></div>
          </div>
        </div>
      </div>

      <!-- Error -->
      <div v-if="error" class="error-toast">{{ error }}</div>

      <!-- Data source hint -->
      <div class="data-hint">
        💡 反应数据来自 SciFinder PDF 提取结果（reactions.db），可通过
        <code>scripts/extract_scifinder_llm.py --import-db</code> 导入新数据。
      </div>

      <!-- Empty -->
      <div v-if="!result && !loading && !steps.length" class="empty-hint">👆 在上方输入目标化合物开始分析</div>
    </div>
  </MainLayout>
</template>

<style scoped>
.rp-root { max-width: 1100px; }

/* Input */
.input-panel { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 24px; margin-bottom: 20px; box-shadow: var(--shadow); }
.ip-header h2 { font-size: 18px; font-weight: 700; color: var(--primary); margin-bottom: 4px; }
.ip-header p { font-size: 13px; color: var(--text-light); margin-bottom: 16px; }
.ip-row { display: flex; gap: 12px; margin-bottom: 12px; }
.ip-search { flex: 1; display: grid; grid-template-columns: 1fr 1fr auto; gap: 12px; align-items: end; }
.field { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--text-light); }
.field input { width: 100%; box-sizing: border-box; padding: 10px 12px; border: 1.5px solid var(--border); border-radius: var(--radius); font-size: 14px; outline: none; }
.field input:focus { border-color: var(--primary-light); }
.ip-search button { padding: 10px 28px; background: var(--primary); color: #fff; border: none; border-radius: var(--radius); font-weight: 600; cursor: pointer; white-space: nowrap; }
.ip-search button:disabled { opacity: 0.6; cursor: not-allowed; }
.demo-row { display: flex; align-items: center; justify-content: space-between; margin: 10px 0 14px; color: var(--text-light); font-size: 12px; }
.demo-row button { border: 0; background: transparent; color: var(--primary); font-weight: 600; cursor: pointer; }
.constraint-panel { border-top: 1px solid var(--border); padding-top: 12px; color: var(--text); font-size: 13px; }
.constraint-panel summary { cursor: pointer; font-weight: 600; }
.constraint-grid { display: grid; grid-template-columns: repeat(3, minmax(120px, 1fr)); gap: 12px; margin-top: 14px; }
.constraint-note { color: var(--text-light); font-size: 11px; margin: 12px 0 0; }
.route-source { color: var(--text-light); font-size: 12px; text-align: center; margin: 8px 0; }
.plan-panel { margin-top: 16px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--card); padding: 18px; }
.plan-panel h3 { margin: 0 0 10px; }
.plan-panel pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.65; }
.plan-notice { padding: 10px; background: #fffbeb; color: #92400e; border-radius: 8px; font-size: 12px; }
.plan-error { color: #991b1b; }

/* Quick drop */
.quick-drop { margin-top: 12px; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
.qd-item { padding: 8px 14px; cursor: pointer; display: flex; justify-content: space-between; font-size: 13px; border-bottom: 1px solid var(--border); transition: background 0.1s; }
.qd-item:hover { background: var(--primary-pale); }
.qd-cas { font-family: var(--mono); color: var(--text-light); font-size: 12px; }
.qd-eq { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); margin-left: 12px; }

/* Steps */
.steps-panel { display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
.step-row { display: flex; align-items: center; gap: 8px; padding: 12px 18px; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); flex: 1; min-width: 220px; }
.step-row.active { border-color: var(--primary-light); background: var(--primary-pale); }
.step-row.done { opacity: 0.7; }
.step-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--border); flex-shrink: 0; }
.step-row.active .step-dot { background: var(--primary-light); animation: pulse 1s infinite; }
.step-row.done .step-dot { background: var(--success); }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
.step-info { display: flex; flex-direction: column; gap: 2px; }
.step-info strong { font-size: 10px; color: var(--text-light); text-transform: uppercase; }
.step-info span { font-size: 13px; font-weight: 600; }
.step-detail { font-size: 11px; color: var(--text-light); margin-left: auto; }

/* Results */
.results-area { display: flex; gap: 20px; }
.result-left { width: 260px; flex-shrink: 0; }
.result-right { flex: 1; }
.results-area h3 { font-size: 14px; font-weight: 600; margin-bottom: 12px; color: var(--text); }

/* Route Tree */
.route-tree { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.tree-node { text-align: center; }
.tn-compound { padding: 8px 16px; background: var(--primary-pale); border: 1px solid var(--primary-light); border-radius: var(--radius); font-size: 13px; font-weight: 600; color: var(--primary); display: inline-block; }
.tn-reaction { padding: 4px 12px; font-size: 11px; color: var(--text-light); }
.tn-arrow { font-size: 16px; color: var(--primary-light); }
.tn-target { padding: 10px 20px; background: var(--primary); color: #fff; border-radius: var(--radius); font-weight: 700; font-size: 14px; display: inline-block; }

/* Route Cards (样式已迁移至 ReactionCard 组件) */
.route-cards { display: flex; flex-direction: column; gap: 10px; }
.no-routes { padding: 18px; border: 1px dashed var(--border); border-radius: var(--radius); color: var(--text-light); font-size: 13px; }
.literature-panel { margin-top: 18px; padding: 18px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--card); }
.literature-panel h3 { margin: 0 0 12px; }
.paper-row { display: flex; flex-direction: column; gap: 4px; padding: 10px 0; border-top: 1px solid var(--border); font-size: 12px; }
.paper-row strong { font-size: 13px; color: var(--text); }
.paper-row span { color: var(--text-light); }
.paper-row a { color: var(--primary); text-decoration: none; }

/* Answer panel */
.answer-panel { margin-top: 24px; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; }
.answer-panel h3 { font-size: 15px; font-weight: 600; color: var(--primary); margin-bottom: 12px; }
.answer-content { font-size: 14px; line-height: 1.8; color: #333; white-space: pre-wrap; }

.error-toast { max-width: 500px; margin: 24px auto; padding: 16px 24px; background: #fef2f2; color: #991b1b; border-radius: 12px; text-align: center; }

.empty-hint { text-align: center; padding: 60px 24px; color: var(--text-light); font-size: 15px; }

/* Data hint */
.data-hint { margin-top: 16px; padding: 10px 16px; background: var(--card); border: 1px dashed var(--border); border-radius: var(--radius); font-size: 12px; color: var(--text-light); }
.data-hint code { font-family: var(--mono); background: #F3F4F6; padding: 1px 6px; border-radius: 4px; }

@media (max-width: 768px) {
  .ip-search, .constraint-grid { grid-template-columns: 1fr; }
  .results-area { flex-direction: column; }
  .result-left { width: 100%; }
  .steps-panel { flex-direction: column; }
}
</style>
