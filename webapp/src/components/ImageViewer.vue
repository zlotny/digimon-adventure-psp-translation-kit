<template>
  <div class="viewer-shell">
    <div class="viewer">
      <div class="iv-header">
        <span class="iv-title">Images — {{ store.currentFileId }}</span>
        <span class="iv-count" :class="{ complete: doneCount === store.imageEntries.length }">
          {{ doneCount }}/{{ store.imageEntries.length }} translated
        </span>
      </div>

      <div class="iv-row" v-for="entry in store.imageEntries" :key="entry.idx">
        <div class="iv-label">img_{{ String(entry.idx).padStart(2, '0') }} — {{ entry.width }}×{{ entry.height }}</div>
        <div class="iv-pair">
          <div class="iv-pane">
            <div class="iv-pane-label">Original</div>
            <div class="iv-frame">
              <img :src="srcFor(entry.filename)" :alt="entry.filename" />
            </div>
          </div>
          <div class="iv-pane">
            <div class="iv-pane-label" :class="{ done: entry.translated_filename }">
              {{ entry.translated_filename ? 'Translated' : 'Not translated yet' }}
            </div>
            <div class="iv-frame">
              <img v-if="entry.translated_filename" :src="srcFor(entry.translated_filename)" :alt="entry.translated_filename" />
              <div v-else class="iv-empty">
                Save <code>{{ expectedTranslatedName(entry) }}</code><br>next to the original to fill this in.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useTranslationStore } from '../stores/translation.js'

const store = useTranslationStore()

function srcFor(filename) {
  return `/api/images/raw/${store.currentFileId}/${filename}`
}

function expectedTranslatedName(entry) {
  return entry.filename.replace(/\.png$/, '_translated.png')
}

const doneCount = computed(() => store.imageEntries.filter(e => e.translated_filename).length)
</script>

<style scoped>
.viewer-shell {
  margin: auto;
  padding: 24px 32px;
  max-width: 820px;
  width: 100%;
}

.iv-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}
.iv-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.iv-count {
  font-size: 12px;
  color: var(--muted);
}
.iv-count.complete { color: var(--green); }

.iv-row {
  margin-bottom: 28px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--border);
}
.iv-row:last-child { border-bottom: none; }

.iv-label {
  font-size: 11px;
  color: var(--muted);
  margin-bottom: 8px;
  font-family: monospace;
}

.iv-pair {
  display: flex;
  gap: 16px;
}
.iv-pane { flex: 1; min-width: 0; }

.iv-pane-label {
  font-size: 11px;
  color: var(--muted);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.iv-pane-label.done { color: var(--green); }

.iv-frame {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 80px;
}
.iv-frame img {
  max-width: 100%;
  height: auto;
  image-rendering: pixelated;
}

.iv-empty {
  font-size: 11px;
  color: var(--muted);
  text-align: center;
  line-height: 1.6;
}
.iv-empty code {
  background: var(--bg-active);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 4px;
  font-size: 10px;
  color: var(--text);
}
</style>
