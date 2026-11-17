<script setup>
import { reactive, ref, computed, onBeforeUnmount, onMounted } from 'vue'
import ConstraintEvidence from '../components/ConstraintEvidence.vue'
import MarkdownIt from 'markdown-it'
import { getReaction, getSearchHistory, deleteSearchHistory, clearSearchHistory } from '../api/chemistry.js'
import { useReactionSearch } from '../composables/useReactionSearch.js'

const md = new MarkdownIt({
  html: false,    // 禁用原始 HTML，防注入
  linkify: true,
  breaks: true,   // 单个换行转 <br>
})

const {
  query, loading, searchResults, result,
  handleSearch, runAnalysis,
} = useReactionSearch({ maxSuggestions: 8 })

const activeTab = ref('answer')
const selectedReaction = ref(null)

// ---- AI 分析报告（Markdown 渲染）----
const renderedAnswer = computed(() => {
  const ans = result.value?.answer
  if (!ans) return ''
  return md.render(ans)
})

// ---- 筛选条件 ----
const filters = reactive({
  minYield: null,     // 最低收率 %
  maxTemp: null,      // 最高温度 °C
  maxSteps: null,     // 最大步骤数
  maxTime: null,      // 最长反应时间（小时）
  catalyst: 'any',    // 是否使用催化剂：any / with / without
  catalystName: '',   // 催化剂名称关键词（如 Piperidine）
  workup: 'any',      // 是否有后处理：any / with / without
  solvent: 'any',     // 是否使用溶剂：any / with / without
  solventName: '',    // 溶剂名称关键词（如 Water）
  topN: 5,            // 返回最接近的前几项
})

const filterMatches = computed(() => result.value?.filter_matches || null)

const activeConditionCount = computed(() => {
  const f = filterMatches.value?.filters
  if (!f) return 0
  const valueCount = [f.min_yield, f.max_steps, f.max_temperature, f.max_time_hours]
    .filter(v => v != null).length
  const prefCount = [f.catalyst, f.workup, f.solvent]
    .filter(v => v != null && v !== 'any').length
  const nameCount = [f.catalyst_name, f.solvent_name]
    .filter(v => v != null && String(v).trim() !== '').length
  return valueCount + prefCount + nameCount
})

function toNum(v) {
  if (v === '' || v == null) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function filterPayload() {
  const p = {}
  const y = toNum(filters.minYield)
  const t = toNum(filters.maxTemp)
  const s = toNum(filters.maxSteps)
  const tm = toNum(filters.maxTime)
  if (y != null) p.min_yield = y
  if (t != null) p.max_temperature = t
  if (s != null) p.max_steps = s
  if (tm != null) p.max_time_hours = tm
  if (filters.catalyst !== 'any') p.catalyst = filters.catalyst
  if (filters.workup !== 'any') p.workup = filters.workup
  if (filters.solvent !== 'any') p.solvent = filters.solvent
  if (filters.catalyst !== 'without' && filters.catalystName?.trim()) p.catalyst_name = filters.catalystName.trim()
  if (filters.solvent !== 'without' && filters.solventName?.trim()) p.solvent_name = filters.solventName.trim()
  if (Object.keys(p).length) p.top_n = filters.topN
  return p
}

function resetFilters() {
  filters.minYield = null
  filters.maxTemp = null
  filters.maxSteps = null
  filters.maxTime = null
  filters.catalyst = 'any'
  filters.catalystName = ''
  filters.workup = 'any'
  filters.solvent = 'any'
  filters.solventName = ''
  filters.topN = 5
}

// ---- 分析进度条（分阶段模拟推进，响应返回后跳到 100%）----
const progress = ref(0)
const progressLabel = ref('')
let progressTimer = null

const PROGRESS_STAGES = [
  { until: 30, label: '检索反应数据库' },
  { until: 60, label: '多维评分与筛选' },
  { until: 90, label: '生成 AI 分析报告' },
]

function stageFor(p) {
  for (const s of PROGRESS_STAGES) {
    if (p < s.until) return s.label
  }
  return PROGRESS_STAGES[PROGRESS_STAGES.length - 1].label
}

function startProgress() {
  progress.value = 5
  progressLabel.value = stageFor(progress.value)
  clearInterval(progressTimer)
  progressTimer = setInterval(() => {
    if (progress.value >= 90) return // 停在 90%，等待后端响应
    progress.value = Math.min(progress.value + 3, 90)
    progressLabel.value = stageFor(progress.value)
  }, 300)
}

function finishProgress() {
  clearInterval(progressTimer)
  progressTimer = null
  progress.value = 100
  progressLabel.value = '分析完成'
  setTimeout(() => { progress.value = 0 }, 600)
}

onBeforeUnmount(() => clearInterval(progressTimer))

// ---- 搜索历史（当前用户独立）----
const historyItems = ref([])

async function fetchHistory() {
  try {
    const d = await getSearchHistory({ limit: 10 })
    historyItems.value = d.items || []
  } catch { historyItems.value = [] }
}

async function deleteHistory(id) {
  try {
    await deleteSearchHistory(id)
    historyItems.value = historyItems.value.filter(h => h.id !== id)
  } catch { /* 忽略删除失败 */ }
}

async function clearAllHistory() {
  try {
    await clearSearchHistory()
    historyItems.value = []
  } catch { /* 忽略清空失败 */ }
}

// 恢复历史搜索（含筛选条件）并重新分析
function applyHistory(item) {
  query.value = item.query || ''
  const f = item.filters || {}
  filters.minYield = f.min_yield != null ? f.min_yield : null
  filters.maxTemp = f.max_temperature != null ? f.max_temperature : null
  filters.maxSteps = f.max_steps != null ? f.max_steps : null
  filters.maxTime = f.max_time_hours != null ? f.max_time_hours : null
  filters.catalyst = f.catalyst || 'any'
  filters.catalystName = f.catalyst_name || ''
  filters.workup = f.workup || 'any'
  filters.solvent = f.solvent || 'any'
  filters.solventName = f.solvent_name || ''
  filters.topN = f.top_n || 5
  startAnalysis()
}

onMounted(fetchHistory)

// Run analysis
async function startAnalysis(suggestion) {
  startProgress()
  await runAnalysis(suggestion, filterPayload())
  finishProgress()
}

// View reaction detail
async function viewReaction(id) {
  try {
    selectedReaction.value = await getReaction(id)
  } catch { selectedReaction.value = null }
}
</script>

<template>
  <MainLayout>
    <div class="exp-root">
      <header class="page-intro"><h1>实验助手</h1><p>按化合物名称或 CAS 号检索反应，依据选定路线生成实验方案草案。</p></header>

      <div class="exp-search">
        <div class="es-row">
          <input
            aria-label="目标化合物"
            v-model="query"
            @keyup.enter="startAnalysis()"
            @input="handleSearch"
            placeholder="输入化合物名称或 CAS Registry ID，如：cinnamic acid / 31-333-CAS-20579053"
            :disabled="loading"
          />
          <button @click="startAnalysis()" :disabled="loading">
            {{ loading ? '分析中...' : '开始分析' }}
          </button>
        </div>
        <div v-if="searchResults.length && !loading" class="es-dropdown">
          <div v-for="item in searchResults" :key="item.id" class="esd-item" @click="startAnalysis(item.cas_registry_id || item.reactants_text)">
            <span class="esd-cas">{{ item.cas_registry_id || '—' }}</span>
            <span v-if="item.reactants_text" class="esd-text">{{ item.reactants_text }} → {{ item.products_text }}</span>
            <span v-if="item.literature_title" class="esd-lit">{{ item.literature_title?.slice(0, 40) }}</span>
          </div>
        </div>
      </div>

      <!-- Filter conditions -->
      <details class="es-filters" open>
        <summary>筛选条件（可选，留空则忽略）</summary>
        <div class="esf-grid">
          <label class="esf-item">
            <span>最低收率</span>
            <input v-model="filters.minYield" type="number" min="0" max="100" placeholder="如 80" />
            <em>%</em>
          </label>
          <label class="esf-item">
            <span>最高温度</span>
            <input v-model="filters.maxTemp" type="number" min="-100" max="1000" placeholder="如 100" />
            <em>°C</em>
          </label>
          <label class="esf-item">
            <span>最大步骤</span>
            <input v-model="filters.maxSteps" type="number" min="1" max="20" placeholder="如 3" />
          </label>
          <label class="esf-item">
            <span>最长单段时间</span>
            <input v-model="filters.maxTime" type="number" min="0" placeholder="如 6" />
            <em>h</em>
          </label>
          <label class="esf-item">
            <span>催化剂</span>
            <select v-model="filters.catalyst">
              <option value="any">不限</option>
              <option value="with">使用催化剂</option>
              <option value="without">不使用催化剂</option>
            </select>
            <input
              v-model="filters.catalystName"
              type="text"
              placeholder="名称，如 Piperidine"
              :disabled="filters.catalyst === 'without'"
            />
          </label>
          <label class="esf-item">
            <span>后处理</span>
            <select v-model="filters.workup">
              <option value="any">不限</option>
              <option value="with">有后处理</option>
              <option value="without">无后处理</option>
            </select>
          </label>
          <label class="esf-item">
            <span>溶剂</span>
            <select v-model="filters.solvent">
              <option value="any">不限</option>
              <option value="with">使用溶剂</option>
              <option value="without">不使用溶剂</option>
            </select>
            <input
              v-model="filters.solventName"
              type="text"
              placeholder="名称，如 Water"
              :disabled="filters.solvent === 'without'"
            />
          </label>
          <label class="esf-item">
            <span>显示前</span>
            <select v-model.number="filters.topN">
              <option :value="3">3 项</option>
              <option :value="5">5 项</option>
              <option :value="10">10 项</option>
            </select>
          </label>
        </div>
        <button class="esf-reset" @click="resetFilters">重置筛选</button>
      </details>

      <!-- Search history -->
      <div v-if="historyItems.length" class="er-history">
        <div class="erh-header">
          <span>🕘 历史搜索</span>
          <button class="erh-clear" @click="clearAllHistory">清空</button>
        </div>
        <div class="erh-list">
          <div v-for="h in historyItems" :key="h.id" class="erh-item">
            <div class="erh-main" @click="applyHistory(h)">
              <span class="erh-query">{{ h.query }}</span>
              <span class="erh-meta">{{ h.result_count }} 条结果 · {{ h.created_at ? h.created_at.slice(0, 16).replace('T', ' ') : '' }}</span>
            </div>
            <button class="erh-del" @click="deleteHistory(h.id)" title="删除此条">✕</button>
          </div>
        </div>
      </div>

      <!-- Analysis progress -->
      <div v-if="loading" class="er-progress">
        <div class="erp-bar">
          <div class="erp-fill" :style="{ width: progress + '%' }"></div>
        </div>
        <div class="erp-info">
          <span>{{ progressLabel }}</span>
          <span>{{ progress }}%</span>
        </div>
      </div>

      <!-- Results -->
      <div v-if="result" class="exp-result">
        <!-- Stats bar -->
        <div class="er-stats">
          <div class="ers-item">匹配反应: <strong>{{ result.reactions?.length || 0 }}</strong></div>
          <div class="ers-item">相关 Scheme: <strong>{{ result.schemes?.length || 0 }}</strong></div>
          <div class="ers-item">评分: <strong>{{ result.scored?.length || 0 }}</strong> 条</div>
        </div>

        <!-- Tabs -->
        <div class="er-tabs">
          <button :class="{ active: activeTab === 'answer' }" @click="activeTab = 'answer'">AI 分析报告</button>
          <button :class="{ active: activeTab === 'reactions' }" @click="activeTab = 'reactions'">匹配反应 ({{ result.reactions?.length || 0 }})</button>
          <button :class="{ active: activeTab === 'scored' }" @click="activeTab = 'scored'">评分排名 ({{ result.scored?.length || 0 }})</button>
          <button :class="{ active: activeTab === 'schemes' }" @click="activeTab = 'schemes'">相关 Scheme ({{ result.schemes?.length || 0 }})</button>
          <button v-if="filterMatches" :class="{ active: activeTab === 'filters' }" @click="activeTab = 'filters'">🎯 条件匹配 ({{ filterMatches.items?.length || 0 }})</button>
        </div>

        <!-- AI Answer -->
        <div v-if="activeTab === 'answer'">
          <div class="er-answer markdown-body" v-html="renderedAnswer || '暂无 AI 分析报告，请查看下方数据。'"></div>

          <!-- References from reactions.db -->
          <div v-if="result.literature?.sources?.length" class="er-refs">
            <h4>📚 参考文献（reactions.db 查询结果，共 {{ result.literature.total }} 篇，展示前 {{ result.literature.sources.length }} 篇）</h4>
            <ol class="er-refs-list">
              <li v-for="(lit, i) in result.literature.sources" :key="i">
                <div class="er-ref-title">[{{ i + 1 }}] {{ lit.title }}</div>
                <div class="er-ref-meta">
                  <span v-if="lit.authors">{{ lit.authors }}</span>
                  <span v-if="lit.journal">{{ lit.journal }}</span>
                  <span v-if="lit.year">{{ lit.year }}</span>
                  <span v-if="lit.volume">vol. {{ lit.volume }}</span>
                  <span v-if="lit.pages">pp. {{ lit.pages }}</span>
                  <span v-if="lit.doi" class="er-ref-doi">DOI: {{ lit.doi }}</span>
                </div>
              </li>
            </ol>
          </div>
        </div>

        <!-- Reactions -->
        <div v-if="activeTab === 'reactions'">
          <div class="er-empty" v-if="!result.reactions?.length">未找到匹配反应</div>
          <div v-for="r in result.reactions" :key="r.id" class="er-card" @click="viewReaction(r.id)">
            <div class="erc-header">
              <span class="erc-cas">{{ r.cas_registry_id || '—' }}</span>
              <span class="erc-yield" v-if="r.yield_">{{ r.yield_ }}</span>
            </div>
            <div class="erc-body">
              <span v-if="r.reactants_text">反应物: {{ r.reactants_text }}</span>
              <span v-if="r.products_text"> → 产物: {{ r.products_text }}</span>
            </div>
            <div class="erc-conds" v-if="r.conditions_summary?.length">
              <span v-for="c in r.conditions_summary.slice(0,3)" :key="c.step" class="cond-tag">
                {{ c.temperature || c.time || c.catalysts || c.solvents || '' }}
              </span>
            </div>
            <div class="erc-lit" v-if="r.literature_title">
              📄 {{ r.literature_title }} ({{ r.literature_journal }}, {{ r.literature_year }})
            </div>
          </div>
        </div>

        <!-- Scored -->
        <div v-if="activeTab === 'scored'">
          <div class="er-empty" v-if="!result.scored?.length">暂无评分</div>
          <div v-for="s in result.scored" :key="s.reaction_id" class="er-card">
            <div class="erc-header">
              <span class="erc-cas">{{ s.cas_registry_id || '—' }}</span>
              <span class="erc-score" :style="{ color: s.total > 70 ? '#065F46' : s.total > 50 ? '#92400E' : '#991B1B' }">
                {{ s.total }} 分
              </span>
            </div>
            <div class="er-bars">
              <div class="bar-row"><span class="bar-lbl">收率</span><div class="bar-trk"><div class="bar-fil" :style="{ width: s.yield_score + '%' }"></div></div><span class="bar-val">{{ s.yield_score }}</span></div>
              <div class="bar-row"><span class="bar-lbl">步骤</span><div class="bar-trk"><div class="bar-fil" :style="{ width: s.step_score + '%', background: '#10B981' }"></div></div><span class="bar-val">{{ s.step_score }}</span></div>
              <div class="bar-row"><span class="bar-lbl">温度</span><div class="bar-trk"><div class="bar-fil" :style="{ width: s.temp_score + '%', background: '#F59E0B' }"></div></div><span class="bar-val">{{ s.temp_score }}</span></div>
              <div class="bar-row"><span class="bar-lbl">安全</span><div class="bar-trk"><div class="bar-fil" :style="{ width: s.safety_score + '%', background: '#EF4444' }"></div></div><span class="bar-val">{{ s.safety_score }}</span></div>
            </div>
          </div>
        </div>

        <!-- Schemes -->
        <div v-if="activeTab === 'schemes'">
          <div class="er-empty" v-if="!result.schemes?.length">无关联 Scheme</div>
          <div v-for="sch in result.schemes" :key="sch.id" class="er-scheme-card">
            <strong>Scheme #{{ sch.scheme_number }}</strong>
            <span>{{ sch.reaction_count }} 个反应</span>
            <span v-if="sch.overall_yield"> · 总收率: {{ sch.overall_yield }}</span>
            <span> · p.{{ sch.page_start }}{{ sch.page_end ? '-' + sch.page_end : '' }}</span>
          </div>
        </div>

        <!-- Filter Matches -->
        <div v-if="activeTab === 'filters' && filterMatches">
          <div class="erf-summary">
            🎯 满足全部 {{ activeConditionCount }} 项条件的反应 <strong>{{ filterMatches.total_exact }}</strong> 条
            <span class="erf-sub">共评估 {{ filterMatches.total_ranked }} 条 · 按条件满足度与综合评分排序，取前 {{ filterMatches.items?.length || 0 }} 项</span>
          </div>
          <div v-if="!filterMatches.items?.length" class="er-empty">没有满足筛选条件的反应，请放宽筛选条件</div>
          <div v-for="(item, idx) in filterMatches.items" :key="item.id" class="erf-card" @click="viewReaction(item.id)">
            <div class="erf-rank">#{{ idx + 1 }}</div>
            <div class="erf-main">
              <div class="erf-eq" :title="item.equation_zh || item.equation">
                {{ item.equation_zh || item.equation || item.cas_registry_id || ('反应 #' + item.id) }}
              </div>
              <div class="erf-tags">
                <ConstraintEvidence :checks="item.checks || []" />
                <span v-if="item.exact" class="erf-tag exact">✓ 完全匹配</span>
                <span v-else class="erf-tag partial">{{ item.matched_conditions }}/{{ activeConditionCount }} 项满足</span>
              </div>
            </div>
            <div class="erf-score" v-if="item.score">{{ item.score.total }} 分</div>
          </div>
        </div>
      </div>

      <!-- Selected Reaction Detail Modal -->
      <div v-if="selectedReaction" class="er-modal-overlay" @click="selectedReaction = null">
        <div class="er-modal" @click.stop>
          <h3>{{ selectedReaction.cas_registry_id || '反应详情' }}</h3>
          <button class="er-modal-close" @click="selectedReaction = null">✕</button>

          <div class="erm-section">
            <h4>基本信息</h4>
            <p>反应物: {{ selectedReaction.reactants_text || '—' }}</p>
            <p>产物: {{ selectedReaction.products_text || '—' }}</p>
            <p>收率: {{ selectedReaction.yield_ || '—' }}</p>
            <p>步骤数: {{ selectedReaction.steps || '—' }}</p>
            <p v-if="selectedReaction.reactant_smiles">反应物 SMILES: {{ selectedReaction.reactant_smiles }}</p>
            <p v-if="selectedReaction.product_smiles">产物 SMILES: {{ selectedReaction.product_smiles }}</p>
          </div>

          <div class="erm-section" v-if="selectedReaction.conditions?.length">
            <h4>反应条件</h4>
            <table class="erm-table">
              <thead>
                <tr><th>步骤</th><th>试剂</th><th>催化剂</th><th>溶剂</th><th>温度</th><th>时间</th></tr>
              </thead>
              <tbody>
                <tr v-for="c in selectedReaction.conditions" :key="c.id">
                  <td>{{ c.step_number }}</td>
                  <td>{{ (c.reagents||[]).join(', ') || '—' }}</td>
                  <td>{{ (c.catalysts||[]).join(', ') || '—' }}</td>
                  <td>{{ (c.solvents||[]).join(', ') || '—' }}</td>
                  <td>{{ c.temperature || '—' }}</td>
                  <td>{{ c.time || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="erm-section" v-if="selectedReaction.literature">
            <h4>文献</h4>
            <p><strong>{{ selectedReaction.literature.title }}</strong></p>
            <p>{{ selectedReaction.literature.authors }}</p>
            <p>{{ selectedReaction.literature.journal }}, {{ selectedReaction.literature.year }}, {{ selectedReaction.literature.volume }}, {{ selectedReaction.literature.pages }}</p>
          </div>
        </div>
      </div>
    </div>
  </MainLayout>
</template>

<style scoped>
.exp-root { max-width: 960px; }

.exp-search { position: relative; margin-bottom: 24px; }
.es-row { display: flex; gap: 10px; }
.es-row input { flex: 1; padding: 12px 16px; border: 1.5px solid var(--border); border-radius: var(--radius); font-size: 14px; outline: none; }
.es-row input:focus { border-color: var(--primary-light); }
.es-row button { padding: 12px 28px; background: var(--primary); color: #fff; border: none; border-radius: var(--radius); font-weight: 600; cursor: pointer; white-space: nowrap; }
.es-row button:disabled { opacity: 0.6; }

.es-dropdown { position: absolute; top: 100%; left: 0; right: 0; background: #fff; border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-lg); z-index: 10; max-height: 320px; overflow-y: auto; }
.esd-item { padding: 10px 14px; cursor: pointer; display: flex; gap: 12px; align-items: center; border-bottom: 1px solid var(--border); font-size: 13px; }
.esd-item:hover { background: #f0f7ff; }
.esd-cas { font-family: var(--mono); font-size: 11px; color: var(--primary); white-space: nowrap; }
.esd-text { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.esd-lit { font-size: 11px; color: var(--text-light); white-space: nowrap; }

.exp-result { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; }
.er-stats { display: flex; gap: 24px; margin-bottom: 16px; }
.ers-item { font-size: 13px; color: var(--text-light); }
.ers-item strong { color: var(--primary); font-size: 16px; }

.er-tabs { display: flex; gap: 6px; margin-bottom: 16px; border-bottom: 1px solid var(--border); padding-bottom: 10px; }
.er-tabs button { padding: 8px 16px; border: none; background: none; color: var(--text-light); font-size: 13px; cursor: pointer; border-bottom: 2px solid transparent; }
.er-tabs button.active { color: var(--primary); border-bottom-color: var(--primary); font-weight: 600; }

.er-answer { padding: 16px; background: #FFFBEB; border-radius: var(--radius); font-size: 14px; line-height: 1.8; }

/* Markdown 报告样式 */
.markdown-body :deep(h1), .markdown-body :deep(h2), .markdown-body :deep(h3), .markdown-body :deep(h4) { margin: 14px 0 8px; color: var(--primary); font-weight: 700; line-height: 1.4; }
.markdown-body :deep(h3) { font-size: 15px; border-bottom: 1px solid var(--border); padding-bottom: 4px; }
.markdown-body :deep(h4) { font-size: 13px; }
.markdown-body :deep(p) { margin: 6px 0; }
.markdown-body :deep(ul), .markdown-body :deep(ol) { padding-left: 22px; margin: 6px 0; }
.markdown-body :deep(li) { margin: 3px 0; }
.markdown-body :deep(strong) { font-weight: 700; color: #111827; }
.markdown-body :deep(table) { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13px; }
.markdown-body :deep(th), .markdown-body :deep(td) { border: 1px solid var(--border); padding: 6px 10px; text-align: left; }
.markdown-body :deep(th) { background: #F3F4F6; }
.markdown-body :deep(code) { font-family: var(--mono); background: #F3F4F6; padding: 1px 5px; border-radius: 4px; font-size: 12px; }
.markdown-body :deep(pre) { background: #1F2937; color: #F9FAFB; padding: 12px; border-radius: 8px; overflow-x: auto; margin: 8px 0; }
.markdown-body :deep(pre code) { background: none; color: inherit; padding: 0; }
.markdown-body :deep(blockquote) { border-left: 3px solid var(--primary-light); padding-left: 12px; color: var(--text-light); margin: 8px 0; }

/* References */
.er-refs { margin-top: 16px; padding: 16px; background: #fff; border: 1px solid var(--border); border-radius: var(--radius); }
.er-refs h4 { font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 10px; }
.er-refs-list { padding-left: 0; margin: 0; list-style: none; }
.er-refs-list li { margin-bottom: 12px; font-size: 13px; }
.er-ref-title { font-weight: 600; color: #111827; line-height: 1.5; }
.er-ref-meta { display: flex; gap: 10px; flex-wrap: wrap; font-size: 12px; color: var(--text-light); margin-top: 2px; }
.er-ref-doi { font-family: var(--mono); }
.er-empty { padding: 40px; text-align: center; color: var(--text-light); font-size: 14px; }

.er-card { padding: 14px; background: #fff; border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 8px; cursor: pointer; transition: all 0.12s; }
.er-card:hover { border-color: var(--primary-light); box-shadow: var(--shadow); }
.erc-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.erc-cas { font-family: var(--mono); font-size: 12px; color: var(--primary); font-weight: 600; }
.erc-yield { background: #D1FAE5; color: #065F46; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
.erc-score { font-size: 16px; font-weight: 700; }
.erc-body { font-size: 13px; color: #555; margin-bottom: 4px; }
.erc-conds { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 4px; }
.cond-tag { font-size: 11px; padding: 2px 6px; background: #F3F4F6; border-radius: 3px; color: #666; }
.erc-lit { font-size: 11px; color: var(--text-light); }

.er-bars { margin-top: 8px; }
.bar-row { display: flex; align-items: center; gap: 6px; margin-bottom: 3px; }
.bar-lbl { width: 30px; font-size: 10px; color: var(--text-light); }
.bar-trk { flex: 1; height: 5px; background: #E5E7EB; border-radius: 3px; }
.bar-fil { height: 100%; border-radius: 3px; background: #3B82F6; }
.bar-val { width: 20px; font-size: 10px; font-weight: 600; text-align: right; }

.er-scheme-card { padding: 10px 14px; background: #f0f7ff; border: 1px solid var(--primary-light); border-radius: var(--radius); margin-bottom: 6px; font-size: 13px; }
.er-scheme-card strong { color: var(--primary); margin-right: 10px; }

.er-modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.4); z-index: 100; display: flex; align-items: center; justify-content: center; }
.er-modal { background: #fff; border-radius: var(--radius); padding: 24px; max-width: 700px; width: 90%; max-height: 80vh; overflow-y: auto; position: relative; }
.er-modal h3 { font-size: 16px; margin-bottom: 16px; color: var(--primary); }
.er-modal-close { position: absolute; top: 12px; right: 12px; background: none; border: none; font-size: 18px; cursor: pointer; color: var(--text-light); }
.erm-section { margin-bottom: 16px; }
.erm-section h4 { font-size: 13px; font-weight: 600; color: var(--text); margin-bottom: 6px; }
.erm-section p { font-size: 13px; color: #555; margin-bottom: 3px; }
.erm-table { width: 100%; font-size: 12px; border-collapse: collapse; }
.erm-table th { text-align: left; padding: 6px; border-bottom: 2px solid var(--border); color: var(--text-light); font-weight: 600; }
.erm-table td { padding: 5px 6px; border-bottom: 1px solid var(--border); color: #333; }

/* Filter conditions */
.es-filters { margin-bottom: 20px; background: #F9FAFB; border: 1px dashed var(--border); border-radius: var(--radius); padding: 10px 14px; }
.es-filters summary { cursor: pointer; font-size: 13px; font-weight: 600; color: var(--primary); user-select: none; }
.esf-grid { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 10px; }
.esf-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-light); }
.esf-item input { width: 72px; padding: 6px 8px; border: 1.5px solid var(--border); border-radius: 6px; font-size: 13px; outline: none; }
.esf-item input[type="text"] { width: 140px; }
.esf-item input:focus { border-color: var(--primary-light); }
.esf-item input:disabled { opacity: 0.5; background: #F3F4F6; cursor: not-allowed; }
.esf-item select { padding: 6px 8px; border: 1.5px solid var(--border); border-radius: 6px; font-size: 13px; }
.esf-item em { font-style: normal; font-size: 11px; }
.esf-reset { margin-top: 10px; padding: 4px 12px; font-size: 12px; color: var(--text-light); background: #fff; border: 1px solid var(--border); border-radius: 6px; cursor: pointer; }
.esf-reset:hover { color: var(--primary); border-color: var(--primary-light); }

/* Search history */
.er-history { margin-bottom: 16px; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 14px; }
.erh-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 13px; font-weight: 600; color: var(--text); }
.erh-clear { background: none; border: none; color: var(--text-light); font-size: 12px; cursor: pointer; }
.erh-clear:hover { color: #991B1B; }
.erh-list { display: flex; flex-direction: column; gap: 4px; max-height: 220px; overflow-y: auto; }
.erh-item { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px; background: #F9FAFB; }
.erh-main { flex: 1; min-width: 0; cursor: pointer; display: flex; flex-direction: column; }
.erh-query { font-size: 13px; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.erh-meta { font-size: 11px; color: var(--text-light); }
.erh-del { background: none; border: none; color: var(--text-light); cursor: pointer; font-size: 12px; padding: 2px 6px; border-radius: 4px; }
.erh-del:hover { color: #991B1B; background: #FEE2E2; }

/* Analysis progress */
.er-progress { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px 20px; margin-bottom: 20px; }
.erp-bar { height: 8px; background: #E5E7EB; border-radius: 4px; overflow: hidden; }
.erp-fill { height: 100%; border-radius: 4px; background: linear-gradient(90deg, #0d9488, #10B981); transition: width 0.3s ease; }
.erp-info { display: flex; justify-content: space-between; margin-top: 8px; font-size: 12px; color: var(--text-light); }

/* Filter match results */
.erf-summary { padding: 10px 14px; background: #F0FDFA; border: 1px solid #A7F3D0; border-radius: var(--radius); font-size: 13px; color: #065F46; margin-bottom: 12px; }
.erf-summary strong { font-size: 16px; }
.erf-sub { display: block; font-size: 11px; color: #6b7280; margin-top: 2px; }
.erf-card { display: flex; align-items: center; gap: 12px; padding: 12px 14px; background: #fff; border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 8px; cursor: pointer; transition: all 0.12s; }
.erf-card:hover { border-color: var(--primary-light); box-shadow: var(--shadow); }
.erf-rank { width: 32px; height: 32px; border-radius: 50%; background: var(--primary); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; flex-shrink: 0; }
.erf-main { flex: 1; min-width: 0; }
.erf-eq { font-size: 12px; font-family: var(--mono); color: #333; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-bottom: 6px; }
.erf-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.erf-tag { font-size: 11px; padding: 2px 8px; border-radius: 4px; background: #F3F4F6; color: #666; }
.erf-tag.ok { background: #D1FAE5; color: #065F46; }
.erf-tag.miss { background: #FEE2E2; color: #991B1B; }
.erf-tag.exact { background: var(--primary); color: #fff; font-weight: 600; }
.erf-tag.partial { background: #FEF3C7; color: #92400E; }
.erf-score { font-size: 16px; font-weight: 700; color: var(--primary); flex-shrink: 0; }

@media (max-width: 768px) { .er-stats { flex-wrap: wrap; gap: 12px; } .er-tabs { flex-wrap: wrap; } }
.es-row input { min-width:0 }
</style>
