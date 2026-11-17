<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useReactionSearch } from '../composables/useReactionSearch.js'
import ReactionCard from '../components/ReactionCard.vue'
import RouteComparison from '../components/RouteComparison.vue'
import PlanDraft from '../components/PlanDraft.vue'
import { pdfEvidenceLines } from '../utils/routeEvidence.js'
import { draftContext } from '../utils/planDraft.js'
import ChemicalStructureEditor from '../components/ChemicalStructureEditor.vue'
import { confirmSciFinderImport, generateExperimentPlan, previewSciFinderImport } from '../api/chemistry.js'
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
const maxTimeHours = ref('')
const catalystRequirement = ref('any')
const solventRequirement = ref('any')
const workupRequirement = ref('any')
const catalystName = ref('')
const solventName = ref('')
const planLoading = ref(false)
const experimentPlan = ref(null)
const planContext = ref(null)
const documentType = ref('scifinder')
const importFile = ref(null)
const maxImportSchemes = ref(5)
const importLoading = ref(false)
const importConfirmLoading = ref(false)
const importPreview = ref(null)
const importError = ref('')
const importMessage = ref('')
const structureSmiles = ref('')
const incompleteImportCount = computed(() => (importPreview.value?.reactions || []).filter(reaction =>
  !reaction.reactants_text.trim() || !reaction.products_text.trim()
).length)

const rankedReactions = computed(() => {
  if (Array.isArray(result.value?.filter_matches?.items)) {
    return result.value.filter_matches.items
  }
  const scoreByReaction = new Map(
    (result.value?.scored || []).map(score => [score.reaction_id, score.total])
  )
  return [...reactions.value].sort((a, b) =>
    (scoreByReaction.get(b.id) ?? -1) - (scoreByReaction.get(a.id) ?? -1)
  )
})

function useDemoCase() {
  startingMaterial.value = '苯甲醛'
  query.value = '肉桂酸'
}

if (useRoute().query.demo === 'cinnamic-acid') useDemoCase()

function analyzeStructure(smiles) {
  const target = String(smiles || '').trim()
  if (!target) return
  query.value = target
  handleSearch()
  startAnalysis(target)
}

function selectSciFinderFile(event) {
  importFile.value = event.target.files?.[0] || null
  importPreview.value = null
  importError.value = ''
  importMessage.value = ''
}

function joinPreviewValue(value) {
  if (Array.isArray(value)) return value.join('; ')
  return value == null ? '' : String(value)
}

function splitPreviewValue(value) {
  return String(value || '').split(/[\n;；]+/).map(item => item.trim()).filter(Boolean)
}

async function previewSciFinder() {
  importError.value = ''
  importMessage.value = ''
  if (!importFile.value) {
    importError.value = '请先选择 PDF 文件。'
    return
  }
  if (importFile.value.size > 20 * 1024 * 1024) {
    importError.value = 'PDF 文件不能超过 20 MB。'
    return
  }

  importLoading.value = true
  importPreview.value = null
  try {
    const data = await previewSciFinderImport(importFile.value, Number(maxImportSchemes.value) || 5, documentType.value)
    importPreview.value = {
      ...data,
      reactions: (data.reactions || []).map(reaction => ({
        ...reaction,
        reactants_text: joinPreviewValue(reaction.reactants),
        products_text: joinPreviewValue(reaction.products),
        yield_text: joinPreviewValue(reaction.yield),
        temperature_text: joinPreviewValue(reaction.conditions?.temperature),
        time_text: joinPreviewValue(reaction.conditions?.time),
        source_text: joinPreviewValue(reaction.source),
      })),
    }
  } catch (e) {
    importError.value = e.response?.data?.message || 'PDF 提取失败，请检查登录状态和服务器配置。'
  } finally {
    importLoading.value = false
  }
}

async function confirmImport() {
  if (!importPreview.value?.reactions?.length) return
  importConfirmLoading.value = true
  importError.value = ''
  importMessage.value = ''
  try {
    const preview = importPreview.value
    const payload = {
      source_sha256: preview.source_sha256,
      file_name: preview.file_name,
      page_count: preview.page_count,
      model: preview.model,
      schemes: preview.schemes,
      reactions: preview.reactions.map(reaction => ({
        ...reaction,
        reactants: splitPreviewValue(reaction.reactants_text),
        products: splitPreviewValue(reaction.products_text),
        yield: reaction.yield_text.trim() || null,
        source: reaction.source_text.trim() || null,
        conditions: {
          ...(reaction.conditions || {}),
          temperature: reaction.temperature_text.trim() || '',
          time: reaction.time_text.trim() || '',
        },
      })),
    }
    const imported = await confirmSciFinderImport(payload)
    importMessage.value = imported.duplicate
      ? '这个 PDF 已经导入过。'
      : `导入完成：${imported.schemes_imported} 个方案，${imported.reactions_imported} 条反应。可以重新分析目标产物查看结果。`
  } catch (e) {
    importError.value = e.response?.data?.message || '导入失败，请核对数据后重试。'
  } finally {
    importConfirmLoading.value = false
  }
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
    max_time_hours: maxTimeHours.value !== '' ? Number(maxTimeHours.value) : undefined,
    catalyst: catalystRequirement.value,
    solvent: solventRequirement.value,
    workup: workupRequirement.value,
    catalyst_name: catalystName.value.trim() || undefined,
    solvent_name: solventName.value.trim() || undefined,
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
  const analysis = result.value
  if (!analysis || planLoading.value) return
  const context = draftContext(analysis, reaction)
  planContext.value = context
  activeRoute.value = rankedReactions.value.findIndex(item => item.id === reaction.id)
  planLoading.value = true
  experimentPlan.value = null
  try {
    const literatureContext = [context.source, ...context.links.map(link => `${link.label} ${link.url}`)].join('\n')
    const draft = await generateExperimentPlan({
      compound: { name: analysis.query, starting_material: analysis.starting_material || '' },
      route: {
        name: reaction.reaction_type || reaction.literature_title || `反应 ${reaction.id}`,
        type: reaction.reaction_type || '未提供',
        equation: reaction.equation_zh || reaction.equation || `${reaction.reactants_zh || reaction.reactants_text || ''} → ${reaction.products_zh || reaction.products_text || ''}`,
        yield: reaction.yield_ || '未提供',
        catalyst: (reaction.conditions_summary || []).map(c => c.catalysts).filter(Boolean).join('；') || '未提供',
        solvent: (reaction.conditions_summary || []).map(c => c.solvents).filter(Boolean).join('；') || '未提供',
        temperature: (reaction.conditions_summary || []).map(c => c.temperature).filter(Boolean).join('；') || '未提供',
        time: (reaction.conditions_summary || []).map(c => c.time).filter(Boolean).join('；') || '未提供',
        literature_title: reaction.literature_title || '',
      },
      literature_context: literatureContext,
      extra_instructions: [
        `起始原料：${context.start}。选定的数据库反应编号：${context.reactionId}。`,
        `用户设置的实验室约束：${context.filters}。`,
        ...(context.checks.length ? [`系统逐项核对：${context.checks.join('；')}`] : []),
        '请对照记录标出满足、冲突及缺乏证据的条件。筛选阈值仅为用户要求，不能用作实验测量值。缺失的条件或出处标为需查证。',
      ].join('\n'),
    })
    if (result.value === analysis) experimentPlan.value = draft
  } catch (e) {
    if (result.value === analysis) {
      experimentPlan.value = { error: e.response?.data?.message || '方案生成失败，请稍后重试。' }
    }
  } finally {
    planLoading.value = false
  }
}
</script>

<template>
  <MainLayout>
    <div class="rp-root">
      <header class="page-intro"><h1>合成路线规划</h1><p>比较实验室条件下可行的反应，查看文献依据并生成实验草案。</p></header>
      <div class="input-panel">
        <h2 class="panel-heading">目标反应</h2>
        <div class="demo-row"><span>演示案例：苯甲醛 → 肉桂酸</span><button type="button" @click="useDemoCase">填入案例</button></div>
        <div class="ip-row">
          <div class="ip-search">
            <label class="field"><span>起始原料</span><input v-model="startingMaterial" placeholder="例如：苯甲醛（可选）" /></label>
            <label class="field"><span>目标产物</span><input v-model="query" @keyup.enter="startAnalysis()" @input="handleSearch" placeholder="例如：肉桂酸或 CAS 号" /></label>
            <button @click="startAnalysis()" :disabled="loading">{{ loading ? '分析中...' : '开始分析' }}</button>
          </div>
        </div>
        <!-- Quick search results -->
        <div v-if="searchResults.length && !loading" class="quick-drop">
          <div v-for="c in searchResults" :key="c.id" class="qd-item" @click="startAnalysis(c.cas_registry_id || query.trim())">
            <span class="qd-cas">{{ c.cas_registry_id || '—' }}</span>
            <span class="qd-eq">{{ c.reactants_text || '?' }} → {{ c.products_text || '?' }}</span>
          </div>
        </div>
        <details class="constraint-panel">
          <summary>实验室条件筛选（可选）</summary>
          <div class="constraint-grid">
            <label class="field"><span>最低收率 (%)</span><input v-model="minYield" type="number" min="0" max="100" placeholder="不限" /></label>
            <label class="field"><span>最高温度 (°C)</span><input v-model="maxTemperature" type="number" placeholder="不限" /></label>
            <label class="field"><span>最多反应步骤</span><input v-model="maxSteps" type="number" min="1" placeholder="不限" /></label>
            <label class="field"><span>最长单段时间 (小时)</span><input v-model="maxTimeHours" type="number" min="0" placeholder="不限" /></label>
            <label class="field"><span>催化剂关键词</span><input v-model="catalystName" placeholder="如 Piperidine" /></label>
            <label class="field"><span>溶剂关键词</span><input v-model="solventName" placeholder="如 Water" /></label>
            <label class="field"><span>催化剂要求</span><select v-model="catalystRequirement"><option value="any">不限</option><option value="with">需有催化剂记录</option></select></label>
            <label class="field"><span>溶剂要求</span><select v-model="solventRequirement"><option value="any">不限</option><option value="with">需有溶剂记录</option></select></label>
            <label class="field"><span>后处理要求</span><select v-model="workupRequirement"><option value="any">不限</option><option value="with">需有后处理记录</option></select></label>
          </div>
          <p class="constraint-note">起始原料按数据库已有反应的反应物名称或 SMILES 匹配；当前展示直接反应记录，不自动拼接多步路线。条件筛选仅依据已录入字段；设备和库存尚未建模，不会被系统假定。</p>
        </details>

        <details class="structure-panel">
          <summary>化学结构绘图（Beta）</summary>
          <p class="structure-intro">绘制原子和键后可导出 SVG，或用生成的 SMILES 搜索路线。结构匹配目前要求 SMILES 与数据库记录一致。</p>
          <ChemicalStructureEditor v-model:smiles="structureSmiles" @use-smiles="analyzeStructure" />
        </details>
      </div>
      <section class="scifinder-import">
          <div class="import-heading">
            <div>
              <h3>从 PDF 导入反应</h3>
              <p>PDF 文本会发送给服务器配置的 LLM 服务提取；文件本身不会保存在服务器。提取后先校对，再写入共享反应数据库。</p>
            </div>
          </div>
          <div class="import-controls">
            <label class="field"><span>文档类型</span><select v-model="documentType" :disabled="importLoading || importConfirmLoading" @change="importPreview = null; importError = ''; importMessage = ''"><option value="scifinder">SciFinder 导出</option><option value="paper">期刊论文</option></select></label>
            <label class="field import-file"><span>PDF 文件（最大 20 MB）</span><input type="file" :disabled="importLoading || importConfirmLoading" accept="application/pdf,.pdf" @change="selectSciFinderFile" /></label>
            <label v-if="documentType === 'scifinder'" class="field scheme-limit"><span>提取 Scheme 数</span><input v-model.number="maxImportSchemes" type="number" min="1" max="20" /></label>
            <button class="import-button" type="button" :disabled="importLoading || importConfirmLoading || !importFile" @click="previewSciFinder">
              {{ importLoading ? '正在提取…' : '提取并预览' }}
            </button>
          </div>
          <p v-if="importPreview" class="import-summary">{{ importPreview.file_name }} · {{ importPreview.reactions.length }} 条反应<template v-if="importPreview.document_type !== 'paper'"> · 已处理 {{ importPreview.selected_scheme_count }}/{{ importPreview.total_scheme_count }} 个 Scheme</template> · {{ importPreview.page_count }} 页 · 模型 {{ importPreview.model }}<template v-if="importPreview.failed_schemes"> · {{ importPreview.failed_schemes }} 个 Scheme 提取失败</template></p>
          <p v-for="warning in importPreview?.warnings || []" :key="warning" class="import-notice">{{ warning }}</p>
          <p v-if="importPreview?.review_notice" class="import-notice">{{ importPreview.review_notice }}</p>
          <p v-if="importPreview?.reactions_truncated" class="import-notice">预览反应数已达到 500 条上限；本次只包含前 500 条。</p>
          <p v-if="incompleteImportCount" class="import-notice">{{ incompleteImportCount }} 条反应缺少反应物或产物信息，请在确认导入前补全或核对。</p>
          <div v-if="importPreview?.reactions?.length" class="import-review-list">
            <article v-for="(reaction, index) in importPreview.reactions" :key="`${reaction.scheme_number}-${index}`" class="import-review-card">
              <div class="import-card-title"><strong><template v-if="documentType === 'scifinder'">Scheme {{ reaction.scheme_number }} · </template>反应 {{ index + 1 }}</strong><span>PDF 第 {{ reaction.page }} 页</span><em v-if="!reaction.reactants_text.trim() || !reaction.products_text.trim()">待补全</em></div>
              <div v-if="reaction.paper_evidence?.length" class="import-notice">
                <p v-for="(line, i) in pdfEvidenceLines(reaction)" :key="i">{{ line }}</p>
              </div>
              <label class="field"><span>标题</span><input v-model="reaction.title" placeholder="未提取到标题" /></label>
              <div class="import-edit-grid">
                <label class="field"><span>反应物（用分号分隔）</span><textarea v-model="reaction.reactants_text" rows="2" placeholder="反应物名称" /></label>
                <label class="field"><span>产物（用分号分隔）</span><textarea v-model="reaction.products_text" rows="2" placeholder="产物名称" /></label>
              </div>
              <div class="import-edit-grid import-edit-meta">
                <label class="field"><span>收率</span><input v-model="reaction.yield_text" placeholder="例如 85%" /></label>
                <label class="field"><span>温度</span><input v-model="reaction.temperature_text" placeholder="例如 80 °C" /></label>
                <label class="field"><span>时间</span><input v-model="reaction.time_text" placeholder="例如 3 h" /></label>
              </div>
              <label class="field"><span>文献来源</span><textarea v-model="reaction.source_text" rows="2" placeholder="期刊、年份、DOI 或专利" /></label>
            </article>
            <button class="confirm-import-button" type="button" :disabled="importConfirmLoading" @click="confirmImport">
              {{ importConfirmLoading ? '正在写入数据库…' : '确认校对并导入数据库' }}
            </button>
          </div>
          <p v-if="importError" class="import-error">{{ importError }}</p>
          <p v-if="importMessage" class="import-success">{{ importMessage }}</p>
      </section>

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
            <div class="tn-target">{{ compound?.name || query }}</div>
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
          <div v-if="result.filter_matches" class="filter-summary">
            <strong>满足全部筛选 {{ result.filter_matches.total_exact }} / {{ result.filter_matches.total_ranked }} 条</strong>
            <span>展示 {{ result.filter_matches.items?.length || 0 }} 条；先按已证实满足的条件数排序；数量相同时比较综合评分。冲突和证据不足均不计为满足。</span>
          </div>
          <div class="route-cards">
            <RouteComparison v-if="rankedReactions.length >= 2"
              :reactions="rankedReactions" :score-for="scoreFor" :generating="planLoading"
              @generate="createPlan" />
            <PlanDraft v-if="experimentPlan" :draft="experimentPlan" :context="planContext" />
            <ReactionCard
              v-for="(reaction, idx) in rankedReactions"
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
            <p v-if="!rankedReactions.length" class="no-routes">当前数据库中没有同时匹配目标产物、起始原料和筛选条件的反应记录。可放宽条件或检查导入数据。</p>
          </div>

          <section v-if="result.literature?.sources?.length" class="literature-panel">
            <h3>相关文献</h3>
            <article v-for="(paper, index) in result.literature.sources" :key="`${paper.title}-${index}`" class="paper-row">
              <strong>{{ paper.title || '未提供标题' }}</strong>
              <span>{{ [paper.authors, paper.journal, paper.year].filter(Boolean).join(' · ') || '文献信息不完整' }}</span>
              <a v-if="paper.doi" :href="`https://doi.org/${paper.doi}`" target="_blank" rel="noopener noreferrer">DOI: {{ paper.doi }}</a>
            </article>
          </section>

          <!-- LLM Analysis Report -->
          <div v-if="result.answer" class="answer-panel">
            <h3>AI 分析报告</h3>
            <div class="answer-content">{{ result.answer }}</div>
          </div>
        </div>
      </div>

      <!-- Error -->
      <div v-if="error" class="error-toast">{{ error }}</div>

      <!-- Data source hint -->
      <div class="data-hint">
        反应数据来自化学数据库（reactions.db）。SciFinder PDF 提取需要服务器配置 DEEPSEEK_API_KEY；确认导入前请人工核对提取结果。
      </div>


    </div>
  </MainLayout>
</template>

<style scoped>
.rp-root { max-width: 1200px; }

/* Input */
.input-panel { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 24px; margin-bottom: 20px; box-shadow: var(--shadow); }
.panel-heading { font-size: 18px; font-weight: 700; color: var(--primary); margin-bottom: 4px; }
.ip-row { display: flex; gap: 12px; margin-bottom: 12px; }
.ip-search { flex: 1; display: grid; grid-template-columns: 1fr 1fr auto; gap: 12px; align-items: end; }
.field { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--text-light); }
.field input, .field select { width: 100%; box-sizing: border-box; padding: 10px 12px; border: 1.5px solid var(--border); border-radius: var(--radius); background: #fff; font-size: 14px; outline: none; }
.field input:focus, .field select:focus { border-color: var(--primary-light); }
.ip-search button { padding: 10px 28px; background: var(--primary); color: #fff; border: none; border-radius: var(--radius); font-weight: 600; cursor: pointer; white-space: nowrap; }
.ip-search button:disabled { opacity: 0.6; cursor: not-allowed; }
.demo-row { display: flex; align-items: center; gap: 14px; margin: 10px 0 14px; color: var(--text-light); font-size: 12px; }
.demo-row button { border: 0; background: transparent; color: var(--primary); font-weight: 600; cursor: pointer; }
.structure-panel { margin: 16px 0 0; border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg); padding: 12px; color: var(--text); font-size: 13px; }
.structure-panel summary { cursor: pointer; font-weight: 600; }
.structure-intro { margin-top: 8px; color: var(--text-light); font-size: 12px; }
.constraint-panel { border-top: 1px solid var(--border); padding-top: 12px; color: var(--text); font-size: 13px; }
.constraint-panel summary { cursor: pointer; font-weight: 600; }
.constraint-grid { display: grid; grid-template-columns: repeat(3, minmax(120px, 1fr)); gap: 12px; margin-top: 14px; }
.constraint-note { color: var(--text-light); font-size: 11px; margin: 12px 0 0; }
.scifinder-import { margin:0 0 20px; padding:20px 24px; background:#ebf2ef; border:1px solid var(--border); border-radius:var(--radius); }
.import-heading h3 { margin: 0 0 4px; color: var(--text); font-size: 14px; }
.import-heading p, .import-summary { margin: 0 0 12px; color: var(--text-light); font-size: 12px; }
.import-controls { display: grid; grid-template-columns: minmax(120px,.65fr) minmax(175px,1.4fr) minmax(100px,.6fr) auto; gap: 12px; align-items: end; }
.import-file input { padding: 8px 0; border: 0; font-size: 12px; }
.scheme-limit input { width: 100%; box-sizing: border-box; padding: 9px 10px; border: 1px solid var(--border); border-radius: var(--radius); }
.import-button, .confirm-import-button { padding: 10px 16px; background: var(--primary); color: #fff; border: 0; border-radius: var(--radius); font-weight: 600; cursor: pointer; }
.import-button:disabled, .confirm-import-button:disabled { opacity: .55; cursor: not-allowed; }
.import-notice { padding: 10px 12px; color: #854d0e; background: #fffbeb; border-radius: 8px; font-size: 12px; }
.import-review-list { display: flex; flex-direction: column; gap: 10px; max-height: 600px; overflow: auto; padding: 2px; }
.import-review-card { display: flex; flex-direction: column; gap: 10px; padding: 14px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--card); }
.import-card-title { display: flex; justify-content: space-between; gap: 12px; color: var(--text); font-size: 12px; }
.import-card-title span { color: var(--text-light); }
.import-card-title em { color: #b45309; font-size: 11px; font-style: normal; font-weight: 700; }
.import-edit-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.import-edit-meta { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.import-review-card textarea { width: 100%; box-sizing: border-box; resize: vertical; padding: 9px 10px; border: 1px solid var(--border); border-radius: var(--radius); font: inherit; font-size: 13px; }
.import-error, .import-success { margin: 10px 0 0; font-size: 12px; }
.import-error { color: #991b1b; }
.import-success { color: #166534; }
.confirm-import-button { align-self: flex-start; }
.route-source { color: var(--text-light); font-size: 12px; text-align: center; margin: 8px 0; }

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
.result-right { flex: 1; min-width: 0; }
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
.filter-summary { display: flex; flex-direction: column; gap: 4px; margin: -2px 0 12px; padding: 11px 13px; border: 1px solid #B7D8D0; border-radius: 9px; background: #F1FAF7; color: #285E53; font-size: 12px; }
.filter-summary strong { font-size: 13px; }
.filter-summary span { color: #597D75; }
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


/* Data hint */
.data-hint { margin-top: 16px; padding: 10px 16px; background: var(--card); border: 1px dashed var(--border); border-radius: var(--radius); font-size: 12px; color: var(--text-light); }
.data-hint code { font-family: var(--mono); background: #F3F4F6; padding: 1px 6px; border-radius: 4px; }

@media (max-width: 768px) {
  .ip-search, .constraint-grid, .import-controls, .import-edit-grid, .import-edit-meta { grid-template-columns: 1fr; }
  .results-area { flex-direction: column; }
  .result-left { width: 100%; }
  .steps-panel { flex-direction: column; }
}
</style>
