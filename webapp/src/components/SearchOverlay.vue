<template>
  <Transition name="overlay">
    <div v-if="open" class="overlay" @click.self="close" @keydown.esc="close">
      <div class="panel">
        <div class="search-bar">
          <span class="icon">⌕</span>
          <input
            ref="inputRef"
            v-model="query"
            @input="onInput"
            placeholder="Search source or translation…"
            spellcheck="false"
          />
          <span v-if="loading" class="spinner">⋯</span>
          <button class="close-btn" @click="close">✕</button>
        </div>

        <div v-if="results.length === 0 && query.length >= 2 && !loading" class="empty">
          No results for "{{ query }}"
        </div>

        <div v-if="results.length > 0" class="results">
          <div
            v-for="r in results"
            :key="r.category + r.file + r.index"
            class="result-row"
            @click="goTo(r)"
          >
            <div class="result-path">
              {{ r.category }} / {{ r.file }} / #{{ r.index }}
            </div>
            <div class="result-source" v-html="hl(r.source)" />
            <div v-if="r.translation" class="result-translation" v-html="hl(r.translation)" />
          </div>
          <div v-if="results.length === 60" class="limit-note">
            Showing first 60 matches — refine your query to narrow down.
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { useTranslationStore } from '../stores/translation.js'
import { search } from '../api.js'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['close'])

const store = useTranslationStore()
const inputRef = ref(null)
const query = ref('')
const results = ref([])
const loading = ref(false)
let debounceTimer = null

watch(() => props.open, (val) => {
  if (val) {
    nextTick(() => inputRef.value?.focus())
  } else {
    query.value = ''
    results.value = []
  }
})

function onInput() {
  clearTimeout(debounceTimer)
  if (query.value.length < 2) { results.value = []; return }
  loading.value = true
  debounceTimer = setTimeout(doSearch, 300)
}

async function doSearch() {
  try {
    results.value = await search(query.value)
  } finally {
    loading.value = false
  }
}

async function goTo(r) {
  if (store.dirty) {
    store.showToast('Changes discarded — use Cmd+Enter to save')
    store.dirty = false
  }
  close()
  await store.loadFile(r.category, r.file)
  store.currentIndex = r.index
}

function close() {
  emit('close')
}

// Wrap query matches in <mark>
function hl(text) {
  if (!query.value || !text) return text
  const escaped = query.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return text.replace(new RegExp(`(${escaped})`, 'gi'), '<mark>$1</mark>')
}
</script>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 80px;
  z-index: 200;
}

.overlay-enter-active, .overlay-leave-active { transition: opacity 0.15s ease; }
.overlay-enter-from, .overlay-leave-to { opacity: 0; }

.panel {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  width: 640px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 120px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
}

/* ── search bar ── */
.search-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.icon { font-size: 18px; color: var(--muted); }

input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  color: var(--text);
  font-family: inherit;
  font-size: 15px;
}
input::placeholder { color: var(--muted); }

.spinner { color: var(--muted); font-size: 18px; letter-spacing: 2px; }

.close-btn {
  background: none;
  border: none;
  color: var(--muted);
  font-size: 14px;
  cursor: pointer;
  padding: 2px 6px;
}
.close-btn:hover { color: var(--text); }

/* ── results ── */
.results {
  overflow-y: auto;
  flex: 1;
}

.empty {
  padding: 24px;
  text-align: center;
  color: var(--muted);
  font-size: 13px;
}

.result-row {
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.1s;
}
.result-row:last-child { border-bottom: none; }
.result-row:hover { background: var(--bg-active); }

.result-path {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--accent);
  margin-bottom: 4px;
}

.result-source {
  font-size: 12px;
  color: var(--muted);
  white-space: pre-wrap;
  word-break: break-word;
}

.result-translation {
  font-size: 13px;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
  margin-top: 2px;
}

.limit-note {
  padding: 10px 16px;
  font-size: 11px;
  color: var(--muted);
  text-align: center;
  border-top: 1px solid var(--border);
}

/* highlight */
:deep(mark) {
  background: rgba(74, 158, 255, 0.3);
  color: var(--text);
  border-radius: 2px;
  padding: 0 1px;
}
</style>
