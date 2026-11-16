<template>
  <MainLayout>
    <div class="page-dashboard">
      <!-- 标题 -->
      <div class="page-header">
        <h1>ChemGraph AI</h1>
        <p>化学知识增强智能研发平台</p>
      </div>

      <!-- 数据卡片 -->
      <div class="stat-cards">
        <div class="stat-card">
          <div class="stat-num">{{ stats.compounds.toLocaleString() }}</div>
          <div class="stat-label">化合物数量</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{{ stats.reactions.toLocaleString() }}</div>
          <div class="stat-label">反应数量</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{{ stats.literatures.toLocaleString() }}</div>
          <div class="stat-label">文献数量</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">{{ stats.total_nodes.toLocaleString() }}</div>
          <div class="stat-label">知识网络节点</div>
        </div>
      </div>

      <!-- 最近分析 -->
      <div class="section">
        <h2>最近分析</h2>
        <div class="task-list">
          <div v-if="recentTasks.length === 0" class="empty-hint">暂无分析记录，上传反应式开始构建知识库</div>
          <div v-for="(t, i) in recentTasks" :key="t.id || i" class="task-item" @click="$router.push('/route-planning')">
            <span class="task-icon">{{ ['🧬','🔬','💊','⚗️','🧪'][i % 5] }}</span>
            <div class="task-info">
              <strong>批次 #{{ t.batch_number }}</strong>
              <span>{{ t.status }} · {{ t.schemes_found }} schemes, {{ t.reactions_found }} reactions</span>
            </div>
            <span class="task-time">{{ t.created_at?.slice(0, 10) }}</span>
          </div>
        </div>
      </div>

      <!-- 快捷入口 -->
      <div class="section">
        <h2>快捷功能</h2>
        <div class="quick-grid">
          <div class="quick-card" @click="$router.push('/route-planning')">
            <span class="qc-icon">🧬</span>
            <strong>路线规划</strong>
            <p>输入目标化合物，获取最优合成路线</p>
          </div>
          <div class="quick-card" @click="$router.push('/knowledge-graph')">
            <span class="qc-icon">🔗</span>
            <strong>知识图谱</strong>
            <p>可视化化学实体关系网络</p>
          </div>
          <div class="quick-card" @click="$router.push('/literature')">
            <span class="qc-icon">📚</span>
            <strong>文献检索</strong>
            <p>Hybrid RAG 检索论文与专利</p>
          </div>
          <div class="quick-card" @click="$router.push('/experiment')">
            <span class="qc-icon">⚗️</span>
            <strong>实验助手</strong>
            <p>AI 生成结构化实验方案</p>
          </div>
        </div>
      </div>
    </div>
  </MainLayout>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getStats, getExtractionLogs } from '../api/chemistry.js'

const stats = ref({ compounds: 0, reactions: 0, literatures: 0, total_nodes: 0 })
const recentTasks = ref([])

onMounted(async () => {
  try {
    const d = await getStats()
    stats.value = {
      compounds: d.schemes,
      reactions: d.reactions,
      literatures: d.literatures,
      total_nodes: d.schemes + d.reactions + d.literatures,
    }
  } catch { /* 统计加载失败时保持 0 */ }

  try {
    const d = await getExtractionLogs({ limit: 5 })
    recentTasks.value = d.items || []
  } catch { /* 日志加载失败时保持空 */ }
})
</script>

<style scoped>
.page-dashboard { max-width: 960px; }
.page-header { margin-bottom: 28px; }
.page-header h1 { font-size: 26px; font-weight: 700; color: var(--primary); margin-bottom: 4px; }
.page-header p { color: var(--text-light); font-size: 14px; }

.stat-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 28px; }
.stat-card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; text-align: center; box-shadow: var(--shadow); }
.stat-num { font-size: 28px; font-weight: 700; color: var(--primary); font-family: var(--mono); }
.stat-label { font-size: 12px; color: var(--text-light); margin-top: 4px; }

.section { margin-bottom: 24px; }
.section h2 { font-size: 15px; font-weight: 600; color: var(--text); margin-bottom: 12px; }

.task-list { display: flex; flex-direction: column; gap: 6px; }
.task-item { display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); cursor: pointer; transition: all 0.12s; }
.task-item:hover { border-color: var(--primary-light); box-shadow: var(--shadow-lg); }
.task-icon { font-size: 24px; }
.task-info { flex: 1; display: flex; flex-direction: column; }
.task-info strong { font-size: 14px; }
.task-info span { font-size: 12px; color: var(--text-light); }
.task-time { font-size: 12px; color: var(--text-light); }

.quick-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.quick-card { padding: 20px; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); cursor: pointer; text-align: center; transition: all 0.12s; }
.quick-card:hover { border-color: var(--primary-light); box-shadow: var(--shadow-lg); }
.qc-icon { font-size: 32px; display: block; margin-bottom: 8px; }
.quick-card strong { display: block; font-size: 14px; margin-bottom: 4px; }
.quick-card p { font-size: 12px; color: var(--text-light); line-height: 1.4; }

@media (max-width: 768px) {
  .stat-cards, .quick-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
