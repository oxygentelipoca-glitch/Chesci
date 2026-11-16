/**
 * useReactionSearch — 反应搜索与分析共享逻辑。
 *
 * 统一 RoutePlanning / ChemistryPanel / Experiment 三个视图中的：
 * - 实时搜索建议（handleSearch）
 * - 分析执行（runAnalysis → POST /api/chemistry/analyze）
 * - 评分查询（scoreFor）
 *
 * @param {object} [options]
 * @param {number} [options.maxSuggestions=Infinity] - 搜索建议上限
 */
import { ref, computed } from 'vue'
import { search, analyze } from '../api/chemistry.js'

export function useReactionSearch({ maxSuggestions = Infinity } = {}) {
  const query = ref('')
  const loading = ref(false)
  const searching = ref(false)
  const searchResults = ref([])
  const result = ref(null)

  // ---- 分析结果派生状态 ----
  const reactions = computed(() => result.value?.reactions || [])
  const scored = computed(() => result.value?.scored || [])
  const compound = computed(() => result.value?.compound)
  const upstream = computed(() => result.value?.upstream || [])
  const downstream = computed(() => result.value?.downstream || [])
  const schemes = computed(() => result.value?.schemes || [])
  const error = computed(() => result.value?.error || null)

  // ---- 实时搜索建议 ----
  async function handleSearch() {
    if (!query.value.trim()) { searchResults.value = []; return }
    searching.value = true
    try {
      const d = await search({ q: query.value.trim(), type: 'all' })
      const items = d.items || []
      searchResults.value = Number.isFinite(maxSuggestions)
        ? items.slice(0, maxSuggestions)
        : items
    } catch { searchResults.value = [] }
    finally { searching.value = false }
  }

  // ---- 执行分析 ----
  // 成功返回分析数据，失败返回 null 并设置 result.error
  // options 会合并进请求体（如筛选条件 min_yield / max_steps / max_temperature / top_n）
  async function runAnalysis(target, options = {}) {
    const t = (target || query.value.trim() || '').trim()
    if (!t) return null
    loading.value = true
    result.value = null
    searchResults.value = []
    try {
      const d = await analyze({ query: t, ...options })
      result.value = d
      return d
    } catch (e) {
      result.value = { error: e.response?.data?.message || '分析失败' }
      return null
    } finally {
      loading.value = false
    }
  }

  // ---- 按 reaction_id 查找评分 ----
  function scoreFor(rid) {
    return scored.value.find(s => s.reaction_id === rid) || null
  }

  function clearResult() { result.value = null }

  return {
    query, loading, searching, searchResults, result,
    reactions, scored, compound, upstream, downstream, schemes, error,
    handleSearch, runAnalysis, scoreFor, clearResult,
  }
}

/** 数字格式化：保留一位小数，非数字原样返回。 */
export function fmtScore(v) {
  return v != null ? (typeof v === 'number' ? v.toFixed(1) : v) : '?'
}
