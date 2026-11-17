export const statusLabel = { met: '满足', conflict: '冲突', unknown: '证据不足' }

export function sourceLocation(r) {
  return [
    r.id != null && `反应 #${r.id}`,
    !r.source_refs?.length && r.scheme_number != null && `Scheme ${r.scheme_number}`,
    !r.source_refs?.length && r.source_page != null && `来源页 ${r.source_page}`,
    r.source_file,
    r.literature_title || '未关联文献',
    r.literature_doi && `DOI: ${r.literature_doi}`,
  ].filter(Boolean).join(' · ')
}

export function describeCheck(check) {
  return `${statusLabel[check.status]}｜${check.requirement}；记录：${check.record}`
}


export function paperLinks(reaction) {
  if (reaction.source_refs?.length) return reaction.source_refs
  return reaction.literature_doi
    ? [{ label: '打开论文', url: `https://doi.org/${reaction.literature_doi}` }]
    : []
}

export function pdfEvidenceLines(reaction) {
  return (reaction.paper_evidence || []).map(c =>
    `${c.field === 'yield' ? '收率' : '条件'} · PDF 第 ${c.page} 页 · ${c.quote}`
  )
}
