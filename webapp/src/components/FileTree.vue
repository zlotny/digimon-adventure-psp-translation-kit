<template>
  <div class="tree">
    <!-- Overall progress header -->
    <div class="overall-header">
      <div class="overall-title">Translation Progress</div>
      <div class="overall-pct" :class="overallPct === 100 ? 'complete' : ''">
        {{ overallPct }}%
      </div>
      <div class="overall-bar">
        <div class="overall-bar-fill" :style="{ width: overallPct + '%' }" />
      </div>
      <div class="overall-counts">{{ totalDone }} / {{ totalTotal }} entries</div>
      <div v-if="totalProblems > 0" class="overall-problems">{{ totalProblems }} problem{{ totalProblems === 1 ? '' : 's' }}</div>
    </div>

    <div class="top-actions">
      <button @click="store.jumpToFirstUntranslatedInProject()">⇥ First untranslated</button>
      <button @click="store.jumpToFirstProblemInProject()">⚠ First problem</button>
    </div>

    <div v-for="cat in categories" :key="cat.key" class="category">
      <div class="cat-header" @click="cat.open = !cat.open">
        <span class="caret">{{ cat.open ? '▾' : '▸' }}</span>
        <span class="cat-label">{{ cat.label }}</span>
        <span class="cat-pct" :class="catPct(cat.key) === 100 ? 'complete' : ''">
          {{ catPct(cat.key) }}%
        </span>
      </div>

      <div v-if="cat.open" class="file-list">
        <div
          v-for="file in store.files[cat.key]"
          :key="file.id"
          class="file-row"
          :class="{ active: store.currentCategory === cat.key && store.currentFileId === file.id }"
          @click="openFile(cat.key, file.id)"
        >
          <span class="file-name">{{ file.id }}</span>
          <span class="file-progress" :class="progressClass(file)">
            {{ file.done }}/{{ file.total }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, computed } from 'vue'
import { useTranslationStore } from '../stores/translation.js'

const store = useTranslationStore()

const categories = reactive([
  { key: 'dialog', label: 'Dialog', open: true },
  { key: 'other',  label: 'Other',  open: true },
  { key: 'eboot',  label: 'Eboot',  open: true },
  { key: 'names',  label: 'Names',  open: true },
  { key: 'images', label: 'Images', open: true },
])

function catDone(key) {
  return (store.files[key] || []).reduce((s, f) => s + f.done, 0)
}
function catTotal(key) {
  return (store.files[key] || []).reduce((s, f) => s + f.total, 0)
}
function catPct(key) {
  const t = catTotal(key)
  return t ? Math.round(100 * catDone(key) / t) : 0
}

const ALL_CATS = ['dialog','other','eboot','names','images']
const totalDone     = computed(() => ALL_CATS.reduce((s, k) => s + catDone(k), 0))
const totalTotal    = computed(() => ALL_CATS.reduce((s, k) => s + catTotal(k), 0))

// Rounding straight to an integer can display "100%" when a handful of
// images are still untranslated against a backdrop of 15000+ text lines —
// only report 100 when every unit is actually done, one decimal otherwise.
const overallPct = computed(() => {
  const t = totalTotal.value
  if (!t) return 0
  const d = totalDone.value
  if (d >= t) return 100
  return Math.min(99.9, Math.round(1000 * d / t) / 10)
})
const totalProblems = computed(() => ALL_CATS.reduce((s, k) =>
  s + (store.files[k] || []).reduce((s2, f) => s2 + (f.problems || 0), 0), 0))

function progressClass(file) {
  if (file.total === 0) return ''
  const pct = file.done / file.total
  if (pct === 1) return 'done'
  if (pct > 0)   return 'partial'
  return 'empty'
}

async function openFile(category, id) {
  if (store.currentCategory === category && store.currentFileId === id) return
  if (store.dirty) {
    store.showToast('Changes discarded — use Cmd+Enter to save')
    store.dirty = false
  }
  await store.loadFile(category, id)
}
</script>

<style scoped>
.tree {
  padding-bottom: 16px;
  font-size: 12px;
}

/* ── overall header ── */
.overall-header {
  padding: 14px 12px 12px;
  border-bottom: 1px solid var(--border);
}
.overall-title {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
  margin-bottom: 6px;
}
.overall-pct {
  font-size: 28px;
  font-weight: 700;
  color: var(--text);
  line-height: 1;
  margin-bottom: 8px;
}
.overall-pct.complete { color: var(--green); }

.overall-bar {
  height: 3px;
  background: var(--muted2);
  border-radius: 2px;
  margin-bottom: 6px;
  overflow: hidden;
}
.overall-bar-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
  transition: width 0.4s ease;
}

.overall-counts {
  font-size: 11px;
  color: var(--muted);
}
.overall-problems {
  font-size: 11px;
  color: var(--yellow);
  margin-top: 3px;
}

/* ── top actions ── */
.top-actions {
  padding: 8px 10px 10px;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.top-actions button {
  width: 100%;
  text-align: left;
  border-color: var(--accent);
  color: var(--accent);
  font-size: 11px;
}

/* ── categories ── */
.category { margin-top: 4px; }

.cat-header {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  cursor: pointer;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-size: 11px;
  user-select: none;
}
.cat-header:hover { color: var(--text); }

.caret { font-size: 10px; }
.cat-label { flex: 1; }

.cat-pct {
  font-size: 11px;
  color: var(--muted);
}
.cat-pct.complete { color: var(--green); }

/* ── file rows ── */
.file-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 4px 10px 4px 22px;
  cursor: pointer;
  border-left: 2px solid transparent;
  transition: background 0.1s;
}
.file-row:hover { background: var(--bg-card); }
.file-row.active {
  background: var(--bg-active);
  border-left-color: var(--accent);
}

.file-name {
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-progress { font-size: 11px; flex-shrink: 0; margin-left: 8px; }
.file-progress.empty   { color: var(--muted); }
.file-progress.partial { color: var(--yellow); }
.file-progress.done    { color: var(--green); }
</style>
