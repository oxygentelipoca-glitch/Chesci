<script setup>
/**
 * ReactionCard — 反应记录卡片（共享组件）。
 *
 * 统一 RoutePlanning / ChemistryPanel 两处的反应卡片渲染：
 * 反应式、条件/文献/收率标签、四维评分条，可选"生成实验方案"按钮。
 */
import { computed } from 'vue'
import { fmtScore } from '../composables/useReactionSearch.js'

const props = defineProps({
  reaction: { type: Object, required: true },
  score: { type: Object, default: null },
  rank: { type: Number, default: null },
  selected: { type: Boolean, default: false },
  showGenerateBtn: { type: Boolean, default: false },
  generating: { type: Boolean, default: false },
})

const emit = defineEmits(['select', 'generate'])

const title = computed(() =>
  props.reaction.cas_registry_id || props.reaction.name || (props.rank ? `反应 ${props.rank}` : '反应')
)

// 方程式显示优先级：中文方程式 → SMILES 方程式 → 反应物/产物文本
const equationText = computed(() => {
  const r = props.reaction
  if (r.equation_zh && !r.equation_zh.includes('?')) return r.equation_zh
  if (r.equation && !r.equation.includes('?')) return r.equation
  if (r.reactants_text || r.products_text) return null // 走下方拼接显示
  return null
})

const scoreBars = computed(() => {
  if (!props.score) return []
  return [
    { label: '收率', value: props.score.yield_score },
    { label: '步骤', value: props.score.step_score },
    { label: '温度', value: props.score.temp_score },
    { label: '安全', value: props.score.safety_score },
  ]
})
</script>

<template>
  <div class="rc-card" :class="{ selected }" @click="emit('select')">
    <div class="rc-header">
      <span v-if="rank != null" class="rc-rank">#{{ rank }}</span>
      <div class="rc-title">
        <strong>{{ title }}</strong>
        <span class="rc-type" v-if="reaction.scheme_number">Scheme {{ reaction.scheme_number }}</span>
      </div>
      <div v-if="score" class="rc-score" :class="(score.total || 0) >= 70 ? 'good' : 'avg'">
        {{ fmtScore(score.total) }}
      </div>
    </div>

    <div class="rc-body">
      <div class="rc-equation">
        <span v-if="equationText">{{ equationText }}</span>
        <template v-else>
          <span v-if="reaction.reactants_text">{{ reaction.reactants_text }}</span>
          <span v-if="reaction.reactants_text && reaction.products_text"> → </span>
          <span v-if="reaction.products_text">{{ reaction.products_text }}</span>
          <span v-if="!reaction.reactants_text && !reaction.products_text">（无反应式数据）</span>
        </template>
      </div>

      <div class="rc-conds">
        <span v-if="reaction.conditions_summary?.length" class="cond">🔬 {{ reaction.conditions_summary.length }} 组条件</span>
        <span v-if="reaction.literature_title" class="cond">📄 {{ reaction.literature_title.slice(0, 40) }}</span>
        <span v-if="reaction.yield_ != null" class="cond yield">收率 {{ reaction.yield_ }}%</span>
        <span v-else-if="reaction.yield" class="cond yield">收率 {{ reaction.yield }}%</span>
      </div>

      <div v-if="score" class="rc-bars">
        <div v-for="b in scoreBars" :key="b.label" class="bar-row">
          <span class="bar-lbl">{{ b.label }}</span>
          <div class="bar-trk"><div class="bar-fil" :style="{ width: (b.value || 0) + '%' }"></div></div>
          <span class="bar-val">{{ fmtScore(b.value) }}</span>
        </div>
      </div>
    </div>

    <button v-if="showGenerateBtn" class="gen-btn" @click.stop="emit('generate', reaction)" :disabled="generating">
      🧬 {{ generating ? '生成中...' : '生成实验方案' }}
    </button>
  </div>
</template>

<style scoped>
.rc-card {
  background: var(--card);
  border: 1.5px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  transition: all 0.12s;
}
.rc-card:hover { border-color: var(--primary-light); }
.rc-card.selected { border-color: var(--primary); box-shadow: var(--shadow-lg); }

.rc-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.rc-rank { background: var(--primary); color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }
.rc-title { display: flex; flex-direction: column; flex: 1; }
.rc-title strong { font-size: 14px; }
.rc-type { font-size: 12px; color: var(--text-light); }
.rc-score { padding: 3px 10px; border-radius: 4px; font-weight: 700; font-size: 14px; }
.rc-score.good { background: #D1FAE5; color: #065F46; }
.rc-score.avg { background: #FEF3C7; color: #92400E; }

.rc-equation {
  font-size: 12px;
  font-family: var(--mono);
  color: var(--text-light);
  padding: 8px;
  background: #FFFBEB;
  border-radius: 4px;
  margin-bottom: 8px;
}
.rc-conds { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.cond { font-size: 11px; padding: 3px 8px; background: #F3F4F6; border-radius: 4px; }
.cond.yield { background: #D1FAE5; color: #065F46; font-weight: 600; }

.rc-bars { display: flex; flex-direction: column; gap: 3px; }
.bar-row { display: flex; align-items: center; gap: 6px; }
.bar-lbl { width: 30px; font-size: 10px; color: var(--text-light); }
.bar-trk { flex: 1; height: 5px; background: #E5E7EB; border-radius: 3px; }
.bar-fil { height: 100%; border-radius: 3px; background: linear-gradient(90deg, #F59E0B, #10B981); }
.bar-val { width: 32px; font-size: 10px; font-weight: 600; text-align: right; }

.gen-btn {
  width: 100%;
  padding: 10px;
  border: 1.5px solid #0d9488;
  border-radius: 10px;
  background: #f0fdfa;
  color: #0d9488;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.gen-btn:hover { background: #0d9488; color: #fff; }
.gen-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
