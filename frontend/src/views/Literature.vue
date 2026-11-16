<script setup>
import { ref } from 'vue'
import { search, getOnlineLiterature } from '../api/chemistry.js'

const query = ref('')
const loading = ref(false)
const results = ref([])
const total = ref(0)
const errorMsg = ref('')
const mode = ref('local')            // local | online
const onlineSource = ref('openalex') // openalex | crossref

const fieldLabel = {
  cas_registry_id: 'CAS 号',
  literature: '文献',
  text: '反应式',
}

function switchMode(m) {
  mode.value = m
  results.value = []
  total.value = 0
  errorMsg.value = ''
}

async function doSearch() {
  if (!query.value.trim()) return
  loading.value = true
  errorMsg.value = ''
  try {
    if (mode.value === 'online') {
      const d = await getOnlineLiterature({
        q: query.value.trim(),
        source: onlineSource.value,
        limit: 20,
      })
      results.value = d.items || []
      total.value = d.total || 0
    } else {
      const d = await search({ q: query.value.trim(), type: 'all' })
      results.value = d.items || []
      total.value = d.total || 0
    }
  } catch (e) {
    results.value = []
    total.value = 0
    errorMsg.value = e.response?.data?.message || '检索失败，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <MainLayout>
    <div class="lit-root">
      <h2>文献检索</h2>
      <p class="sub">{{ mode === 'local' ? '基于 reactions.db · CAS / 文献标题 / 反应物产物全文搜索' : '在线学术文献检索 · OpenAlex / Crossref 开放 API' }}</p>

      <!-- 检索源切换 -->
      <div class="lit-tabs">
        <button :class="{ active: mode === 'local' }" @click="switchMode('local')">📂 本地库（reactions.db）</button>
        <button :class="{ active: mode === 'online' }" @click="switchMode('online')">🌐 在线文献</button>
        <span v-if="mode === 'online'" class="lit-source">
          <label><input type="radio" v-model="onlineSource" value="openalex" /> OpenAlex</label>
          <label><input type="radio" v-model="onlineSource" value="crossref" /> Crossref</label>
        </span>
      </div>

      <div class="lit-search">
        <input
          v-model="query"
          @keyup.enter="doSearch"
          :placeholder="mode === 'local' ? '搜索 CAS 号、反应物/产物或文献关键词...' : '输入文献关键词，如 cinnamic acid synthesis'"
        />
        <button @click="doSearch" :disabled="loading">{{ loading ? '检索中...' : '检索' }}</button>
      </div>

      <p v-if="errorMsg" class="lit-error">{{ errorMsg }}</p>
      <p v-if="total" class="lit-total">共 {{ total }} 条匹配结果</p>

      <div class="lit-results">
        <!-- 本地库结果：反应记录 -->
        <template v-if="mode === 'local'">
          <div v-for="r in results" :key="r.id" class="lit-card">
            <div class="lc-header">
              <strong>{{ r.cas_registry_id || '反应 #' + r.id }}</strong>
              <span class="lc-rel">{{ fieldLabel[r.match_field] || r.match_field }}</span>
            </div>
            <div class="lc-body">
              <span v-if="r.reactants_text || r.products_text" class="lc-eq">{{ r.reactants_text || '?' }} → {{ r.products_text || '?' }}</span>
              <span v-if="r.yield_ != null">收率: {{ r.yield_ }}</span>
              <span v-if="r.scheme_number">Scheme #{{ r.scheme_number }}</span>
            </div>
            <div class="lc-footer" v-if="r.literature_title">
              <span>📄 {{ r.literature_title }}</span>
            </div>
          </div>
        </template>

        <!-- 在线结果：学术文献 -->
        <template v-else>
          <div v-for="(r, i) in results" :key="r.doi || i" class="lit-card">
            <div class="lc-header">
              <strong>{{ r.title }}</strong>
              <span v-if="r.cited_by != null" class="lc-rel">被引 {{ r.cited_by }}</span>
            </div>
            <div class="lc-body">
              <span v-if="r.authors" class="lc-authors">{{ r.authors }}</span>
              <span v-if="r.journal || r.year">{{ r.journal }}{{ r.year ? ', ' + r.year : '' }}</span>
            </div>
            <div v-if="r.abstract" class="lc-abstract">{{ r.abstract }}</div>
            <div class="lc-footer">
              <a
                v-if="r.doi"
                :href="'https://doi.org/' + r.doi"
                target="_blank"
                rel="noopener"
                class="lc-doi"
              >🔗 DOI: {{ r.doi }}</a>
              <span class="lc-src">{{ r.source === 'crossref' ? 'Crossref' : 'OpenAlex' }}</span>
            </div>
          </div>
        </template>

        <div v-if="!results.length && !loading && !errorMsg" class="empty">输入关键词开始检索</div>
      </div>
    </div>
  </MainLayout>
</template>

<style scoped>
.lit-root { max-width: 900px; }
.lit-root h2 { font-size: 18px; font-weight: 700; color: var(--primary); margin-bottom: 4px; }
.sub { color: var(--text-light); font-size: 13px; margin-bottom: 16px; }

.lit-tabs { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.lit-tabs button {
  padding: 6px 14px; border: 1.5px solid var(--border); background: #fff;
  border-radius: var(--radius); font-size: 13px; font-weight: 600; cursor: pointer;
  color: var(--text-light); transition: all 0.12s;
}
.lit-tabs button.active { border-color: var(--primary); color: var(--primary); background: var(--primary-pale); }
.lit-source { display: flex; gap: 12px; margin-left: 8px; font-size: 12px; color: var(--text-light); }
.lit-source label { display: flex; align-items: center; gap: 4px; cursor: pointer; }

.lit-search { display: flex; gap: 8px; margin-bottom: 12px; }
.lit-search input { flex: 1; padding: 10px 16px; border: 1.5px solid var(--border); border-radius: var(--radius); font-size: 14px; outline: none; }
.lit-search input:focus { border-color: var(--primary-light); }
.lit-search button { padding: 10px 28px; background: var(--primary); color: #fff; border: none; border-radius: var(--radius); font-weight: 600; cursor: pointer; }
.lit-search button:disabled { opacity: 0.6; }

.lit-error { font-size: 13px; color: #991b1b; margin-bottom: 12px; }
.lit-total { font-size: 12px; color: var(--text-light); margin-bottom: 12px; }

.lit-results { display: flex; flex-direction: column; gap: 8px; }
.lit-card { padding: 16px; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); }
.lc-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 8px; }
.lc-header strong { font-size: 14px; line-height: 1.5; flex: 1; }
.lc-rel { background: #D1FAE5; color: #065F46; padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 600; white-space: nowrap; }
.lc-body { display: flex; gap: 16px; flex-wrap: wrap; align-items: center; font-size: 12px; color: var(--text-light); margin-bottom: 8px; }
.lc-eq { font-family: var(--mono); font-size: 12px; color: var(--text); }
.lc-authors { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lc-abstract {
  font-size: 12px; line-height: 1.7; color: #555;
  background: #F9FAFB; border-radius: 6px; padding: 10px 12px; margin-bottom: 8px;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
}
.lc-footer { display: flex; gap: 16px; align-items: center; font-size: 12px; }
.lc-doi { color: var(--primary); font-family: var(--mono); text-decoration: none; }
.lc-doi:hover { text-decoration: underline; }
.lc-src { color: var(--text-light); font-size: 11px; }
.empty { text-align: center; padding: 48px; color: var(--text-light); }
</style>
