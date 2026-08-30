import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { brandApi } from '@/apis/system_api'
import {
  APP_BRAND_ICON,
  APP_BRAND_NAME,
  APP_COPYRIGHT,
  normalizeBrandText
} from '@/utils/branding'

function readDebugMode() {
  try {
    return localStorage.getItem('yuxi_debug_mode') === 'true'
  } catch {
    return false
  }
}

export const useInfoStore = defineStore('info', () => {
  // 状态
  const infoConfig = ref({})
  const isLoading = ref(false)
  const isLoaded = ref(false)
  const debugMode = ref(readDebugMode())
  const showDebugModal = ref(false)

  // 计算属性 - 组织信息
  const organization = computed(() => {
    const source = infoConfig.value.organization || {}
    return {
      ...source,
      name: normalizeBrandText(source.name) || APP_BRAND_NAME,
      logo: APP_BRAND_ICON,
      avatar: APP_BRAND_ICON
    }
  })

  // 计算属性 - 品牌信息
  const branding = computed(() => {
    const source = infoConfig.value.branding || {}
    return {
      ...source,
      name: normalizeBrandText(source.name) || APP_BRAND_NAME,
      title: normalizeBrandText(source.title),
      subtitle: normalizeBrandText(source.subtitle),
      subtitles: Array.isArray(source.subtitles)
        ? source.subtitles.map(normalizeBrandText).filter(Boolean)
        : []
    }
  })

  // 计算属性 - 页脚信息
  const footer = computed(() => {
    const source = infoConfig.value.footer || {}
    return {
      user_agreement_url: '',
      privacy_policy_url: '',
      ...source,
      copyright: APP_COPYRIGHT
    }
  })

  // 动作方法
  function setInfoConfig(newConfig) {
    infoConfig.value = newConfig
    isLoaded.value = true
  }

  function setDebugMode(enabled) {
    debugMode.value = Boolean(enabled)
    try {
      if (debugMode.value) {
        localStorage.setItem('yuxi_debug_mode', 'true')
      } else {
        localStorage.removeItem('yuxi_debug_mode')
      }
    } catch {
      // localStorage 不可用时仍保留当前页面内的响应式状态。
    }
  }

  function toggleDebugMode() {
    setDebugMode(!debugMode.value)
  }

  function openDebugModal() {
    showDebugModal.value = true
  }

  function closeDebugModal() {
    showDebugModal.value = false
  }

  async function loadInfoConfig(force = false) {
    // 如果已经加载过且不强制刷新，则不重新加载
    if (isLoaded.value && !force) {
      return infoConfig.value
    }

    try {
      isLoading.value = true
      const response = await brandApi.getInfoConfig()

      if (response.success && response.data) {
        setInfoConfig(response.data)
        console.debug('信息配置加载成功:', response.data)
        return response.data
      } else {
        console.warn('信息配置加载失败，使用默认配置')
        return null
      }
    } catch (error) {
      console.error('加载信息配置时发生错误:', error)
      return null
    } finally {
      isLoading.value = false
    }
  }

  return {
    // 状态
    infoConfig,
    isLoading,
    isLoaded,
    debugMode,
    showDebugModal,

    // 计算属性
    organization,
    branding,
    footer,

    // 方法
    setDebugMode,
    toggleDebugMode,
    openDebugModal,
    closeDebugModal,
    loadInfoConfig
  }
})
