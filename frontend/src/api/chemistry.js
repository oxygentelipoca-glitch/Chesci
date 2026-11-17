/**
 * ChemRoute 化学合成 API 封装
 */
import axios from "axios"

const API_BASE = import.meta.env.VITE_API_BASE || ""

function authHeaders() {
  const token = localStorage.getItem("rag_token")
  return token ? { Authorization: "Bearer " + token } : {}
}

// ─── Schemes ────────────────────────────────────────────────────────────────

/**
 * GET /api/chemistry/schemes — 获取 Scheme 列表
 * @param {object} [params={}] - 查询参数
 * @param {number} [params.skip=0] - 分页偏移
 * @param {number} [params.limit=20] - 每页条数
 * @param {string} [params.q] - 搜索关键词
 */
export async function getSchemes(params = {}) {
  const res = await axios.get(`${API_BASE}/api/chemistry/schemes`, {
    params,
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * GET /api/chemistry/schemes/{id} — 获取 Scheme 详情
 * @param {number|string} id - Scheme ID
 */
export async function getScheme(id) {
  const res = await axios.get(`${API_BASE}/api/chemistry/schemes/${id}`, {
    headers: authHeaders(),
  })
  return res.data.data
}

// ─── Reactions ──────────────────────────────────────────────────────────────

/**
 * GET /api/chemistry/reactions — 获取 Reaction 列表
 * @param {object} [params={}] - 查询参数
 */
export async function getReactions(params = {}) {
  const res = await axios.get(`${API_BASE}/api/chemistry/reactions`, {
    params,
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * GET /api/chemistry/reactions/{id} — 获取 Reaction 详情
 * @param {number|string} id - Reaction ID
 */
export async function getReaction(id) {
  const res = await axios.get(`${API_BASE}/api/chemistry/reactions/${id}`, {
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * GET /api/chemistry/reactions/{id}/conditions — 获取条件列表
 * @param {number|string} id - Reaction ID
 */
export async function getReactionConditions(id) {
  const res = await axios.get(
    `${API_BASE}/api/chemistry/reactions/${id}/conditions`,
    { headers: authHeaders() }
  )
  return res.data.data
}

/**
 * GET /api/chemistry/reactions/{id}/literature — 获取文献详情
 * @param {number|string} id - Reaction ID
 */
export async function getReactionLiterature(id) {
  const res = await axios.get(
    `${API_BASE}/api/chemistry/reactions/${id}/literature`,
    { headers: authHeaders() }
  )
  return res.data.data
}

/** Extract a SciFinder PDF into editable preview data. */
export async function previewSciFinderImport(file, maxSchemes = 5, documentType = "scifinder") {
  const form = new FormData()
  form.append("file", file)
  form.append("document_type", documentType)
  form.append("max_schemes", String(maxSchemes))
  const res = await axios.post(`${API_BASE}/api/chemistry/import/scifinder/preview`, form, {
    headers: authHeaders(),
  })
  return res.data.data
}

/** Import the reviewed and corrected SciFinder preview into reactions.db. */
export async function confirmSciFinderImport(payload) {
  const res = await axios.post(`${API_BASE}/api/chemistry/import/scifinder/confirm`, payload, {
    headers: authHeaders(),
  })
  return res.data.data
}

// ─── Knowledge Graph ────────────────────────────────────────────────────────

/**
 * GET /api/chemistry/graph — 获取知识图谱数据
 */
export async function getGraph() {
  const res = await axios.get(`${API_BASE}/api/chemistry/graph`, {
    headers: authHeaders(),
  })
  return res.data.data
}

// ─── Search ─────────────────────────────────────────────────────────────────

/**
 * GET /api/chemistry/search — 全文搜索
 * @param {object} params - {q, type}
 */
export async function search(params) {
  const res = await axios.get(`${API_BASE}/api/chemistry/search`, {
    params,
    headers: authHeaders(),
  })
  return res.data.data
}

// ─── Stats ──────────────────────────────────────────────────────────────────

/**
 * GET /api/chemistry/stats — 获取统计概览
 */
export async function getStats() {
  const res = await axios.get(`${API_BASE}/api/chemistry/stats`, {
    headers: authHeaders(),
  })
  return res.data.data
}

// ─── Extraction Logs ────────────────────────────────────────────────────────

/**
 * GET /api/chemistry/extraction-logs — 获取提取日志列表
 */
export async function getExtractionLogs(params = {}) {
  const res = await axios.get(`${API_BASE}/api/chemistry/extraction-logs`, {
    params,
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * GET /api/chemistry/extraction-logs/{id} — 获取日志详情
 */
export async function getExtractionLog(id) {
  const res = await axios.get(
    `${API_BASE}/api/chemistry/extraction-logs/${id}`,
    { headers: authHeaders() }
  )
  return res.data.data
}

// ─── Analyze ────────────────────────────────────────────────────────────────

/**
 * POST /api/chemistry/analyze — 一站式分析
 * @param {object} params - {query}
 */
export async function analyze(params = {}) {
  const res = await axios.post(
    `${API_BASE}/api/chemistry/analyze`,
    params,
    { headers: authHeaders() }
  )
  return res.data.data
}

/**
 * POST /api/chemistry/experiment-plan — 基于选中路线和来源生成方案草案
 */
export async function generateExperimentPlan(params = {}) {
  const res = await axios.post(
    `${API_BASE}/api/chemistry/experiment-plan`,
    params,
    { headers: authHeaders() }
  )
  return res.data.data
}

// ─── Search History（按用户隔离）────────────────────────────────────────────

/**
 * GET /api/chemistry/search-history — 当前用户的搜索历史
 */
export async function getSearchHistory(params = {}) {
  const res = await axios.get(`${API_BASE}/api/chemistry/search-history`, {
    params,
    headers: authHeaders(),
  })
  return res.data.data
}

/**
 * DELETE /api/chemistry/search-history/{id} — 删除一条搜索历史
 */
export async function deleteSearchHistory(id) {
  const res = await axios.delete(
    `${API_BASE}/api/chemistry/search-history/${id}`,
    { headers: authHeaders() }
  )
  return res.data.data
}

/**
 * DELETE /api/chemistry/search-history — 清空当前用户的搜索历史
 */
export async function clearSearchHistory() {
  const res = await axios.delete(
    `${API_BASE}/api/chemistry/search-history`,
    { headers: authHeaders() }
  )
  return res.data.data
}

// ─── 在线文献检索（OpenAlex / Crossref 代理）────────────────────────────────

/**
 * GET /api/chemistry/literature-online — 在线文献检索
 * @param {object} params - {q, source: 'openalex'|'crossref', limit}
 */
export async function getOnlineLiterature(params = {}) {
  const res = await axios.get(`${API_BASE}/api/chemistry/literature-online`, {
    params,
    headers: authHeaders(),
  })
  return res.data.data
}
