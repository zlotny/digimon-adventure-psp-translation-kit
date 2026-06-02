<template>
  <div class="editor-shell">
    <div class="editor">

        <!-- Context above -->
        <div class="context-zone context-above">
          <div
            v-for="entry in contextAbove"
            :key="entry.index"
            class="context-entry"
            :style="speakerBorder(entry.speaker_id)"
            @click="jumpTo(entry.index)"
          >
            <span class="ctx-index">#{{ entry.index }}</span>
            <span class="ctx-text">{{ displayText(entry) }}</span>
          </div>
        </div>

        <!-- Active entry -->
        <div class="active-zone">
          <div class="source-block">
            <span class="translate-label">Translate</span>
            <div class="source-text">{{ currentEntry.source }}</div>
          </div>

          <div class="textarea-wrap">
            <textarea
              ref="textareaRef"
              v-model="inputText"
              @input="onInput"
              placeholder="Enter translation…"
              rows="3"
            />
          </div>

          <div class="toolbar">
            <div class="shortcuts">
              <kbd>⌘[</kbd><span>prev</span>
              <kbd>⌘]</kbd><span>next</span>
              <kbd>⌘↵</kbd><span>submit</span>
              <kbd>⌘'</kbd><span>next problem</span>
              <button class="keep-btn" @click="keepEnglish">Keep English</button>
              <button @click="store.jumpToFirstUntranslatedInFile()">↓ First untranslated</button>
            </div>
            <div class="byte-info" :class="byteClass">
              <span v-if="currentEntry.limit != null">
                {{ lintResult.bytes }} / {{ currentEntry.limit }} bytes
              </span>
              <span v-else class="muted">{{ lintResult.bytes }} bytes</span>
            </div>
          </div>

          <div v-if="lintResult.issues.length" class="lint-notices">
            <div
              v-for="issue in lintResult.issues"
              :key="issue.msg"
              class="notice"
              :class="'notice-' + issue.type"
            >{{ issue.msg }}</div>
          </div>
        </div>

        <!-- Context below -->
        <div class="context-zone context-below">
          <div
            v-for="entry in contextBelow"
            :key="entry.index"
            class="context-entry"
            :style="speakerBorder(entry.speaker_id)"
            @click="jumpTo(entry.index)"
          >
            <span class="ctx-index">#{{ entry.index }}</span>
            <span class="ctx-text">{{ displayText(entry) }}</span>
          </div>
        </div>

    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useTranslationStore } from '../stores/translation.js'
import { ACCENT_SUPPORTED, PROXY_CHARS, ACCENT_STRIP, LINE_CHAR_LIMITS } from '../accentMap.js'

const store = useTranslationStore()
const textareaRef = ref(null)
const inputText = ref('')

const SPEAKER_COLORS = [
  'var(--sp-0)','var(--sp-1)','var(--sp-2)','var(--sp-3)','var(--sp-4)',
  'var(--sp-5)','var(--sp-6)','var(--sp-7)','var(--sp-8)','var(--sp-9)',
]

// ── derived state ─────────────────────────────────────────────
const currentEntry = computed(() => store.entries[store.currentIndex] ?? {})

const contextAbove = computed(() => {
  const start = Math.max(0, store.currentIndex - 3)
  return store.entries.slice(start, store.currentIndex)
})

const contextBelow = computed(() => {
  return store.entries.slice(store.currentIndex + 1, store.currentIndex + 4)
})

function displayText(entry) {
  return entry.translation || entry.source
}

function speakerBorder(speakerId) {
  if (speakerId == null) return {}
  return { borderLeftColor: SPEAKER_COLORS[speakerId % 10] }
}

// ── linter ────────────────────────────────────────────────────
// Compute the byte length as the game sees it (each char = 1 byte after remapping).
function gameByteLength(text) {
  return [...text].filter(ch => ch !== '\n').length
}

const lintResult = computed(() => {
  const text = inputText.value
  const issues = []

  // Two or more accent chars in a row — the game interprets consecutive proxy
  // bytes as a control sequence, breaking the current and next dialogs.
  if ([...text].some((ch, i) => ch in ACCENT_SUPPORTED && text[i + 1] in ACCENT_SUPPORTED)) {
    issues.push({ type: 'error', msg: '⚠ Two accented letters in a row can trigger a game control sequence — separate them with a space or regular letter' })
  }

  // Chars that will be stripped to ASCII base (à â ë etc.)
  const stripped = [...new Set([...text].filter(ch => ch in ACCENT_STRIP))]
  if (stripped.length) {
    const pairs = stripped.map(ch => `${ch}→${ACCENT_STRIP[ch]}`).join(' ')
    issues.push({ type: 'warn', msg: `Stripped to ASCII at build time: ${pairs}` })
  }

  // Proxy chars used directly — these now render as accented letters, not symbols
  const proxies = [...new Set([...text].filter(ch => PROXY_CHARS.has(ch)))]
  if (proxies.length) {
    const labels = { '@':'á', '#':'é', '$':'í', '&':'ó', '*':'ú', '_':'ñ', '=':'ü' }
    const pairs = proxies.map(ch => `${ch}→${labels[ch]}`).join(' ')
    issues.push({ type: 'error', msg: `⚠ These chars now render as accented letters: ${pairs}` })
  }

  // Truly unsupported: high-codepoint chars not in any map
  const unsupported = [...new Set([...text].filter(ch =>
    ch.charCodeAt(0) > 127 && !(ch in ACCENT_SUPPORTED) && !(ch in ACCENT_STRIP) && ch !== '\n',
  ))]
  if (unsupported.length) {
    issues.push({ type: 'error', msg: `Unsupported characters: ${unsupported.join(' ')}` })
  }

  // literal \n typed by hand
  if (text.includes('\\n')) {
    issues.push({ type: 'error', msg: 'Literal \\n found — press Enter for line breaks instead' })
  }

  const isDialog = store.currentCategory === 'dialog'
  let tooManyLines = false
  if (isDialog) {
    tooManyLines = text.split('\n').length > 3
    if (tooManyLines) {
      issues.push({ type: 'error', msg: 'Dialog box only fits 3 lines (max 2 line breaks)' })
    }
    const lines = text.split('\n')
    lines.forEach((l, i) => {
      const cap = LINE_CHAR_LIMITS[Math.min(i, LINE_CHAR_LIMITS.length - 1)]
      if (l.length > cap) {
        issues.push({ type: 'warn', msg: `Line ${i + 1} may overflow (${l.length}/${cap} chars)` })
      }
    })
  }

  const bytes = gameByteLength(text)
  const limit = currentEntry.value?.limit ?? null
  const hasConsecutiveAccents = [...text].some((ch, i) => ch in ACCENT_SUPPORTED && text[i + 1] in ACCENT_SUPPORTED)
  const blocked = hasConsecutiveAccents
    || proxies.length > 0
    || unsupported.length > 0
    || text.includes('\\n')
    || tooManyLines
    || (limit !== null && bytes > limit)

  return { issues, bytes, limit, blocked }
})

const byteClass = computed(() => {
  const { bytes, limit } = lintResult.value
  if (limit == null) return ''
  if (bytes > limit) return 'over'
  if (bytes > limit * 0.85) return 'near'
  return 'ok'
})

// ── load / save ───────────────────────────────────────────────
watch([() => store.currentFileId, () => store.currentIndex], () => loadEntry(), { immediate: true })

function loadEntry() {
  const e = currentEntry.value
  if (!e.source) return
  inputText.value = e.translation || ''
  store.dirty = false
  nextTick(() => {
    textareaRef.value?.focus()
    autoResize()
  })
}

function onInput() {
  store.dirty = true
  autoResize()
}

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = el.scrollHeight + 'px'
}

async function submit() {
  if (lintResult.value.blocked) {
    store.showToast('Fix linter errors before submitting')
    return
  }
  await store.saveEntry(inputText.value)
  await advance()
}

async function keepEnglish() {
  await store.saveEntry(currentEntry.value.source)
  await advance()
}

async function advance() {
  if (store.currentIndex < store.entries.length - 1) {
    store.currentIndex++
  } else {
    await store.advanceToNextFile()
  }
}

function navigatePrev() {
  if (store.dirty) {
    store.showToast('Changes discarded — use Cmd+Enter to save')
    store.dirty = false
  }
  if (store.currentIndex > 0) {
    store.currentIndex--
  }
}

async function navigateNext() {
  if (store.dirty) {
    store.showToast('Changes discarded — use Cmd+Enter to save')
    store.dirty = false
  }
  if (store.currentIndex < store.entries.length - 1) {
    store.currentIndex++
  } else {
    await store.advanceToNextFile()
  }
}

function jumpTo(index) {
  if (store.dirty) {
    store.showToast('Changes discarded — use Cmd+Enter to save')
    store.dirty = false
  }
  store.currentIndex = index
  nextTick(() => textareaRef.value?.focus())
}

// ── global keyboard shortcuts ─────────────────────────────────
function onKeydown(e) {
  if (!store.currentFileId) return
  const mod = e.metaKey || e.ctrlKey
  if (!mod) return

  if (e.key === 'Enter') { e.preventDefault(); submit() }
  else if (e.key === '[') { e.preventDefault(); navigatePrev() }
  else if (e.key === ']') { e.preventDefault(); navigateNext() }
  else if (e.key === "'") { e.preventDefault(); store.jumpToNextProblem() }
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
/* ── shell: handles centering within .main ── */
.editor-shell {
  margin: auto;
  padding: 24px 32px;
  max-width: 720px;
  width: 100%;
}

/* ── editor body ── */
.editor {
  display: flex;
  flex-direction: column;
}

/* ── context zones ── */
.context-zone { display: flex; flex-direction: column; gap: 2px; }
.context-above { margin-bottom: 16px; }
.context-below { margin-top: 16px; }

.context-entry {
  display: flex;
  gap: 10px;
  align-items: baseline;
  padding: 6px 10px;
  border-left: 2px solid var(--muted2);
  border-radius: 0 4px 4px 0;
  cursor: pointer;
  opacity: 0.45;
  transition: opacity 0.15s;
  background: var(--bg-card);
}
.context-entry:hover { opacity: 0.75; }

.ctx-index { color: var(--muted); font-size: 10px; flex-shrink: 0; }
.ctx-text {
  color: var(--text);
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ── active entry ── */
.active-zone {
  background: var(--bg-active);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 20px;
}

.source-block { margin-bottom: 14px; }

.translate-label {
  display: block;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--accent);
  margin-bottom: 6px;
}

.source-text {
  font-size: 16px;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
}

.textarea-wrap { margin-bottom: 12px; }

textarea {
  width: 100%;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-family: inherit;
  font-size: 15px;
  line-height: 1.5;
  padding: 10px 12px;
  resize: none;
  outline: none;
  overflow: hidden;
  transition: border-color 0.15s;
}
textarea:focus { border-color: var(--accent); }
textarea::placeholder { color: var(--muted); }

/* ── toolbar ── */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.shortcuts {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--muted);
  flex-wrap: wrap;
}

.keep-btn { color: var(--muted); }

.byte-info { font-size: 12px; }
.byte-info.ok   { color: var(--muted); }
.byte-info.near { color: var(--yellow); }
.byte-info.over { color: var(--red); font-weight: 600; }
.muted { color: var(--muted); }

/* ── lint notices ── */
.lint-notices {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.notice {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 3px;
}
.notice-accent { color: var(--green);  background: rgba(74,222,128,0.08); }
.notice-warn   { color: var(--yellow); background: rgba(251,191,36,0.08); }
.notice-error  { color: var(--red);    background: rgba(248,113,113,0.1); }
.notice-info   { color: var(--green);  background: rgba(74,222,128,0.08); }
</style>
