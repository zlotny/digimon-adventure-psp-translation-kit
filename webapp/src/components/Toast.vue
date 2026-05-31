<template>
  <Transition name="toast">
    <div v-if="store.toast" class="toast">{{ store.toast }}</div>
  </Transition>
</template>

<script setup>
import { useTranslationStore } from '../stores/translation.js'
const store = useTranslationStore()
</script>

<style scoped>
.toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 10px 16px;
  border-radius: 6px;
  font-size: 12px;
  pointer-events: none;
  z-index: 100;
  box-shadow: 0 4px 16px rgba(0,0,0,0.4);
}

.toast-enter-active, .toast-leave-active { transition: opacity 0.2s, transform 0.2s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(6px); }
</style>
