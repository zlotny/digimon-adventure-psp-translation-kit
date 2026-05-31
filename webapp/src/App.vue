<template>
  <div class="app">
    <aside class="sidebar">
      <FileTree />
    </aside>
    <main class="main">
      <TranslationEditor v-if="store.currentFileId" />
      <div v-else class="welcome">
        <h1>Digimon Adventure<br>Translation Helper</h1>
        <p>Select a file from the sidebar, or jump straight in:</p>
        <button class="jump-btn" @click="store.jumpToFirstUntranslatedInProject()">
          Jump to first untranslated
        </button>
      </div>
    </main>
    <Toast />
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useTranslationStore } from './stores/translation.js'
import FileTree from './components/FileTree.vue'
import TranslationEditor from './components/TranslationEditor.vue'
import Toast from './components/Toast.vue'

const store = useTranslationStore()
onMounted(() => store.loadFiles())
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
  max-width: 400px;
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
</style>
