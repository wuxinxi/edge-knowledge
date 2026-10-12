import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../shared/api/client'
import type { Capabilities, Health, Library } from '../shared/types/api'

export const useAppStore = defineStore('app', () => {
  const libraries = ref<Library[]>([])
  const activeLibrary = ref('default')
  const health = ref<Health | null>(null)
  const capabilities = ref<Capabilities | null>(null)
  const error = ref('')
  const loading = ref(true)
  const currentLibrary = computed(() =>
    libraries.value.find((item) => item.id === activeLibrary.value),
  )

  async function refreshLibraries() {
    libraries.value = await api.libraries()
  }
  async function refreshCapabilities() {
    capabilities.value = await api.capabilities()
  }
  async function initialize() {
    loading.value = true
    error.value = ''
    try {
      const [status, items, features] = await Promise.all([
        api.health(),
        api.libraries(),
        api.capabilities(),
      ])
      health.value = status
      libraries.value = items
      capabilities.value = features
    } catch (cause) {
      health.value = null
      error.value = cause instanceof Error ? cause.message : '无法连接本地服务。'
    } finally {
      loading.value = false
    }
  }
  return {
    libraries,
    activeLibrary,
    health,
    capabilities,
    error,
    loading,
    currentLibrary,
    refreshLibraries,
    refreshCapabilities,
    initialize,
  }
})
