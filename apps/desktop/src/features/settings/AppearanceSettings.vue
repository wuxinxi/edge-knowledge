<script setup lang="ts">
import { Check, RotateCcw, Keyboard, ShieldCheck } from '@lucide/vue'
import { useI18n } from '../../shared/i18n'
import { useAppStore } from '../../app/store'
import ThemeOption from './ThemeOption.vue'
defineProps<{ section: 'appearance' | 'data' }>()
const { t, preferences } = useI18n()
const app = useAppStore()
</script>
<template>
  <template v-if="section === 'appearance'">
    <section class="settings-card appearance-card" id="appearance-settings">
      <div class="settings-card-heading">
        <div>
          <h2>{{ t('外观与语言') }}</h2>
          <p>{{ t('让工作空间适合你的阅读习惯。') }}</p>
        </div>
        <span class="autosave-label"><span></span>{{ t('自动保存') }}</span>
      </div>
      <div class="preference-rows">
        <div class="preference-row theme-preference">
          <div class="preference-label">
            <strong>{{ t('主题') }}</strong>
            <p>{{ t('选择你习惯的界面明暗。') }}</p>
          </div>
          <div class="theme-options-refined" role="group" :aria-label="t('主题')">
            <ThemeOption
              v-for="option in ['system', 'light', 'dark'] as const"
              :key="option"
              :option="option"
              :selected="preferences.values.theme === option"
              @select="preferences.values.theme = option"
            />
          </div>
        </div>
        <div class="preference-row">
          <div class="preference-label">
            <strong>{{ t('主题配色') }}</strong>
            <p>{{ t('用于选中状态与主要操作。') }}</p>
          </div>
          <div class="color-control">
            <div class="color-dots" role="group" :aria-label="t('主题配色')">
              <button
                v-for="option in ['neutral', 'sage', 'indigo', 'amber'] as const"
                :key="option"
                type="button"
                :class="[option, { selected: preferences.values.accent === option }]"
                :aria-label="
                  t(
                    option === 'neutral'
                      ? '石墨蓝'
                      : option === 'sage'
                        ? '鼠尾草绿'
                        : option === 'indigo'
                          ? '靛蓝'
                          : '琥珀',
                  )
                "
                :title="
                  t(
                    option === 'neutral'
                      ? '石墨蓝'
                      : option === 'sage'
                        ? '鼠尾草绿'
                        : option === 'indigo'
                          ? '靛蓝'
                          : '琥珀',
                  )
                "
                :aria-pressed="preferences.values.accent === option"
                @click="preferences.values.accent = option"
              >
                <Check v-if="preferences.values.accent === option" :size="12" />
              </button>
            </div>
            <span>{{
              t(
                preferences.values.accent === 'neutral'
                  ? '石墨蓝'
                  : preferences.values.accent === 'sage'
                    ? '鼠尾草绿'
                    : preferences.values.accent === 'indigo'
                      ? '靛蓝'
                      : '琥珀',
              )
            }}</span>
          </div>
        </div>
        <div class="preference-row">
          <div class="preference-label">
            <label for="interface-language">{{ t('界面语言') }}</label>
            <p>{{ t('资料原文和已有回答保持不变。') }}</p>
          </div>
          <select
            id="interface-language"
            v-model="preferences.values.language"
            class="preference-select"
          >
            <option value="zh-CN">简体中文</option>
            <option value="en-US">English</option>
          </select>
        </div>
        <div class="preference-row">
          <div class="preference-label">
            <label for="interface-font">{{ t('阅读字体') }}</label>
            <p>{{ t('选择适合长时间阅读的字体。') }}</p>
          </div>
          <select
            id="interface-font"
            v-model="preferences.values.fontFamily"
            class="preference-select"
          >
            <option value="system">{{ t('系统字体') }}</option>
            <option value="serif">{{ t('衬线字体') }}</option>
            <option value="mono">{{ t('等宽字体') }}</option>
          </select>
        </div>
        <div class="preference-row">
          <div class="preference-label">
            <label for="interface-font-size">{{ t('字体大小') }}</label>
            <p>{{ t('应用到界面与对话内容。') }}</p>
          </div>
          <div class="font-size-control">
            <span class="font-sample small">A</span
            ><input
              id="interface-font-size"
              v-model.number="preferences.values.fontSize"
              type="range"
              min="12"
              max="18"
              step="1"
            /><span class="font-sample large">A</span
            ><output for="interface-font-size"
              >{{ preferences.values.fontSize }}<small>px</small></output
            >
          </div>
        </div>
      </div>
      <div class="appearance-preview">
        <span class="preview-glyph">Aa</span>
        <div>
          <span>{{ t('阅读预览') }}</span>
          <p>{{ t('你的资料和对话，井然有序。') }}</p>
        </div>
      </div>
      <div class="appearance-footer">
        <span>{{ t('更改即时生效') }}</span
        ><button type="button" class="text-button" @click="preferences.reset">
          <RotateCcw :size="12" />{{ t('恢复默认外观') }}
        </button>
      </div>
      <div v-if="preferences.storageError" class="inline-error" role="alert">
        {{ t('界面设置保存失败，请检查浏览器存储权限。') }}
      </div>
    </section>
    <section class="settings-card interaction-card">
      <div class="settings-card-heading">
        <div>
          <h2>{{ t('输入与对话') }}</h2>
          <p>{{ t('对话在此设备保存，可新建、重命名、删除和导出。') }}</p>
        </div>
        <Keyboard :size="18" />
      </div>
      <div class="preference-rows">
        <div class="preference-row">
          <div class="preference-label">
            <label for="send-shortcut">{{ t('发送快捷键') }}</label>
            <p>{{ t('Shift + Enter 始终用于换行。') }}</p>
          </div>
          <select
            id="send-shortcut"
            v-model="preferences.values.sendKey"
            class="preference-select shortcut-select"
          >
            <option value="enter">Enter</option>
            <option value="mod-enter">Ctrl / ⌘ + Enter</option>
          </select>
        </div>
      </div>
      <div class="shortcut-note">
        <kbd>@</kbd><span>{{ t('引用资料') }}</span
        ><kbd>/</kbd><span>{{ t('快捷命令') }}</span>
      </div>
    </section>
  </template>
  <section v-else class="settings-card local-data-card">
    <div class="settings-card-heading">
      <div>
        <h2>{{ t('本机数据') }}</h2>
        <p>{{ t('界面偏好与对话保存在此设备；密钥由系统凭据库保管。') }}</p>
      </div>
      <ShieldCheck :size="20" />
    </div>
    <dl class="runtime-details">
      <div>
        <dt>{{ t('版本') }}</dt>
        <dd>Edge Assistant <span class="version-label">0.1.0</span></dd>
      </div>
      <div>
        <dt>{{ t('运行状态') }}</dt>
        <dd>
          <span class="runtime-status" :class="{ ready: app.health }"></span
          >{{ t(app.health ? '本地服务已连接' : '本地服务未连接') }}
        </dd>
      </div>
      <div>
        <dt>{{ t('查找资料') }}</dt>
        <dd>
          <span class="runtime-status" :class="{ ready: app.capabilities?.embedding.ready }"></span
          >{{ t(app.capabilities?.embedding.ready ? '检索模型已准备' : '检索模型尚未准备') }}
        </dd>
      </div>
      <div>
        <dt>{{ t('提取图片文字') }}</dt>
        <dd>
          <span class="runtime-status" :class="{ ready: app.capabilities?.ocr.available }"></span
          >{{ t(app.capabilities?.ocr.available ? '本地 OCR 可用' : '本地 OCR 不可用') }}
          <span v-if="app.capabilities?.ocr.engine" class="version-label">{{
            app.capabilities.ocr.engine
          }}</span>
        </dd>
      </div>
    </dl>
  </section>
</template>
