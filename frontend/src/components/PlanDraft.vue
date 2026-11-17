<script setup>
import PaperLinks from './PaperLinks.vue'
import { ref } from 'vue'
import { draftMarkdown } from '../utils/planDraft.js'

const props = defineProps({
  draft: { type: Object, required: true },
  context: { type: Object, required: true },
})
const body = ref(props.draft.plan || '')
const editing = ref(false)
const notice = props.draft.review_notice || '研究草案，使用前请核对原始文献并由专业人员审核。'

function download() {
  const markdown = draftMarkdown(props.context, body.value, notice)
  const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `ChemFinder-反应${props.context.reactionId}-实验草案.md`
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>

<template>
  <section class="draft">
    <h3>反应 {{ context.reactionId }} 的实验方案草案</h3>
    <p>{{ context.start }} → {{ context.target }}</p>
    <p>筛选条件：{{ context.filters }}</p>
    <p>记录出处：{{ context.location }}</p>
    <PaperLinks :links="context.links" />
    <ul v-if="context.checks.length" aria-label="选定路线条件核对">
      <li v-for="line in context.checks" :key="line">{{ line }}</li>
    </ul>
    <p v-if="draft.error || !draft.plan?.trim()" role="alert">
      {{ draft.error || '模型未返回草案正文，请重新生成。' }}
    </p>
    <template v-else>
      <p>{{ notice }}</p>
      <div class="actions">
        <button type="button" @click="editing = !editing">{{ editing ? '预览正文' : '编辑正文' }}</button>
        <button type="button" :disabled="!body.trim()" @click="download">导出 Markdown</button>
      </div>
      <template v-if="editing">
        <p>修改保留在当前页面，离开或重新分析前请导出。</p>
        <textarea v-model="body" aria-label="实验方案正文" rows="14" />
      </template>
      <pre v-else>{{ body || '正文为空，可继续编辑。' }}</pre>
    </template>
  </section>
</template>

<style scoped>
.draft { padding: 16px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--card); overflow-wrap: anywhere; }
p { margin: 6px 0; font-size: 13px; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
button { background: white; color: var(--primary); border: 1px solid var(--border); border-radius: 6px; padding: 7px 12px; cursor: pointer; }
button:disabled { opacity: .5; }
textarea { width: 100%; box-sizing: border-box; resize: vertical; padding: 10px; }
pre, textarea { white-space: pre-wrap; font: inherit; line-height: 1.6; }
</style>
