<script setup>
import { ref, computed, onMounted } from "vue"
import { getExtractionLogs, getStats } from "../api/chemistry.js"
import { useReactionSearch, fmtScore } from "../composables/useReactionSearch.js"
import ReactionCard from "../components/ReactionCard.vue"

const {
  query, loading, searching, searchResults, result,
  reactions, scored, compound, upstream, downstream,
  handleSearch, runAnalysis, scoreFor,
} = useReactionSearch()

// ---- 局部状态 ----
const experimentPlan = ref(null)
const generatingPlan = ref(false)
const activeTab = ref("info")
const historyItems = ref([])
const historyTotal = ref(0)
const analytics = ref(null)
const loadingHistory = ref(false)
const loadingAnalytics = ref(false)

// ---- 派生状态 ----
const firstCas = computed(() => reactions.value.find(r => r.cas_registry_id)?.cas_registry_id || null)
const schemeCount = computed(() => result.value?.schemes?.length || 0)
const litTotal = computed(() => result.value?.literature?.total || 0)

// ---- 分析入口（清理局部状态后调用共享逻辑）----
async function handleAnalyze(name) {
  experimentPlan.value = null
  await runAnalysis(name)
}

// ---- 实验方案（后端端点建设中，保留占位行为）----
async function handleGeneratePlan() {
  generatingPlan.value = true
  experimentPlan.value = null
  experimentPlan.value = { plan: "实验方案生成功能正在建设中，敬请期待。" }
  generatingPlan.value = false
}

// ---- 侧边栏数据 ----
async function fetchHistory() {
  loadingHistory.value = true
  try {
    const d = await getExtractionLogs({ limit: 5 })
    historyItems.value = d.items || []
    historyTotal.value = d.total || 0
  } catch { /* 加载失败保持空 */ } finally { loadingHistory.value = false }
}

async function fetchAnalytics() {
  loadingAnalytics.value = true
  try { analytics.value = await getStats() }
  catch { /* 加载失败保持 null */ } finally { loadingAnalytics.value = false }
}

function switchTab(tab) {
  activeTab.value = tab
  if (tab === "analytics") fetchAnalytics()
}

onMounted(() => fetchHistory())
</script>

<template>
  <div class="cp-root">
    <!-- Hero Search -->
    <div class="hero">
      <div class="hero-icon">🧪</div>
      <h1>化学合成路线分析</h1>
      <p>输入目标化合物名称或 CAS 号，获取合成路线、文献依据和实验方案</p>
      <div class="search-box">
        <input
          v-model="query" @keyup.enter="handleAnalyze()" @input="handleSearch"
          placeholder="例如：布洛芬 / 肉桂酸 / 15687-27-1"
        />
        <button @click="handleAnalyze()" :disabled="loading">
          {{ loading ? "⏳" : "🔍" }} {{ loading ? "分析中" : "分析" }}
        </button>
      </div>

      <!-- Quick search results -->
      <div v-if="searchResults.length && !result" class="quick-results">
        <div v-for="c in searchResults" :key="c.id" class="quick-card" @click="handleAnalyze(c.cas_registry_id || query.trim())">
          <span class="q-name">{{ c.cas_registry_id || '—' }}</span>
          <span class="q-cas">{{ c.reactants_text || '?' }} → {{ c.products_text || '?' }}</span>
          <span class="q-formula" v-if="c.literature_title">{{ c.literature_title.slice(0, 30) }}</span>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="loading-state">
      <div class="spinner"></div>
      <p>正在分析化合物，查询知识图谱...</p>
    </div>

    <!-- Content -->
    <div v-if="result && !result.error && !loading" class="content-area">
      <!-- Sidebar -->
      <aside class="sidebar">
        <div class="side-card compound-summary">
          <div class="sc-header">
            <div class="mol-icon">⚛️</div>
            <div>
              <h3>{{ compound?.name || query }}</h3>
              <span class="cas-badge">{{ firstCas || "无 CAS" }}</span>
            </div>
          </div>
          <div class="sc-props">
            <div class="prop"><label>匹配反应</label><span>{{ reactions.length }}</span></div>
            <div class="prop"><label>相关 Scheme</label><span>{{ schemeCount }}</span></div>
            <div class="prop"><label>关联文献</label><span>{{ litTotal }}</span></div>
            <div class="prop"><label>评分记录</label><span class="tag">{{ scored.length }}</span></div>
          </div>
        </div>

        <div v-if="upstream.length" class="side-card">
          <h4>⬆️ 上游原料</h4>
          <div class="graph-list">
            <div v-for="(u, i) in upstream" :key="'u'+i" class="graph-item">
              <span class="g-name">{{ u.compound }}</span>
              <span class="g-reaction">{{ u.reaction }}</span>
            </div>
          </div>
        </div>
        <div v-if="downstream.length" class="side-card">
          <h4>⬇️ 下游产物</h4>
          <div class="graph-list">
            <div v-for="(d, i) in downstream" :key="'d'+i" class="graph-item">
              <span class="g-name">{{ d.compound }}</span>
              <span class="g-reaction">{{ d.reaction }}</span>
            </div>
          </div>
        </div>

        <div class="side-card">
          <h4>📋 最近提取批次</h4>
          <div v-if="historyItems.length === 0" class="empty-hint">暂无记录</div>
          <div v-else class="mini-history">
            <div v-for="h in historyItems.slice(0, 5)" :key="h.id" class="mh-item" :title="`批次 #${h.batch_number} · p.${h.page_start}-${h.page_end} · ${h.schemes_found} schemes / ${h.reactions_found} reactions`">
              <span>批次 #{{ h.batch_number }} <template v-if="h.status === 'success'">✅</template><template v-else>⚠️</template></span>
              <span class="mh-time">{{ h.created_at?.slice(0, 10) }}</span>
            </div>
          </div>
        </div>
      </aside>

      <!-- Main -->
      <main class="main-panel">
        <!-- Tabs -->
        <nav class="tabs">
          <button :class="{ active: activeTab === 'info' }" @click="switchTab('info')">📋 路线分析</button>
          <button :class="{ active: activeTab === 'experiment' }" @click="switchTab('experiment')" v-if="experimentPlan">🧬 实验方案</button>
          <button :class="{ active: activeTab === 'analytics' }" @click="switchTab('analytics')">📊 数据</button>
        </nav>

        <!-- Tab: Routes -->
        <div v-if="activeTab === 'info'">
          <div v-if="reactions.length === 0" class="empty-state">
            <p>数据库中没有该化合物的合成路线记录</p>
            <p class="hint">尝试扩大搜索范围或添加更多反应数据</p>
          </div>

          <div v-else class="routes-grid">
            <ReactionCard
              v-for="(reaction, idx) in reactions"
              :key="reaction.id"
              :reaction="reaction"
              :score="scoreFor(reaction.id)"
              :rank="idx + 1"
              :show-generate-btn="true"
              :generating="generatingPlan"
              @generate="handleGeneratePlan"
            />
          </div>
        </div>

        <!-- Tab: Experiment -->
        <div v-if="activeTab === 'experiment' && experimentPlan" class="experiment-content">
          <div v-if="experimentPlan.error" class="empty-state">{{ experimentPlan.error }}</div>
          <div v-else class="exp-plan" v-html="experimentPlan.plan?.replace(/\n/g, '<br>')"></div>
        </div>

        <!-- Tab: Analytics -->
        <div v-if="activeTab === 'analytics'" class="analytics-panel">
          <div v-if="!analytics" class="empty-state">加载中...</div>
          <div v-else>
            <div class="stat-row">
              <div class="stat-box">
                <div class="stat-num">{{ analytics.schemes ?? 0 }}</div>
                <div class="stat-label">Scheme 方案</div>
              </div>
              <div class="stat-box">
                <div class="stat-num">{{ analytics.reactions ?? 0 }}</div>
                <div class="stat-label">反应记录</div>
              </div>
              <div class="stat-box">
                <div class="stat-num">{{ analytics.literatures ?? 0 }}</div>
                <div class="stat-label">文献记录</div>
              </div>
            </div>
            <div class="ana-section">
              <h4>数据详情</h4>
              <div class="top-list">
                <div class="top-row">
                  <span class="top-rank">📄</span>
                  <span class="top-name">含 SMILES 结构式的反应</span>
                  <span class="top-cnt">{{ analytics.reactions_with_smiles ?? 0 }} 条</span>
                </div>
                <div class="top-row">
                  <span class="top-rank">🔬</span>
                  <span class="top-name">反应条件记录</span>
                  <span class="top-cnt">{{ analytics.reaction_conditions ?? 0 }} 组</span>
                </div>
                <div class="top-row">
                  <span class="top-rank">📦</span>
                  <span class="top-name">PDF 提取批次</span>
                  <span class="top-cnt">{{ analytics.extraction_logs ?? 0 }} 批</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>

    <!-- Error -->
    <div v-if="result?.error" class="error-toast">{{ result.error }}</div>
  </div>
</template>

<style scoped>
.cp-root { margin-bottom: 48px; }

/* Hero */
.hero { text-align: center; padding: 48px 20px 32px; }
.hero-icon { font-size: 48px; margin-bottom: 8px; }
.hero h1 { font-size: 28px; font-weight: 700; color: #111827; margin-bottom: 8px; }
.hero p { color: #6b7280; font-size: 15px; max-width: 520px; margin: 0 auto 24px; }
.search-box { display: flex; max-width: 600px; margin: 0 auto; gap: 8px; }
.search-box input { flex: 1; padding: 14px 20px; border: 2px solid #e5e7eb; border-radius: 14px; font-size: 15px; outline: none; transition: border 0.15s; }
.search-box input:focus { border-color: #0d9488; }
.search-box button { padding: 14px 28px; background: #0d9488; color: #fff; border: none; border-radius: 14px; font-size: 16px; font-weight: 600; cursor: pointer; transition: background 0.15s; }
.search-box button:hover { background: #0f766e; }
.search-box button:disabled { opacity: 0.6; cursor: not-allowed; }

.quick-results { max-width: 600px; margin: 16px auto 0; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.06); }
.quick-card { padding: 12px 20px; display: flex; align-items: center; gap: 12px; cursor: pointer; border-bottom: 1px solid #f3f4f6; transition: background 0.1s; }
.quick-card:hover { background: #f0fdfa; }
.q-name { font-weight: 600; flex: 1; }
.q-cas { font-family: var(--mono); font-size: 13px; color: #6b7280; }
.q-formula { font-family: var(--mono); font-size: 12px; color: #9ca3af; }

/* Loading */
.loading-state { text-align: center; padding: 48px; }
.spinner { width: 40px; height: 40px; border: 3px solid #e5e7eb; border-top-color: #0d9488; border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 16px; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Content */
.content-area { display: flex; gap: 24px; padding: 0 24px 32px; max-width: 1200px; margin: 0 auto; }
.sidebar { width: 280px; flex-shrink: 0; display: flex; flex-direction: column; gap: 16px; }
.main-panel { flex: 1; }

.side-card { background: #fff; border-radius: 14px; padding: 20px; box-shadow: var(--shadow); }
.side-card h4 { font-size: 14px; font-weight: 600; margin-bottom: 10px; }
.sc-header { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.mol-icon { width: 40px; height: 40px; background: #f0fdfa; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 20px; }
.sc-header h3 { font-size: 16px; font-weight: 700; }
.cas-badge { font-size: 12px; background: #e5e7eb; padding: 2px 10px; border-radius: 8px; color: #6b7280; }
.sc-props { display: flex; flex-direction: column; gap: 6px; }
.prop { display: flex; justify-content: space-between; align-items: center; font-size: 13px; }
.prop label { color: #9ca3af; }
.tag { padding: 2px 8px; background: #d1fae5; color: #065f46; border-radius: 6px; font-size: 12px; }

.graph-list { display: flex; flex-direction: column; gap: 6px; }
.graph-item { display: flex; justify-content: space-between; align-items: center; padding: 6px 8px; background: #f9fafb; border-radius: 8px; font-size: 13px; }
.g-name { font-weight: 500; }
.g-reaction { font-size: 11px; color: #6b7280; }

.mini-history { display: flex; flex-direction: column; gap: 4px; }
.mh-item { display: flex; justify-content: space-between; padding: 6px 8px; background: #f9fafb; border-radius: 8px; cursor: default; font-size: 13px; }
.mh-time { font-size: 11px; color: #9ca3af; }

.empty-hint { font-size: 13px; color: #9ca3af; text-align: center; padding: 12px; }

/* Tabs */
.tabs { display: flex; gap: 4px; background: #f3f4f6; padding: 4px; border-radius: 12px; margin-bottom: 16px; }
.tabs button { flex: 1; padding: 10px 16px; border: none; border-radius: 10px; background: transparent; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.15s; color: #6b7280; }
.tabs button.active { background: #fff; color: #0d9488; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }

.empty-state { text-align: center; padding: 48px; color: #9ca3af; }
.empty-state p { margin-bottom: 4px; }
.empty-state .hint { font-size: 13px; }

/* Route cards 样式已迁移至 ReactionCard 组件 */
.routes-grid { display: flex; flex-direction: column; gap: 12px; }

/* Experiment */
.experiment-content { background: #fff; border-radius: 14px; padding: 24px; box-shadow: var(--shadow); }
.exp-plan { line-height: 1.8; white-space: pre-wrap; font-size: 14px; }
.exp-plan :deep(table) { width: 100%; border-collapse: collapse; margin: 12px 0; }
.exp-plan :deep(td), .exp-plan :deep(th) { padding: 8px 12px; border: 1px solid #e5e7eb; text-align: left; }
.exp-plan :deep(th) { background: #f9fafb; }

/* Analytics */
.analytics-panel { background: #fff; border-radius: 14px; padding: 24px; box-shadow: var(--shadow); }
.stat-row { display: flex; gap: 12px; margin-bottom: 24px; }
.stat-box { flex: 1; padding: 24px; background: linear-gradient(135deg, #0d9488, #0891b2); color: #fff; border-radius: 14px; text-align: center; }
.stat-num { font-size: 40px; font-weight: 700; }
.stat-label { font-size: 13px; opacity: 0.8; margin-top: 4px; }
.ana-section h4 { margin: 0 0 8px; font-size: 14px; }
.top-list { display: flex; flex-direction: column; gap: 4px; }
.top-row { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: #f9fafb; border-radius: 8px; font-size: 14px; }
.top-rank { font-weight: 700; color: #0d9488; width: 28px; }
.top-name { flex: 1; }
.top-cnt { font-size: 12px; background: #e5e7eb; padding: 2px 10px; border-radius: 12px; color: #6b7280; }

.error-toast { max-width: 500px; margin: 24px auto; padding: 16px 24px; background: #fef2f2; color: #991b1b; border-radius: 12px; text-align: center; }

@media (max-width: 768px) {
  .content-area { flex-direction: column; padding: 0 16px 32px; }
  .sidebar { width: 100%; }
  .hero h1 { font-size: 24px; }
  .search-box { flex-direction: column; }
  .stat-row { flex-direction: column; }
}
</style>
