<script setup>
import { computed, ref, watch } from 'vue'
import { serializeSmiles } from '../utils/smiles.js'

const emit = defineEmits(['update:smiles', 'use-smiles'])
defineProps({ smiles: { type: String, default: '' } })

const canvas = ref(null)
const atoms = ref([])
const bonds = ref([])
const selectedAtomId = ref(null)
const activeElement = ref('C')
const bondOrder = ref(1)
const activeMode = ref('atom')
const pendingBondAtomId = ref(null)
const undoStack = ref([])
const notice = ref('')
const dragState = ref(null)
const skipNextAtomClick = ref(false)
let nextAtomId = 1

const width = 720
const height = 405
const elements = ['C', 'N', 'O', 'S', 'P', 'F', 'Cl', 'Br', 'I']

function edgeKey(a, b) {
  return a < b ? `${a}:${b}` : `${b}:${a}`
}

const smiles = computed(() => serializeSmiles(atoms.value, bonds.value))

const valenceWarning = computed(() => atoms.value.some(atom => {
  const valence = bonds.value
    .filter(bond => bond.from === atom.id || bond.to === atom.id)
    .reduce((sum, bond) => sum + bond.order, 0)
  const maxValence = { C: 4, N: 3, O: 2, F: 1, Cl: 1, Br: 1, I: 1, P: 5, S: 6 }[atom.element] || 4
  return valence > maxValence
}))

watch(smiles, value => emit('update:smiles', value), { immediate: true })

function saveUndoPoint() {
  undoStack.value.push({
    atoms: atoms.value.map(atom => ({ ...atom })),
    bonds: bonds.value.map(bond => ({ ...bond })),
  })
  if (undoStack.value.length > 40) undoStack.value.shift()
}

function getCanvasPoint(event) {
  if (!canvas.value) return { x: width / 2, y: height / 2 }
  const rect = canvas.value.getBoundingClientRect()
  return {
    x: Math.max(20, Math.min(width - 20, ((event.clientX - rect.left) / rect.width) * width)),
    y: Math.max(20, Math.min(height - 20, ((event.clientY - rect.top) / rect.height) * height)),
  }
}

function addBond(from, to, order = bondOrder.value) {
  if (from === to || bonds.value.some(bond => edgeKey(bond.from, bond.to) === edgeKey(from, to))) return false
  bonds.value.push({ from, to, order })
  return true
}

function addAtomAtPoint(event) {
  if (activeMode.value !== 'atom' || event.target.closest?.('[data-atom-id]')) return
  saveUndoPoint()
  const point = getCanvasPoint(event)
  const atom = { id: nextAtomId++, element: activeElement.value, x: point.x, y: point.y }
  atoms.value.push(atom)
  if (selectedAtomId.value !== null) addBond(selectedAtomId.value, atom.id)
  selectedAtomId.value = atom.id
  pendingBondAtomId.value = null
  notice.value = ''
}

function handleAtomClick(atomId) {
  if (skipNextAtomClick.value) {
    skipNextAtomClick.value = false
    return
  }
  if (activeMode.value === 'bond') {
    if (pendingBondAtomId.value === null) {
      pendingBondAtomId.value = atomId
      selectedAtomId.value = atomId
      return
    }
    if (pendingBondAtomId.value !== atomId) {
      saveUndoPoint()
      addBond(pendingBondAtomId.value, atomId)
      notice.value = ''
    }
    pendingBondAtomId.value = null
    selectedAtomId.value = atomId
    return
  }
  selectedAtomId.value = atomId
  pendingBondAtomId.value = null
}

function startDrag(event, atomId) {
  if (activeMode.value !== 'atom' || event.button !== 0) return
  selectedAtomId.value = atomId
  dragState.value = { atomId, start: getCanvasPoint(event), moved: false, saved: false }
  event.currentTarget.setPointerCapture?.(event.pointerId)
}

function moveAtom(event) {
  if (!dragState.value) return
  const point = getCanvasPoint(event)
  const distance = Math.hypot(point.x - dragState.value.start.x, point.y - dragState.value.start.y)
  if (distance < 3 && !dragState.value.moved) return
  if (!dragState.value.saved) {
    saveUndoPoint()
    dragState.value.saved = true
  }
  dragState.value.moved = true
  atoms.value = atoms.value.map(atom => atom.id === dragState.value.atomId
    ? { ...atom, x: point.x, y: point.y }
    : atom)
}

function endDrag() {
  if (dragState.value?.moved) skipNextAtomClick.value = true
  dragState.value = null
}

function replaceSelectedAtom() {
  if (selectedAtomId.value === null) return
  saveUndoPoint()
  atoms.value = atoms.value.map(atom => atom.id === selectedAtomId.value
    ? { ...atom, element: activeElement.value }
    : atom)
}

function deleteSelectedAtom() {
  if (selectedAtomId.value === null) return
  saveUndoPoint()
  atoms.value = atoms.value.filter(atom => atom.id !== selectedAtomId.value)
  bonds.value = bonds.value.filter(bond => bond.from !== selectedAtomId.value && bond.to !== selectedAtomId.value)
  selectedAtomId.value = null
  pendingBondAtomId.value = null
}

function undo() {
  const previous = undoStack.value.pop()
  if (!previous) return
  atoms.value = previous.atoms
  bonds.value = previous.bonds
  selectedAtomId.value = null
  pendingBondAtomId.value = null
}

function clearStructure() {
  if (!atoms.value.length) return
  saveUndoPoint()
  atoms.value = []
  bonds.value = []
  selectedAtomId.value = null
  pendingBondAtomId.value = null
  notice.value = ''
}

function addRing(size, benzene = false) {
  saveUndoPoint()
  const radius = size === 5 ? 44 : 50
  const anchor = atoms.value.find(atom => atom.id === selectedAtomId.value)
  const placeOnRight = !anchor || anchor.x <= width / 2
  const center = anchor
    ? {
      x: Math.max(radius + 12, Math.min(width - radius - 12, anchor.x + (placeOnRight ? radius * 2 : -radius * 2))),
      y: Math.max(radius + 12, Math.min(height - radius - 12, anchor.y)),
    }
    : { x: width / 2, y: height / 2 }
  const firstAngle = anchor ? (placeOnRight ? Math.PI : 0) : -Math.PI / 2
  const ringAtoms = Array.from({ length: size }, (_, index) => {
    const angle = firstAngle + (Math.PI * 2 * index) / size
    const atom = {
      id: nextAtomId++, element: 'C',
      x: center.x + Math.cos(angle) * radius,
      y: center.y + Math.sin(angle) * radius,
    }
    atoms.value.push(atom)
    return atom
  })
  ringAtoms.forEach((atom, index) => {
    const next = ringAtoms[(index + 1) % ringAtoms.length]
    addBond(atom.id, next.id, benzene && index % 2 === 0 ? 2 : 1)
  })
  if (anchor) addBond(anchor.id, ringAtoms[0].id, 1)
  selectedAtomId.value = ringAtoms[0].id
  pendingBondAtomId.value = null
}

function addBenzeneRing() {
  addRing(6, true)
}

function bondSegments(bond) {
  const from = atoms.value.find(atom => atom.id === bond.from)
  const to = atoms.value.find(atom => atom.id === bond.to)
  if (!from || !to) return []
  const dx = to.x - from.x
  const dy = to.y - from.y
  const length = Math.hypot(dx, dy) || 1
  const nx = -dy / length
  const ny = dx / length
  const offsets = bond.order === 3 ? [-4, 0, 4] : bond.order === 2 ? [-3, 3] : [0]
  return offsets.map(offset => ({
    x1: from.x + nx * offset, y1: from.y + ny * offset,
    x2: to.x + nx * offset, y2: to.y + ny * offset,
  }))
}

function atomDegree(atomId) {
  return bonds.value.filter(bond => bond.from === atomId || bond.to === atomId).length
}

async function copySmiles() {
  if (!smiles.value) return
  try {
    await navigator.clipboard.writeText(smiles.value)
    notice.value = 'SMILES 已复制'
  } catch {
    notice.value = '复制失败，请手动选择 SMILES 文本'
  }
}

function downloadSvg() {
  if (!canvas.value) return
  const copy = canvas.value.cloneNode(true)
  copy.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  const style = document.createElementNS('http://www.w3.org/2000/svg', 'style')
  style.textContent = '.bond-line{stroke:#243746;stroke-width:2;stroke-linecap:round}.atom-hit{fill:#fff;stroke:#fff;stroke-width:12}.atom-label{fill:#163a5f;font:600 17px sans-serif}.atom-label.selected{fill:#b45309}.canvas-bg{fill:#fff}.grid-dot{fill:#d9e2ea}'
  copy.insertBefore(style, copy.firstChild)
  const blob = new Blob([new XMLSerializer().serializeToString(copy)], { type: 'image/svg+xml' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'chemical-structure.svg'
  link.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <section class="structure-editor">
    <div class="editor-toolbar">
      <div class="tool-group element-tools" aria-label="选择原子元素">
        <button
          v-for="element in elements"
          :key="element"
          type="button"
          :class="['tool-button', { active: activeElement === element }]"
          @click="activeElement = element; activeMode = 'atom'"
        >{{ element }}</button>
        <button class="tool-button" type="button" :disabled="selectedAtomId === null" @click="replaceSelectedAtom">替换所选原子</button>
      </div>
      <div class="tool-group">
        <button v-for="order in [1, 2, 3]" :key="order" type="button" :class="['tool-button bond-tool', { active: bondOrder === order }]" @click="bondOrder = order">
          <span v-if="order === 1">—</span><span v-else-if="order === 2">═</span><span v-else>≡</span>
        </button>
        <button type="button" :class="['tool-button', { active: activeMode === 'bond' }]" @click="activeMode = activeMode === 'bond' ? 'atom' : 'bond'; pendingBondAtomId = null">
          {{ activeMode === 'bond' ? '选择两个原子连键' : '连键模式' }}
        </button>
      </div>
      <div class="tool-group">
        <button type="button" class="tool-button" @click="addRing(5)">五元环</button>
        <button type="button" class="tool-button" @click="addRing(6)">六元环</button>
        <button type="button" class="tool-button" @click="addBenzeneRing">苯环</button>
      </div>
      <div class="tool-group editor-actions">
        <button type="button" class="tool-button" :disabled="!undoStack.length" @click="undo">撤销</button>
        <button type="button" class="tool-button" :disabled="selectedAtomId === null" @click="deleteSelectedAtom">删除原子</button>
        <button type="button" class="tool-button" :disabled="!atoms.length" @click="clearStructure">清空</button>
      </div>
    </div>

    <div class="canvas-help">选中原子后点击空白处可继续接链；拖动原子可调整位置。连键模式下依次点两个原子创建键。点击“苯环”可添加凯库勒式苯环。</div>
    <svg
      ref="canvas"
      class="drawing-canvas"
      viewBox="0 0 720 405"
      role="img"
      aria-label="化学结构绘图区域"
      @click="addAtomAtPoint"
      @pointermove="moveAtom"
      @pointerup="endDrag"
      @pointercancel="endDrag"
    >
      <defs>
        <pattern id="structure-grid" width="20" height="20" patternUnits="userSpaceOnUse"><circle class="grid-dot" cx="1" cy="1" r="1" /></pattern>
      </defs>
      <rect class="canvas-bg" width="720" height="405" rx="10" />
      <rect width="720" height="405" rx="10" fill="url(#structure-grid)" />
      <g v-for="bond in bonds" :key="`${bond.from}-${bond.to}`">
        <line v-for="(segment, index) in bondSegments(bond)" :key="index" class="bond-line" v-bind="segment" />
      </g>
      <g
        v-for="atom in atoms"
        :key="atom.id"
        :data-atom-id="atom.id"
        class="atom-node"
        @pointerdown.stop="startDrag($event, atom.id)"
        @click.stop="handleAtomClick(atom.id)"
      >
        <circle class="atom-hit" :cx="atom.x" :cy="atom.y" r="12" />
        <text v-if="atom.element !== 'C' || atomDegree(atom.id) === 0 || selectedAtomId === atom.id" :x="atom.x" :y="atom.y + 6" :class="['atom-label', { selected: selectedAtomId === atom.id }]" text-anchor="middle">{{ atom.element }}</text>
        <circle v-if="selectedAtomId === atom.id" class="atom-selection" :cx="atom.x" :cy="atom.y" r="15" />
        <circle v-if="pendingBondAtomId === atom.id" class="bond-origin" :cx="atom.x" :cy="atom.y" r="19" />
      </g>
      <text v-if="!atoms.length" x="360" y="205" class="canvas-empty" text-anchor="middle">点击画布放置第一个原子</text>
    </svg>

    <div class="smiles-row">
      <label class="smiles-field">
        <span>草图 SMILES</span>
        <input :value="smiles" readonly placeholder="绘制结构后自动生成" />
      </label>
      <button type="button" class="editor-action-primary" :disabled="!smiles" @click="emit('use-smiles', smiles)">用于路线分析</button>
      <button type="button" class="tool-button" :disabled="!smiles" @click="copySmiles">复制 SMILES</button>
      <button type="button" class="tool-button" :disabled="!atoms.length" @click="downloadSvg">导出 SVG</button>
    </div>
    <p class="editor-note" :class="{ warning: valenceWarning }">
      {{ valenceWarning ? '有原子的键阶超过常见价态，请检查结构。' : '支持常见中性原子和单、双、三键。SMILES 未做规范化；不处理形式电荷和立体化学，使用前请核对。' }}
      <span v-if="notice">{{ notice }}</span>
    </p>
  </section>
</template>

<style scoped>
.structure-editor { display: flex; flex-direction: column; gap: 10px; margin-top: 16px; }
.editor-toolbar { display: flex; flex-wrap: wrap; gap: 8px; }
.tool-group { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg); }
.tool-button { min-height: 32px; padding: 5px 9px; border: 1px solid transparent; border-radius: 5px; background: #fff; color: var(--text); font: inherit; font-size: 12px; cursor: pointer; }
.tool-button:hover { border-color: var(--primary-light); }
.tool-button.active { border-color: var(--primary); background: var(--primary-pale); color: var(--primary); font-weight: 700; }
.tool-button:disabled, .editor-action-primary:disabled { opacity: .5; cursor: not-allowed; }
.bond-tool { min-width: 34px; font-size: 18px; line-height: 1; }
.canvas-help { color: var(--text-light); font-size: 12px; }
.drawing-canvas { width: 100%; aspect-ratio: 16 / 9; border: 1px solid var(--border); border-radius: 10px; background: #fff; touch-action: none; cursor: crosshair; }
.grid-dot { fill: #d9e2ea; }
.canvas-bg { fill: #fff; }
.bond-line { stroke: #243746; stroke-width: 2; stroke-linecap: round; }
.atom-node { cursor: grab; }
.atom-node:active { cursor: grabbing; }
.atom-hit { fill: #fff; stroke: #fff; stroke-width: 12; }
.atom-label { fill: var(--primary); font: 600 17px var(--sans); pointer-events: none; }
.atom-label.selected { fill: #b45309; }
.atom-selection { fill: none; stroke: #d97706; stroke-width: 1.5; stroke-dasharray: 3 3; pointer-events: none; }
.bond-origin { fill: none; stroke: var(--primary-light); stroke-width: 2; pointer-events: none; }
.canvas-empty { fill: #93a4b4; font: 14px var(--sans); pointer-events: none; }
.smiles-row { display: flex; align-items: end; gap: 8px; flex-wrap: wrap; }
.smiles-field { display: flex; flex: 1; min-width: 220px; flex-direction: column; gap: 5px; color: var(--text-light); font-size: 11px; }
.smiles-field input { width: 100%; min-height: 36px; padding: 7px 10px; border: 1px solid var(--border); border-radius: var(--radius); color: var(--text); font: 12px var(--mono); }
.editor-action-primary { min-height: 36px; padding: 7px 12px; border: 0; border-radius: var(--radius); background: var(--primary); color: #fff; font: inherit; font-size: 12px; font-weight: 600; cursor: pointer; }
.editor-note { color: var(--text-light); font-size: 11px; }
.editor-note.warning { color: #b45309; }
.editor-note span { margin-left: 8px; color: var(--success); }
@media (max-width: 700px) { .editor-actions { margin-left: 0; } .smiles-row > button { flex: 1; } }
</style>
