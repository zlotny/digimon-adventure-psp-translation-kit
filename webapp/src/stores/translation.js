import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api.js'
import { PROXY_CHARS, LINE_CHAR_LIMITS } from '../accentMap.js'

export const useTranslationStore = defineStore('translation', () => {
  const files = ref({ dialog: [], eboot: [], names: [] })
  const currentCategory = ref(null)
  const currentFileId = ref(null)
  const entries = ref([])
  const currentIndex = ref(0)
  const dirty = ref(false)
  const toast = ref(null)
  let toastTimer = null

  async function loadFiles() {
    files.value = await api.getFiles()
  }

  async function loadFile(category, name) {
    const data = await api.getFile(category, name)
    currentCategory.value = category
    currentFileId.value = name
    entries.value = data.entries
    currentIndex.value = 0
    dirty.value = false
  }

  async function saveEntry(translation) {
    await api.saveTranslation(
      currentCategory.value,
      currentFileId.value,
      entries.value[currentIndex.value].index,
      translation,
    )
    entries.value[currentIndex.value].translation = translation
    dirty.value = false

    // Sync progress counter in the file list
    const list = files.value[currentCategory.value]
    const file = list?.find(f => f.id === currentFileId.value)
    if (file) {
      file.done = entries.value.filter(e => e.translation !== '').length
    }
  }

  // Ordered list of all files for sequential navigation
  function _allFiles() {
    return [
      ...files.value.dialog.map(f => ({ ...f, category: 'dialog' })),
      ...files.value.eboot.map(f => ({ ...f, category: 'eboot' })),
      ...files.value.names.map(f => ({ ...f, category: 'names' })),
    ]
  }

  async function advanceToNextFile() {
    const all = _allFiles()
    const idx = all.findIndex(
      f => f.category === currentCategory.value && f.id === currentFileId.value,
    )
    if (idx < all.length - 1) {
      const next = all[idx + 1]
      await loadFile(next.category, next.id)
    } else {
      showToast('All files complete!')
    }
  }

  function entryHasProblem(e, isDialog = false) {
    const text = e.translation
    if (!text) return false
    if (isDialog) {
      if (text.split('\n').some((l, i) => l.length > LINE_CHAR_LIMITS[Math.min(i, LINE_CHAR_LIMITS.length - 1)])) return true
      if (text.split('\n').length > 3) return true
      if (text.includes('\\n')) return true
      if ([...text].some(ch => PROXY_CHARS.has(ch))) return true
    }
    const limit = e.limit ?? null
    if (limit !== null) {
      const bytes = [...text].filter(ch => ch !== '\n').length
      if (bytes > limit) return true
    }
    return false
  }

  function firstUntranslatedIndex() {
    return entries.value.findIndex(e => e.translation === '')
  }

  async function jumpToFirstProblemInProject() {
    const all = _allFiles()
    for (const file of all) {
      await loadFile(file.category, file.id)
      const isDialog = file.category === 'dialog'
      const idx = entries.value.findIndex(e => entryHasProblem(e, isDialog))
      if (idx !== -1) {
        currentIndex.value = idx
        return
      }
    }
    showToast('No problems found in the project!')
  }

  async function jumpToNextProblem() {
    // Search forward from currentIndex + 1 within the current file first
    const isDialog = currentCategory.value === 'dialog'
    const localIdx = entries.value.findIndex((e, i) => i > currentIndex.value && entryHasProblem(e, isDialog))
    if (localIdx !== -1) {
      currentIndex.value = localIdx
      return
    }
    // Then search subsequent files
    const all = _allFiles()
    const startFileIdx = all.findIndex(
      f => f.category === currentCategory.value && f.id === currentFileId.value,
    )
    for (let fi = startFileIdx + 1; fi < all.length; fi++) {
      const file = all[fi]
      await loadFile(file.category, file.id)
      const idx = entries.value.findIndex(e => entryHasProblem(e, file.category === 'dialog'))
      if (idx !== -1) {
        currentIndex.value = idx
        return
      }
    }
    showToast('No more problems found!')
  }

  async function jumpToFirstUntranslatedInFile() {
    const idx = firstUntranslatedIndex()
    if (idx !== -1) {
      currentIndex.value = idx
    } else {
      showToast('No untranslated entries in this file')
    }
  }

  async function jumpToFirstUntranslatedInProject() {
    const all = _allFiles()
    for (const file of all) {
      if (file.done < file.total) {
        await loadFile(file.category, file.id)
        const idx = firstUntranslatedIndex()
        if (idx !== -1) {
          currentIndex.value = idx
          return
        }
      }
    }
    showToast('All entries are translated!')
  }

  function showToast(msg) {
    toast.value = msg
    if (toastTimer) clearTimeout(toastTimer)
    toastTimer = setTimeout(() => { toast.value = null }, 3000)
  }

  return {
    files,
    currentCategory,
    currentFileId,
    entries,
    currentIndex,
    dirty,
    toast,
    loadFiles,
    loadFile,
    saveEntry,
    advanceToNextFile,
    firstUntranslatedIndex,
    jumpToFirstUntranslatedInFile,
    jumpToFirstUntranslatedInProject,
    jumpToFirstProblemInProject,
    jumpToNextProblem,
    showToast,
  }
})
