import { sourceLocation, describeCheck, paperLinks, pdfEvidenceLines } from './routeEvidence.js'

export function describeFilters(filters = {}) {
  const limits = [
    ['min_yield', '最低收率', '%'], ['max_steps', '最多步骤', '步'],
    ['max_temperature', '最高温度', '°C'], ['max_time_hours', '最长单段时间', '小时'],
    ['catalyst_name', '催化剂关键词', ''], ['solvent_name', '溶剂关键词', ''],
  ]
  const descriptions = limits
    .filter(([key]) => filters[key] != null && filters[key] !== '')
    .map(([key, label, unit]) => `${label} ${filters[key]}${unit}`)
  for (const [key, label] of [['catalyst', '催化剂'], ['solvent', '溶剂'], ['workup', '后处理']]) {
    if (filters[key] === 'with') descriptions.push(`需有${label}记录`)
    if (filters[key] === 'without') descriptions.push(`不使用${label}`)
  }
  return descriptions.join('；') || '未设置'
}

export function draftContext(analysis, reaction) {
  const source = [reaction.literature_title, reaction.literature_journal, reaction.literature_year]
    .filter(Boolean).join(' · ')
  return {
    target: analysis.query,
    start: analysis.starting_material || '未指定',
    reactionId: reaction.id,
    registryId: reaction.cas_registry_id || '未记录',
    filters: describeFilters(analysis.filter_matches?.filters),
    source: source || '未记录，需查证',
    location: sourceLocation(reaction),
    links: paperLinks(reaction),
    pdfEvidence: pdfEvidenceLines(reaction),
    checks: (reaction.checks || []).map(describeCheck),
  }
}

export function draftMarkdown(context, body, notice) {
  return [
    `# ${context.target}实验方案草案`, '',
    `- 起始原料：${context.start}`,
    `- 本地反应编号：${context.reactionId}`,
    `- SciFinder 反应编号：${context.registryId}`,
    `- 实验室筛选条件：${context.filters}`,
    `- 关联文献：${context.source}`, '',
    `- 记录出处：${context.location}`, '',
    ...(context.links || []).map(link => `- [${link.label}](<${link.url}>)`),
    ...(context.pdfEvidence?.length ? ['## PDF 原文定位', ...context.pdfEvidence.map(line => `- ${line}`), ''] : []),
    ...(context.checks?.length ? ['## 实验室条件核对', ...context.checks.map(s => `- ${s}`), ''] : []),
    notice, '', body.trim(), '',
  ].join('\n')
}
