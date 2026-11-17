<script setup>
import ConstraintEvidence from './ConstraintEvidence.vue'
import PaperLinks from './PaperLinks.vue'
import { sourceLocation, paperLinks } from '../utils/routeEvidence.js'
import { computed, ref } from 'vue'
import { fmtScore } from '../composables/useReactionSearch.js'

const props = defineProps({
  reactions: { type: Array, required: true },
  scoreFor: { type: Function, required: true },
  generating: Boolean,
})
defineEmits(['generate'])

// The parent mounts a fresh comparison for each analysis with at least two results.
const ids = ref(props.reactions.slice(0, 2).map(reaction => reaction.id))
const columns = computed(() => ids.value.map(id => props.reactions.find(r => r.id === id)))

function condition(reaction, field) {
  return (reaction.conditions_summary || [])
    .filter(step => step[field])
    .map(step => [step.step, step[field]].filter(Boolean).join(' · '))
    .join('\n')
}

const rows = [
  ['反应物', r => r.reactants_text || r.reactant_smiles],
  ['产物', r => r.products_text || r.product_smiles],
  ['综合评分', r => props.scoreFor(r.id) && fmtScore(props.scoreFor(r.id).total)],
  ['收率', r => r.yield_],
  ['步骤数', r => r.steps],
  ['温度', r => condition(r, 'temperature')],
  ['时间', r => condition(r, 'time')],
  ['催化剂', r => condition(r, 'catalysts')],
  ['溶剂', r => condition(r, 'solvents')],
  ['期刊 / 年份', r => [r.literature_journal, r.literature_year].filter(Boolean).join(' · ')],
]
const tableRows = computed(() => rows.map(([label, read]) => ({
  label,
  cells: columns.value.map(reaction => {
    const value = read(reaction)
    return value == null || value === '' ? '未记录' : value
  }),
})))
</script>

<template>
  <details class="comparison">
    <summary>并排比较两条路线</summary>
    <div class="scroll">
      <table aria-label="候选反应比较">
        <thead>
          <tr>
            <th scope="col">指标</th>
            <th v-for="(id, index) in ids" :key="index" scope="col">
              <select v-model="ids[index]" :aria-label="'选择第 ' + (index + 1) + ' 条路线'">
                <option v-for="(reaction, rank) in reactions" :key="reaction.id"
                  :value="reaction.id" :disabled="reaction.id === ids[1 - index]">
                  #{{ rank + 1 }} · 反应 {{ reaction.id }}
                </option>
              </select>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="columns.some(r => r.checks?.length)">
            <th scope="row">实验室条件</th>
            <td v-for="r in columns" :key="r.id"><ConstraintEvidence :checks="r.checks || []" /></td>
          </tr>
          <tr>
            <th scope="row">依据</th>
            <td v-for="r in columns" :key="r.id">{{ sourceLocation(r) }}<PaperLinks :links="paperLinks(r)" /></td>
          </tr>
          <tr v-for="row in tableRows" :key="row.label">
            <th scope="row">{{ row.label }}</th>
            <td v-for="(cell, i) in row.cells" :key="i">{{ cell }}</td>
          </tr>
          <tr>
            <th scope="row">实验方案</th>
            <td v-for="r in columns" :key="r.id">
              <button type="button" :disabled="generating" @click="$emit('generate', r)">用这条路线生成</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </details>
</template>

<style scoped>
.comparison { margin: 12px 0; border: 1px solid var(--border); border-radius: var(--radius); background: var(--card); }
summary { padding: 12px; color: var(--primary); cursor: pointer; font-weight: 600; }
.scroll { overflow-x: auto; }
table { width: 100%; min-width: 340px; border-collapse: collapse; table-layout: fixed; font-size: 13px; }
th, td { padding: 9px; border-top: 1px solid var(--border); text-align: left; vertical-align: top; overflow-wrap: anywhere; white-space: pre-line; }
tr > th:first-child { width: 5em; color: var(--text-light); }
select, button { max-width: 100%; padding: 6px; border: 1px solid var(--border); border-radius: 5px; color: var(--primary); background: white; }
button { cursor: pointer; }
</style>
