<template>
  <div class="app">
    <aside class="sidebar">
      <FileTree />
    </aside>
    <main class="main">
      <ImageViewer v-if="store.currentCategory === 'images'" />
      <TranslationEditor v-else-if="store.currentFileId" />
      <div v-else class="welcome">
        <h1>Digimon Adventure<br>Translation Helper</h1>
        <p>Select a file from the sidebar, or jump straight in:</p>
        <button class="jump-btn" @click="store.jumpToFirstUntranslatedInProject()">
          Jump to first untranslated
        </button>

        <div class="tutorial">
          <h2>Translating images &amp; the intro video</h2>
          <p>
            These don't go through this editor — translate them in any image/video
            tool, then drop the result next to the extracted file with
            <code>_translated</code> added before the extension.
          </p>
          <p>
            <strong>Images</strong> — open a file under <strong>Images</strong> in
            the sidebar to see the original next to its translation (or a
            reminder that one's missing). To fill one in, save your edit as
            <code>..._translated.png</code> (same size) right next to the
            original PNG on disk — <code>apply</code> picks these up
            automatically, and they count toward the total progress above.
          </p>
          <p>
            <strong>Intro video</strong> (optional) — <code>translations/videos/intro.mp4</code>
            → save your subtitled/dubbed version as <code>intro_translated.mp4</code>
            next to it. Not counted in the sidebar percentage, and not yet
            picked up by <code>apply</code> automatically.
          </p>
        </div>
      </div>
    </main>

    <!-- Top-right action buttons -->
    <div class="top-actions">
      <button class="action-btn" @click="replaceOpen = true" title="Search &amp; Replace">
        ⇄
      </button>
      <button class="action-btn" @click="searchOpen = true" title="Search (Cmd+F)">
        ⌕
      </button>
    </div>

    <ReplaceOverlay :open="replaceOpen" @close="replaceOpen = false" />
    <SearchOverlay :open="searchOpen" @close="searchOpen = false" />
    <Toast />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useTranslationStore } from './stores/translation.js'
import FileTree from './components/FileTree.vue'
import TranslationEditor from './components/TranslationEditor.vue'
import ImageViewer from './components/ImageViewer.vue'
import SearchOverlay from './components/SearchOverlay.vue'
import ReplaceOverlay from './components/ReplaceOverlay.vue'
import Toast from './components/Toast.vue'

const store = useTranslationStore()
const searchOpen = ref(false)
const replaceOpen = ref(false)

onMounted(() => {
  store.loadFiles()
  document.addEventListener('keydown', onGlobalKey)
})
onUnmounted(() => document.removeEventListener('keydown', onGlobalKey))

function onGlobalKey(e) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
    e.preventDefault()
    searchOpen.value = true
  }
  if (e.key === 'Escape') {
    searchOpen.value = false
  }
}
</script>

<style scoped>
.app {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.sidebar {
  width: 230px;
  flex-shrink: 0;
  background: var(--bg-side);
  border-right: 1px solid var(--border);
  overflow-y: auto;
}

.main {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.welcome {
  margin: auto;
  text-align: center;
  padding: 40px;
  max-width: 480px;
}

.welcome h1 {
  font-size: 22px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.4;
  margin-bottom: 16px;
}

.welcome p {
  color: var(--muted);
  margin-bottom: 24px;
  font-size: 13px;
}

.jump-btn {
  padding: 8px 20px;
  font-size: 13px;
  border-color: var(--accent);
  color: var(--accent);
}

/* ── home page tutorial ── */
.tutorial {
  margin-top: 36px;
  padding-top: 24px;
  border-top: 1px solid var(--border);
  text-align: left;
}
.tutorial h2 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 10px;
}
.tutorial p {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
  margin-bottom: 10px;
}
.tutorial code {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 4px;
  font-size: 11px;
  color: var(--text);
}

/* ── top-right action buttons ── */
.top-actions {
  position: fixed;
  top: 14px;
  right: 16px;
  z-index: 100;
  display: flex;
  gap: 6px;
}
.action-btn {
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--muted);
  font-size: 18px;
  width: 34px;
  height: 34px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.15s, color 0.15s;
  padding: 0;
}
.action-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}
</style>
