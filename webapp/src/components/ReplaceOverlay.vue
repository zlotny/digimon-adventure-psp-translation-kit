<template>
  <Transition name="overlay">
    <div v-if="open" class="overlay" @click.self="close">
      <div class="panel">

        <!-- Header -->
        <div class="header">
          <span class="title">Search &amp; Replace</span>
          <button class="close-btn" @click="close">✕</button>
        </div>

        <!-- Mode toggle -->
        <div class="mode-row">
          <button
            class="mode-btn"
            :class="{ active: mode === 'translation' }"
            @click="setMode('translation')"
          >Translated text</button>
          <button
            class="mode-btn"
            :class="{ active: mode === 'source' }"
            @click="setMode('source')"
          >Original text</button>
          <span class="mode-hint">{{ modeHint }}</span>
        </div>

        <!-- Inputs -->
        <div class="inputs">
          <div class="input-row">
            <label>Search</label>
            <input
              ref="searchRef"
              v-model="searchStr"
              @input="onSearchInput"
              placeholder="Find…"
              spellcheck="false"
            />
          </div>
          <div class="input-row">
            <label>Replace</label>
            <input
              v-model="replaceStr"
              placeholder="Replace with…"
              spellcheck="false"
            />
          </div>
        </div>

        <!-- Results preview -->
        <div class="results-header" v-if="searchStr.length >= 2">
          <span v-if="loading">Searching…</span>
          <span v-else-if="results.length === 0">No matches</span>
          <span v-else>{{ results.length }}{{ results.length === 60 ? '+' : '' }} matches</span>
        </div>

        <div v-if="results.length > 0" class="results">
          <div v-for="r in results" :key="r.category + r.file + r.index" class="result-row">
            <div class="result-path">{{ r.category }} / {{ r.file }} / #{{ r.index }}</div>
            <div class="diff">
              <div class="diff-before" v-html="hlBefore(fieldText(r))" />
              <div class="diff-arrow">→</div>
              <div class="diff-after" v-html="hlAfter(applyReplace(fieldText(r)))" />
            </div>
          </div>
          <div v-if="results.length === 60" class="limit-note">
            Showing first 60 — refine your query to see all matches.
          </div>
        </div>

        <!-- Footer -->
        <div class="footer">
          <button @click="close">Cancel</button>
          <button
            class="replace-btn"
            :disabled="results.length === 0 || replacing"
            @click="doReplace"
          >
            {{ replacing ? 'Replacing…' : `Replace all (${results.length}${results.length === 60 ? '+' : ''})` }}
          </button>
        </div>

      </div>
    </div>
  </Transition>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useTranslationStore } from '../stores/translation.js'
import { search, replaceAll } from '../api.js'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['close'])

const store = useTranslationStore()
const searchRef = ref(null)
const searchStr = ref('')
const replaceStr = ref('')
const mode = ref('translation')   // 'translation' | 'source'
const results = ref([])
const loading = ref(false)
const replacing = ref(false)
let debounceTimer = null

const modeHint = computed(() =>
  mode.value === 'translation'
    ? 'Replaces in already-translated entries'
    : 'Replaces in the English source text'
)

watch(() => props.open, (val) => {
  if (val) {
    nextTick(() => searchRef.value?.focus())
  } else {
    searchStr.value = ''
    replaceStr.value = ''
    results.value = []
  }
})

function setMode(m) {
  mode.value = m
  if (searchStr.value.length >= 2) scheduleSearch()
}

function onSearchInput() {
  results.value = []
  scheduleSearch()
}

function scheduleSearch() {
  clearTimeout(debounceTimer)
  if (searchStr.value.length < 2) { results.value = []; return }
  loading.value = true
  debounceTimer = setTimeout(doSearch, 300)
}

async function doSearch() {
  try {
    results.value = await search(searchStr.value, mode.value === 'source' ? 'source' : 'translation')
  } finally {
    loading.value = false
  }
}

// Which text field to show per mode
function fieldText(r) {
  return mode.value === 'source' ? r.source : r.translation
}

function applyReplace(text) {
  if (!searchStr.value) return text
  return text.split(searchStr.value).join(replaceStr.value)
}

function hlBefore(text) {
  if (!text || !searchStr.value) return text
  const esc = searchStr.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return text.replace(new RegExp(`(${esc})`, 'g'), '<mark class="before">$1</mark>')
}

function hlAfter(text) {
  if (!text || !replaceStr.value) return text || '<em class="empty">(empty)</em>'
  const esc = replaceStr.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return text.replace(new RegExp(`(${esc})`, 'g'), '<mark class="after">$1</mark>')
}

async function doReplace() {
  if (!results.value.length || replacing.value) return
  replacing.value = true
  try {
    const { count } = await replaceAll(searchStr.value, replaceStr.value, mode.value)
    store.showToast(`Replaced ${count} occurrence${count !== 1 ? 's' : ''}`)
    await store.loadFiles()
    if (store.currentFileId) {
      await store.loadFile(store.currentCategory, store.currentFileId)
    }
    close()
  } finally {
    replacing.value = false
  }
}

function close() { emit('close') }
</script>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 60px;
  z-index: 200;
}
.overlay-enter-active, .overlay-leave-active { transition: opacity 0.15s ease; }
.overlay-enter-from, .overlay-leave-to { opacity: 0; }

.panel {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  width: 680px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 100px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
}

/* ── header ── */
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 10px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.title { font-size: 13px; font-weight: 600; color: var(--text); }
.close-btn { background: none; border: none; color: var(--muted); font-size: 14px; cursor: pointer; padding: 2px 6px; }
.close-btn:hover { color: var(--text); }

/* ── mode toggle ── */
.mode-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.mode-btn {
  padding: 4px 12px;
  font-size: 12px;
  border-radius: 4px;
  border: 1px solid var(--border);
  color: var(--muted);
  cursor: pointer;
  background: none;
  transition: all 0.1s;
}
.mode-btn.active {
  border-color: var(--accent);
  color: var(--accent);
  background: rgba(74, 158, 255, 0.08);
}
.mode-hint { font-size: 11px; color: var(--muted); margin-left: 4px; }

/* ── inputs ── */
.inputs {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}
.input-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.input-row label { font-size: 11px; color: var(--muted); width: 52px; flex-shrink: 0; text-align: right; }
.input-row input {
  flex: 1;
  background: var(--bg-active);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-family: inherit;
  font-size: 13px;
  padding: 6px 10px;
  outline: none;
  transition: border-color 0.15s;
}
.input-row input:focus { border-color: var(--accent); }
.input-row input::placeholder { color: var(--muted); }

/* ── results header ── */
.results-header {
  padding: 6px 16px;
  font-size: 11px;
  color: var(--muted);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

/* ── results ── */
.results { overflow-y: auto; flex: 1; }

.result-row {
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
}
.result-row:last-child { border-bottom: none; }

.result-path {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--accent);
  margin-bottom: 5px;
}

.diff {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 12px;
  flex-wrap: wrap;
}
.diff-before, .diff-after {
  flex: 1;
  white-space: pre-wrap;
  word-break: break-word;
  min-width: 0;
}
.diff-before { color: var(--muted); }
.diff-after  { color: var(--text); }
.diff-arrow  { color: var(--muted); flex-shrink: 0; }

.limit-note {
  padding: 8px 16px;
  font-size: 11px;
  color: var(--muted);
  text-align: center;
}

/* ── footer ── */
.footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}
.replace-btn {
  border-color: var(--accent);
  color: var(--accent);
  font-size: 12px;
  padding: 5px 14px;
}
.replace-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.replace-btn:not(:disabled):hover {
  background: rgba(74, 158, 255, 0.1);
}

/* ── highlight marks ── */
:deep(mark.before) {
  background: rgba(248, 113, 113, 0.3);
  color: var(--text);
  border-radius: 2px;
  padding: 0 1px;
}
:deep(mark.after) {
  background: rgba(74, 222, 128, 0.25);
  color: var(--text);
  border-radius: 2px;
  padding: 0 1px;
}
:deep(em.empty) {
  color: var(--muted);
  font-style: italic;
}
</style>
