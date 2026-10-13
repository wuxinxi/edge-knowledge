<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  Check,
  Palette,
  ShieldCheck,
  Database,
  Search,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  SlidersHorizontal,
  Sparkles,
} from '@lucide/vue'
import './settings.css'
import BackupSettings from '../backup/BackupSettings.vue'
import AccessSettings from '../access/AccessSettings.vue'
import AppearanceSettings from './AppearanceSettings.vue'
import { useI18n } from '../../shared/i18n'
import { api } from '../../shared/api/client'
import type { Capabilities, Settings, SettingsPatch } from '../../shared/types/api'
import { useAppStore } from '../../app/store'

const { t } = useI18n()
type SettingsSection = 'appearance' | 'models' | 'images' | 'retrieval' | 'data' | 'access'
const activeSection = ref<SettingsSection>('appearance')
const sections = computed(() => [
  { id: 'appearance' as const, label: t('通用'), icon: Palette },
  { id: 'models' as const, label: t('模型'), icon: Sparkles },
  { id: 'images' as const, label: t('图片'), icon: Eye },
  { id: 'retrieval' as const, label: t('检索'), icon: Search },
  { id: 'access' as const, label: t('权限与隐私'), icon: ShieldCheck },
  { id: 'data' as const, label: t('数据与关于'), icon: Database },
])
function moveTab(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key))
    return
  event.preventDefault()
  const index = sections.value.findIndex((section) => section.id === activeSection.value)
  const next =
    event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? sections.value.length - 1
        : (index +
            (['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1) +
            sections.value.length) %
          sections.value.length
  activeSection.value = sections.value[next]!.id
  document.getElementById(`settings-tab-${activeSection.value}`)?.focus()
}
const settings = ref<Settings>()
const key = ref('')
const revealKey = ref(false)
const saving = ref(false)
const saved = ref(false)
watch(activeSection, () => {
  saved.value = false
})
const error = ref('')
const capabilities = ref<Capabilities>()
const app = useAppStore()
let capabilityRequest = 0
watch(
  () => settings.value?.model,
  async (model) => {
    const version = ++capabilityRequest
    if (!model?.trim()) {
      capabilities.value = undefined
      return
    }
    try {
      const result = await api.capabilities(model)
      if (version === capabilityRequest) capabilities.value = result
    } catch {
      if (version === capabilityRequest) capabilities.value = undefined
    }
  },
)
async function load() {
  error.value = ''
  try {
    settings.value = await api.settings()
    capabilities.value = await api.capabilities()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t('无法读取设置。')
  }
}
async function save(clearKey = false) {
  if (!settings.value) return
  saving.value = true
  saved.value = false
  error.value = ''
  try {
    const section = activeSection.value
    const current = settings.value
    const values: SettingsPatch =
      section === 'models'
        ? {
            base_url: current.base_url,
            model: current.model.trim(),
            stream: current.stream,
          }
        : section === 'images'
          ? { image_qa_mode: current.image_qa_mode }
          : {
              top_k: current.top_k,
              min_score: current.min_score,
              chunk_size: current.chunk_size,
              chunk_overlap: current.chunk_overlap,
            }
    const submittedKey = key.value.trim()
    const result = await api.updateSettings({
      ...values,
      ...(section === 'models'
        ? clearKey
          ? { api_key: '' }
          : submittedKey
            ? { api_key: submittedKey }
            : {}
        : {}),
    })
    settings.value = {
      ...settings.value,
      ...values,
      api_key_configured: result.api_key_configured,
      credential_storage: result.credential_storage,
      credential_message: result.credential_message,
      credential_migration_pending: result.credential_migration_pending,
    }
    if (section === 'models' && key.value.trim() === submittedKey) key.value = ''
    saved.value = activeSection.value === section
    await app.refreshCapabilities()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t('保存失败。')
  } finally {
    saving.value = false
  }
}
onMounted(() => {
  void load()
})
</script>

<template>
  <section class="standard-page settings-page">
    <header class="page-header">
      <div>
        <h1>{{ t('偏好设置') }}</h1>
        <p class="page-subtitle">{{ t('为你的工作习惯量身设置') }}</p>
      </div>
    </header>
    <div class="settings-layout">
      <div class="settings-tabs-shell">
        <nav class="settings-tabs" role="tablist" :aria-label="t('偏好设置')" @keydown="moveTab">
          <button
            v-for="section in sections"
            :key="section.id"
            :id="`settings-tab-${section.id}`"
            type="button"
            role="tab"
            :aria-selected="activeSection === section.id"
            :tabindex="activeSection === section.id ? 0 : -1"
            aria-controls="settings-panel"
            :class="{ active: activeSection === section.id }"
            @click="activeSection = section.id"
          >
            <component :is="section.icon" :size="16" />{{ section.label }}
          </button>
        </nav>
      </div>
      <div
        class="page-content settings-content"
        id="settings-panel"
        role="tabpanel"
        :aria-labelledby="`settings-tab-${activeSection}`"
      >
        <BackupSettings v-if="activeSection === 'data'" />
        <AccessSettings v-if="activeSection === 'access'" />
        <AppearanceSettings
          v-if="activeSection === 'appearance' || activeSection === 'data'"
          :section="activeSection"
        />
        <div v-if="error" role="alert" class="inline-error">
          {{ error
          }}<button v-if="!settings" class="text-button" @click="load">{{ t('重新加载') }}</button>
        </div>
        <div
          v-if="
            !settings &&
            !error &&
            activeSection !== 'appearance' &&
            activeSection !== 'data' &&
            activeSection !== 'access'
          "
          class="empty-state"
        >
          <LoaderCircle class="spin" :size="24" />{{ t('正在读取设置…') }}
        </div>
        <form
          v-if="settings && ['models', 'images', 'retrieval'].includes(activeSection)"
          :inert="saving"
          @submit.prevent="save()"
        >
          <section v-if="activeSection === 'models'" class="settings-card">
            <div class="settings-card-heading">
              <span class="settings-icon"><Sparkles :size="20" /></span>
              <div>
                <h2>{{ t('回答生成') }}</h2>
                <p>{{ t('使用 DeepSeek，把检索到的资料组织成答案。') }}</p>
              </div>
              <span v-if="settings.api_key_configured" class="configured-badge"
                ><Check :size="12" />{{ t('已配置') }}</span
              >
            </div>
            <div class="settings-fields">

                <p v-if="settings.credential_message" class="inline-error" role="alert">
                  {{ settings.credential_message
                  }}<span v-if="settings.credential_migration_pending">
                    {{ t('旧配置仍保留，请解锁系统凭据库后重新保存密钥。') }}</span
                  >
                </p>
                <div class="field">
                  <label for="api-key">DeepSeek API Key</label>
                  <div class="key-input">
                    <KeyRound :size="17" /><input
                      id="api-key"
                      v-model="key"
                      :type="revealKey ? 'text' : 'password'"
                      autocomplete="off"
                      :placeholder="
                        settings.api_key_configured
                          ? t('已保存密钥；留空则保留')
                          : t('输入你的 API Key')
                      "
                      maxlength="500"
                    /><button
                      type="button"
                      class="icon-button"
                      :aria-label="revealKey ? t('隐藏密钥') : t('显示密钥')"
                      @click="revealKey = !revealKey"
                    >
                      <EyeOff v-if="revealKey" :size="17" /><Eye v-else :size="17" />
                    </button>
                  </div>
                  <p>
                    {{ t('密钥保存在系统凭据库，保存后不会从服务端返回。')
                    }}<button
                      v-if="settings.api_key_configured"
                      type="button"
                      class="text-button danger"
                      :disabled="saving"
                      @click="save(true)"
                    >
                      {{ t('移除密钥') }}
                    </button>
                  </p>
                </div>
                <div class="field-row">
                  <div class="field">
                    <label for="base-url">{{ t('服务地址') }}</label
                    ><select id="base-url" v-model="settings.base_url">
                      <option value="https://api.deepseek.com">https://api.deepseek.com</option>
                      <option value="https://api.deepseek.com/v1">
                        https://api.deepseek.com/v1
                      </option>
                    </select>
                  </div>
                  <div class="field">
                    <label for="model">{{ t('模型名称') }}</label
                    ><input
                      id="model"
                      v-model="settings.model"
                      maxlength="100"
                      required
                      placeholder="deepseek-flash"
                    />
                    <p>
                      {{ t('填写账户可用的 DeepSeek 模型名称。')
                      }}{{
                        capabilities?.generator.images
                          ? t('当前模型支持图片输入。')
                          : t('当前模型未声明图片输入能力。')
                      }}
                    </p>
                  </div>
                </div>
              <label class="toggle-row"
                ><span
                  ><strong>{{ t('流式显示回答') }}</strong
                  ><small>{{ t('生成的内容逐段呈现') }}</small></span
                ><input v-model="settings.stream" type="checkbox" role="switch" /><span
                  class="toggle-visual"
                ></span
              ></label>
            </div>
          </section>

          <section v-if="activeSection === 'images'" class="settings-card">
            <div class="settings-card-heading">
              <span class="settings-icon"><Eye :size="20" /></span>
              <div>
                <h2>{{ t('图片理解') }}</h2>
                <p>{{ t('图片检索在本机进行，解读方式由你选择。') }}</p>
              </div>
            </div>
            <div class="settings-fields">
              <div class="field">
                <label for="image-mode">{{ t('图片问答方式') }}</label
                ><select id="image-mode" v-model="settings.image_qa_mode">
                  <option value="local_ocr">{{ t('本地 OCR 文字 · 图片留在本机') }}</option>
                  <option value="cloud_vision">{{ t('云端看图 · 发送相关图片') }}</option>
                </select>
              </div>
              <p v-if="settings.image_qa_mode === 'local_ocr'" class="settings-note">
                <span v-if="capabilities?.ocr.engine"
                  >{{ t('识别引擎') }}：{{ capabilities.ocr.engine }}。
                </span>
                {{ t('默认只发送本地提取的相关文字，不发送图片。')
                }}{{
                  capabilities?.ocr.available
                    ? t('本地文字识别已就绪。')
                    : t('本地文字识别尚未准备就绪。')
                }}{{ t('没有可读文字的照片可检索和查看，文本模型无法据此解读画面。') }}
              </p>
              <p v-else class="settings-note">
                {{
                  t(
                    '需要支持图片的模型，例如 deepseek-flash。每次最多发送 3 张相关图片，提问时还需勾选本次授权。',
                  )
                }}{{
                  capabilities?.generator.images
                    ? t('当前模型支持云端看图。')
                    : t('当前模型不支持图片输入，服务端会阻止发送。')
                }}
              </p>
            </div>
          </section>

          <section v-if="activeSection === 'retrieval'" class="settings-card">
            <div class="settings-card-heading">
              <span class="settings-icon"><SlidersHorizontal :size="20" /></span>
              <div>
                <h2>{{ t('检索与文档切片') }}</h2>
                <p>{{ t('在上下文完整度和检索精度之间找到平衡。') }}</p>
              </div>
            </div>
            <div class="settings-fields">
              <div class="field-row">
                <div class="field">
                  <label for="top-k">{{ t('每次检索片段数') }}</label
                  ><input
                    id="top-k"
                    v-model.number="settings.top_k"
                    type="number"
                    min="1"
                    max="20"
                    required
                  />
                  <p>{{ t('范围 1–20，默认 5 个片段。') }}</p>
                </div>
                <div class="field">
                  <label for="min-score">{{ t('最低相关度') }}</label
                  ><input
                    id="min-score"
                    v-model.number="settings.min_score"
                    type="number"
                    min="-1"
                    max="1"
                    step="0.05"
                    required
                  />
                  <p>{{ t('低于此值时不会发送片段进行生成。') }}</p>
                </div>
              </div>
              <div class="field-row">
                <div class="field">
                  <label for="chunk-size">{{ t('切片长度（字符）') }}</label
                  ><input
                    id="chunk-size"
                    v-model.number="settings.chunk_size"
                    type="number"
                    min="100"
                    max="4000"
                    required
                  />
                </div>
                <div class="field">
                  <label for="chunk-overlap">{{ t('重叠长度（字符）') }}</label
                  ><input
                    id="chunk-overlap"
                    v-model.number="settings.chunk_overlap"
                    type="number"
                    min="0"
                    :max="Math.min(1000, settings.chunk_size - 1)"
                    required
                  />
                </div>
              </div>
              <p class="settings-note">
                {{ t('切片参数只对之后导入的文档生效。已有文档如需调整，请删除后重新导入。') }}
              </p>
            </div>
          </section>
          <div class="settings-actions">
            <span v-if="saved" class="save-success" role="status"
              ><Check :size="16" />{{ t('设置已保存') }}</span
            ><span v-else>{{ t('所有设置都保存在当前设备') }}</span
            ><button class="button primary" :disabled="saving">
              <LoaderCircle v-if="saving" :size="16" class="spin" /><Check v-else :size="16" />{{
                saving ? t('正在保存…') : t('保存设置')
              }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </section>
</template>
