function edgeKey(a, b) {
  return a < b ? `${a}:${b}` : `${b}:${a}`
}

function bondToken(order) {
  return order === 2 ? '=' : order === 3 ? '#' : ''
}

/** Serialize the editor's supported neutral atom graph as a valid SMILES string. */
export function serializeSmiles(atomList, bondList) {
  if (!atomList.length) return ''
  const atomById = new Map(atomList.map(atom => [atom.id, atom]))
  const adjacency = new Map(atomList.map(atom => [atom.id, []]))
  const validBonds = bondList.filter(bond => atomById.has(bond.from) && atomById.has(bond.to))

  for (const bond of validBonds) {
    adjacency.get(bond.from).push({ bond, otherId: bond.to })
    adjacency.get(bond.to).push({ bond, otherId: bond.from })
  }

  const visited = new Set()
  const treeEdges = new Set()
  const children = new Map(atomList.map(atom => [atom.id, []]))
  const components = []

  function buildTree(atomId, parentEdge = null) {
    visited.add(atomId)
    for (const { bond, otherId } of adjacency.get(atomId) || []) {
      const key = edgeKey(bond.from, bond.to)
      if (key === parentEdge || visited.has(otherId)) continue
      treeEdges.add(key)
      children.get(atomId).push({ bond, atomId: otherId })
      buildTree(otherId, key)
    }
  }

  for (const atom of atomList) {
    if (visited.has(atom.id)) continue
    components.push(atom.id)
    buildTree(atom.id)
  }

  const ringClosures = new Map(atomList.map(atom => [atom.id, []]))
  let ringNumber = 1
  for (const bond of validBonds) {
    if (treeEdges.has(edgeKey(bond.from, bond.to))) continue
    const label = ringNumber < 10 ? String(ringNumber) : `%${ringNumber}`
    ringClosures.get(bond.from).push(`${bondToken(bond.order)}${label}`)
    ringClosures.get(bond.to).push(label)
    ringNumber += 1
  }

  function writeAtom(atomId) {
    let result = atomById.get(atomId).element
    result += (ringClosures.get(atomId) || []).join('')
    const branches = children.get(atomId) || []
    for (let index = 1; index < branches.length; index += 1) {
      const branch = branches[index]
      result += `(${bondToken(branch.bond.order)}${writeAtom(branch.atomId)})`
    }
    if (branches.length) {
      const continuation = branches[0]
      result += `${bondToken(continuation.bond.order)}${writeAtom(continuation.atomId)}`
    }
    return result
  }

  return components.map(writeAtom).join('.')
}
