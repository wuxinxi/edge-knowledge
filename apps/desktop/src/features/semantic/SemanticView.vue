<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ImagePlus, LoaderCircle, Search, Shapes, Upload, X, Download } from '@lucide/vue'
import { useAppStore } from '../../app/store'
import { useI18n } from '../../shared/i18n'
import { api } from '../../shared/api/client'
import type {
  Document,
  EmbeddingBudget,
  MediaKind,
  OrganizationResult,
  SemanticResult,
} from '../../shared/types/api'
import ImagePreview from '../../shared/components/ImagePreview.vue'
import MediaPreview from '../../shared/components/MediaPreview.vue'
import './semantic.css'
const app = useAppStore(),
  { t } = useI18n()
const tab = ref<'search' | 'ingest' | 'organize'>('search'),
  text = ref(''),
  name = ref(''),
  files = ref<File[]>([])
const input = ref<HTMLInputElement>(),
  previews = ref<string[]>([]),
  dimension = ref(768),
  topK = ref(10)
const task = ref<'search' | 'code' | 'qa' | 'fact'>('search'),
  kind = ref<MediaKind | ''>('')
const archived = ref<Document[]>([]),
  documents = ref<Document[]>([]),
  scope = ref<string[]>([]),
  busy = ref(false),
  error = ref(''),
  notice = ref('')
const searchResult = ref<SemanticResult>(),
  organization = ref<OrganizationResult>(),
  budget = ref<EmbeddingBudget>()
const organizeTask = ref<'classification' | 'clustering' | 'similarity'>('classification'),
  labels = ref('技术文档, 生活资料, 工作票据'),
  clusters = ref(3),
  threshold = ref(0.8),
  classificationThreshold = ref(0.2)
const valid = computed(() => Boolean(text.value.trim() || files.value.length))
let controller: AbortController | undefined,
  loadGeneration = 0
function clearFiles() {
  previews.value.forEach((url) => {
    if (url) URL.revokeObjectURL(url)
  })
  previews.value = []
  files.value = []
}
function choose(event: Event) {
  const target = event.target as HTMLInputElement
  const chosen = Array.from(target.files ?? [])
  target.value = ''
  error.value = ''
  if (files.value.length + chosen.length > 12) {
    error.value = t('最多联合 12 份素材。')
    return
  }
  for (const file of chosen) {
    const media = /\.(wav|mp3|m4a|aac|flac|ogg|mp4|mov|mkv|webm)$/i.test(file.name)
    if (file.size > (media ? 200 : 20) * 1024 * 1024) {
      error.value = t('文档和图片上限 20 MB，音视频上限 200 MB。')
      continue
    }
    files.value.push(file)
    previews.value.push(file.type.startsWith('image/') ? URL.createObjectURL(file) : '')
  }
}
function removeFile(index: number) {
  if (previews.value[index]) URL.revokeObjectURL(previews.value[index]!)
  files.value.splice(index, 1)
  previews.value.splice(index, 1)
}
async function load() {
  const generation = ++loadGeneration,
    library = app.activeLibrary
  try {
    const [result, trash] = await Promise.all([api.documents(library), api.archived(library)])
    if (generation === loadGeneration) {
      documents.value = result
      archived.value = trash
    }
  } catch (cause) {
    if (generation === loadGeneration)
      error.value = cause instanceof Error ? cause.message : String(cause)
  }
}
async function run() {
  controller?.abort()
  const current = (controller = new AbortController()),
    library = app.activeLibrary
  busy.value = true
  error.value = ''
  notice.value = ''
  searchResult.value = undefined
  organization.value = undefined
  budget.value = undefined
  try {
    if (tab.value === 'organize') {
      const result = await api.organize(
        {
          library_id: library,
          document_ids: scope.value,
          task: organizeTask.value,
          dimension: dimension.value,
          labels: labels.value
            .split(/[,，\n]/)
            .map((label) => label.trim())
            .filter(Boolean),
          clusters: clusters.value,
          threshold:
            organizeTask.value === 'classification'
              ? classificationThreshold.value
              : threshold.value,
        },
        current.signal,
      )
      if (!current.signal.aborted) organization.value = result
    } else if (tab.value === 'ingest') {
      const result = await api.semanticIngest(
        {
          library_id: library,
          text: text.value,
          name:
            name.value.trim() ||
            files.value
              .map((file) => file.name)
              .join(' + ')
              .slice(0, 255) ||
            t('联合素材'),
        },
        files.value,
        current.signal,
      )
      if (!current.signal.aborted) {
        budget.value = result.budget
        notice.value = result.duplicate ? t('已存在，跳过重复导入') : t('联合素材已入库')
        await app.refreshLibraries()
        await load()
      }
    } else {
      const result = await api.semanticSearch(
        {
          library_id: library,
          text: text.value,
          dimension: dimension.value,
          top_k: topK.value,
          task: task.value,
          document_ids: scope.value,
          kinds: kind.value ? [kind.value] : [],
        },
        files.value,
        current.signal,
      )
      if (!current.signal.aborted) {
        searchResult.value = result
        budget.value = result.budget
      }
    }
  } catch (cause) {
    if (!current.signal.aborted)
      error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (!current.signal.aborted) busy.value = false
  }
}
async function previewBudget() {
  controller?.abort()
  const current = (controller = new AbortController())
  busy.value = true
  error.value = ''
  budget.value = undefined
  try {
    const result = await api.semanticBudget(
      {
        library_id: app.activeLibrary,
        text: text.value,
        task: tab.value === 'ingest' ? 'document' : task.value,
      },
      files.value,
      current.signal,
    )
    if (!current.signal.aborted) budget.value = result
  } catch (cause) {
    if (!current.signal.aborted)
      error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (!current.signal.aborted) busy.value = false
  }
}
async function archiveDuplicate(id: string) {
  if (busy.value) return
  const library = app.activeLibrary,
    current = (controller = new AbortController())
  busy.value = true
  error.value = ''
  try {
    await api.archiveDocument(library, id, current.signal)
    if (current.signal.aborted || library !== app.activeLibrary) return
    scope.value = scope.value.filter((value) => value !== id)
    if (organization.value)
      organization.value.pairs = organization.value.pairs?.filter(
        (pair) => pair.left !== id && pair.right !== id,
      )
    await app.refreshLibraries()
    await load()
    if (!current.signal.aborted) notice.value = t('资料已移入暂存区，可随时恢复。')
  } catch (cause) {
    if (!current.signal.aborted)
      error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (!current.signal.aborted) busy.value = false
  }
}
async function restore(id: string) {
  if (busy.value) return
  const library = app.activeLibrary,
    current = (controller = new AbortController())
  busy.value = true
  error.value = ''
  try {
    await api.restoreDocument(library, id, current.signal)
    if (current.signal.aborted || library !== app.activeLibrary) return
    organization.value = undefined
    await app.refreshLibraries()
    await load()
    if (!current.signal.aborted) notice.value = t('资料已恢复，重新整理可更新结果。')
  } catch (cause) {
    if (!current.signal.aborted)
      error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (!current.signal.aborted) busy.value = false
  }
}
function cancel() {
  controller?.abort()
  busy.value = false
  notice.value = t('已停止等待；正在处理的本地任务会安全结束。')
}
function exportResults() {
  const data = organization.value ?? searchResult.value
  if (!data) return
  const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }),
    ),
    link = document.createElement('a')
  link.href = url
  link.download = 'edge-results.json'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function fileName(id: string) {
  return organization.value?.documents.find((doc) => doc.id === id)?.filename ?? id
}
function time(value: number) {
  return `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`
}
watch(
  () => app.activeLibrary,
  () => {
    cancel()
    scope.value = []
    searchResult.value = undefined
    organization.value = undefined
    budget.value = undefined
    notice.value = ''
    void load()
  },
)
watch(tab, () => {
  cancel()
  error.value = ''
  notice.value = ''
  searchResult.value = undefined
  organization.value = undefined
  budget.value = undefined
})
watch(
  () => [
    text.value,
    files.value.map((file) => `${file.name}:${file.size}`).join('|'),
    task.value,
    kind.value,
    topK.value,
  ],
  () => {
    budget.value = undefined
    notice.value = ''
    searchResult.value = undefined
  },
)
watch(
  () => [
    organizeTask.value,
    dimension.value,
    labels.value,
    clusters.value,
    classificationThreshold.value,
    threshold.value,
    scope.value.join(','),
  ],
  () => {
    organization.value = undefined
    searchResult.value = undefined
  },
)
onMounted(load)
onBeforeUnmount(() => {
  controller?.abort()
  loadGeneration++
  clearFiles()
})
</script>
<template>
  <section class="standard-page semantic-page">
    <header class="page-header">
      <div>
        <h1>{{ t('多模态工作台') }}</h1>
        <p class="page-subtitle">{{ t('连接文字、图像与音视频，让资料更有条理') }}</p>
      </div>
      <button
        v-if="organization || searchResult"
        class="button secondary small"
        @click="exportResults"
      >
        <Download :size="15" />{{ t('导出结果') }}
      </button>
    </header>
    <div class="page-content semantic-content">
      <nav class="semantic-tabs" :aria-label="t('工作台功能')">
        <button
          v-for="option in [
            { id: 'search', label: '跨模态检索', icon: Search },
            { id: 'ingest', label: '联合素材入库', icon: Upload },
            { id: 'organize', label: '资料整理', icon: Shapes },
          ] as const"
          :key="option.id"
          :aria-pressed="tab === option.id"
          :class="{ active: tab === option.id }"
          @click="tab = option.id"
        >
          <component :is="option.icon" :size="16" />{{ t(option.label) }}
        </button>
      </nav>
      <form class="semantic-form" @submit.prevent="run">
        <fieldset class="semantic-fields" :disabled="busy">
          <template v-if="tab !== 'organize'">
            <h2>{{ t(tab === 'search' ? '用文字、图片或媒体查找资料' : '把相关素材联合编码') }}</h2>
            <p class="semantic-description">
              {{
                t(
                  tab === 'search'
                    ? '可单独使用图片，也可以组合文字、多张图片与一段音视频。所有编码和检索均在本机进行。'
                    : '多张图片与说明文字共同生成一个向量；长音视频按时间分段，每段与附加文字和图片联合编码。',
                )
              }}
            </p>
            <label v-if="tab === 'ingest'" class="semantic-field"
              >{{ t('素材名称')
              }}<input
                v-model="name"
                :aria-label="t('素材名称')"
                maxlength="255"
                :placeholder="t('例如：产品设计资料')"
            /></label>
            <textarea
              v-model="text"
              :aria-label="t('补充文字')"
              :placeholder="t('输入查询或素材说明，也可以只选择文件…')"
              rows="3"
              maxlength="32000"
            ></textarea>
            <div class="semantic-files">
              <div v-for="(file, index) in files" :key="index" class="semantic-file">
                <img v-if="previews[index]" :src="previews[index]" :alt="file.name" /><span>{{
                  file.name
                }}</span
                ><button
                  type="button"
                  class="icon-button"
                  :aria-label="`${t('移除素材')} ${file.name}`"
                  @click="removeFile(index)"
                >
                  <X :size="14" />
                </button>
              </div>
            </div>
            <button
              type="button"
              class="button secondary small"
              :disabled="busy"
              @click="input?.click()"
            >
              <ImagePlus :size="16" />{{ t('添加图片或媒体') }}</button
            ><input
              ref="input"
              type="file"
              class="hidden"
              multiple
              accept=".txt,.md,.pdf,.docx,.png,.jpg,.jpeg,.webp,.wav,.mp3,.m4a,.aac,.flac,.ogg,.mp4,.mov,.mkv,.webm"
              @change="choose"
            />
            <p class="semantic-footnote">
              {{
                t(
                  '最多 12 份素材，文档和图片 20 MB，音视频 200 MB / 60 分钟。音视频原件保存在本机。',
                )
              }}
            </p>
          </template>
          <template v-else>
            <h2>{{ t('按语义整理资料') }}</h2>
            <p class="semantic-description">
              {{
                t(
                  '分类使用自定义标签；聚类按语义分组；查重列出相似候选，保留所有原件。一次最多整理 200 份资料。',
                )
              }}
            </p>
            <label class="semantic-field"
              >{{ t('整理任务')
              }}<select v-model="organizeTask" :aria-label="t('整理任务')">
                <option value="classification">{{ t('自动分类') }}</option>
                <option value="clustering">{{ t('语义聚类') }}</option>
                <option value="similarity">{{ t('相似查重') }}</option>
              </select></label
            >
            <label v-if="organizeTask === 'classification'" class="semantic-field"
              >{{ t('分类标签')
              }}<textarea
                v-model="labels"
                :aria-label="t('分类标签')"
                rows="2"
                :placeholder="t('用逗号或换行分隔标签')"
              />
            </label>
            <label v-if="organizeTask === 'clustering'" class="semantic-field"
              >{{ t('期望分组数')
              }}<input
                v-model.number="clusters"
                :aria-label="t('期望分组数')"
                type="number"
                min="1"
                max="20"
                required
            /></label>
            <label v-if="organizeTask === 'similarity'" class="semantic-field"
              >{{ t('最低相似度')
              }}<input
                v-model.number="threshold"
                :aria-label="t('最低相似度')"
                type="number"
                min="-1"
                max="1"
                step="0.01"
                required
            /></label>
          </template>
          <label
            v-if="tab === 'organize' && organizeTask === 'classification'"
            class="semantic-field"
            >{{ t('分类最低相似度')
            }}<input
              v-model.number="classificationThreshold"
              :aria-label="t('分类最低相似度')"
              type="number"
              min="-1"
              max="1"
              step="0.01"
              required
          /></label>
          <div v-if="tab !== 'ingest'" class="semantic-options">
            <label class="semantic-field"
              >{{ t('向量维度')
              }}<select v-model.number="dimension" :aria-label="t('向量维度')">
                <option v-for="dim in [768, 512, 256, 128]" :key="dim" :value="dim">
                  {{ dim }}d
                </option>
              </select></label
            >
            <template v-if="tab === 'search'"
              ><label class="semantic-field"
                >{{ t('结果类型')
                }}<select v-model="kind" :aria-label="t('结果类型')">
                  <option value="">{{ t('全部资料') }}</option>
                  <option value="image">{{ t('图片') }}</option>
                  <option value="document">{{ t('文档') }}</option>
                  <option value="audio">{{ t('音频') }}</option>
                  <option value="video">{{ t('视频') }}</option>
                  <option value="bundle">{{ t('联合素材') }}</option>
                </select></label
              ><label class="semantic-field"
                >{{ t('检索任务')
                }}<select v-model="task" :aria-label="t('检索任务')">
                  <option value="search">{{ t('通用检索') }}</option>
                  <option value="code">{{ t('代码检索') }}</option>
                  <option value="qa">{{ t('问题检索') }}</option>
                  <option value="fact">{{ t('事实证据检索') }}</option>
                </select></label
              ><label class="semantic-field"
                >{{ t('结果数量')
                }}<input
                  v-model.number="topK"
                  :aria-label="t('结果数量')"
                  type="number"
                  min="1"
                  max="50"
                  required /></label
            ></template>
          </div>
          <details v-if="tab !== 'ingest'" class="semantic-scope">
            <summary>
              {{ t('选择资料范围') }} ·
              {{ scope.length ? t('已限定资料') : t('当前知识库全部资料') }}
            </summary>
            <div class="semantic-scope-list">
              <label v-for="doc in documents" :key="doc.id"
                ><input v-model="scope" type="checkbox" :value="doc.id" /><span>{{
                  doc.filename
                }}</span></label
              >
              <p v-if="!documents.length">{{ t('请先导入资料。') }}</p>
            </div>
          </details>
        </fieldset>
        <div class="semantic-run">
          <span>{{ t('本地处理 · 不调用云端模型') }}</span
          ><button
            v-if="tab !== 'organize' && !busy"
            type="button"
            class="button secondary"
            :disabled="!valid || !app.health"
            @click="previewBudget"
          >
            {{ t('检查上下文预算') }}</button
          ><button v-if="busy" type="button" class="button secondary" @click="cancel">
            {{ t('停止等待') }}</button
          ><button
            v-else
            class="button primary"
            :disabled="!app.health || (tab === 'organize' ? !documents.length : !valid)"
          >
            <Search v-if="tab === 'search'" :size="16" /><Upload
              v-else-if="tab === 'ingest'"
              :size="16"
            /><Shapes v-else :size="16" />{{
              t(tab === 'search' ? '开始检索' : tab === 'ingest' ? '联合入库' : '开始整理')
            }}
          </button>
        </div>
      </form>
      <p v-if="busy" class="semantic-status" role="status">
        <LoaderCircle :size="18" class="spin" />{{
          t('正在本地编码与处理，首次加载模型需要一些时间…')
        }}
      </p>
      <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
      <p v-if="notice" class="semantic-status" role="status">{{ notice }}</p>
      <div v-if="budget" class="semantic-budget" :class="{ overflow: budget.fits === false }">
        <div>
          <strong>{{ t('上下文预算') }}</strong
          ><span
            >{{ budget.max_tokens }} / {{ budget.limit }} tokens · {{ budget.segments }}
            {{ t('个片段') }}</span
          >
        </div>
        <p v-if="budget.fits === false" class="semantic-footnote">
          {{ t('输入超过预算，请减少文字或图片。') }}
        </p>
        <meter :value="budget.max_tokens" :max="budget.limit"></meter
        ><small
          >{{ t('显示单段最大预算，包含文字、视觉、音频与格式预留；实际输入长度在推理前再次校验。')
          }}<template v-if="searchResult?.aggregation === 'mean_of_segments'">{{
            t('长查询分段编码后取归一化均值；不会把超长素材伪装成单段联合输入。')
          }}</template></small
        >
      </div>
      <section v-if="searchResult" class="semantic-results">
        <h2>{{ t('检索结果') }} · {{ searchResult.sources.length }}</h2>
        <p v-if="!searchResult.sources.length" class="semantic-description">
          {{ t('没有符合当前资料范围的结果。') }}
        </p>
        <article
          v-for="source in searchResult.sources"
          :key="`${source.document_id}:${source.index}`"
          class="semantic-result"
        >
          <div class="semantic-result-heading">
            <strong>{{ source.filename }}</strong
            ><span>{{ source.score.toFixed(4) }}</span>
          </div>
          <small
            >{{ source.section
            }}<template v-if="source.end">
              · {{ time(source.start ?? 0) }}–{{ time(source.end) }}</template
            ></small
          ><ImagePreview
            v-if="source.kind === 'image'"
            :library="app.activeLibrary"
            :document="source.document_id"
            :filename="source.filename"
          /><MediaPreview
            v-if="['audio', 'video', 'bundle'].includes(source.kind ?? '')"
            :library="app.activeLibrary"
            :document="source.document_id"
            :start="source.start"
          />
          <p v-if="source.text">{{ source.text }}</p>
          <p v-else class="semantic-footnote">
            {{ t('此结果来自媒体语义向量；可播放或查看原件，不代表文字转录。') }}
          </p>
        </article>
      </section>
      <section v-if="organization" class="semantic-results">
        <h2>{{ t('整理结果') }}</h2>
        <div
          v-for="row in organization.assignments ?? []"
          :key="row.document_id"
          class="organization-row"
        >
          <strong>{{ fileName(row.document_id) }}</strong
          ><span class="organization-label">{{ row.label }}</span
          ><small>{{ row.scores[0]?.score.toFixed(4) }}</small>
        </div>
        <article
          v-for="(group, index) in organization.groups ?? []"
          :key="index"
          class="semantic-result"
        >
          <strong>{{ t('分组') }} {{ index + 1 }} · {{ group.length }}</strong>
          <ul>
            <li v-for="id in group" :key="id">{{ fileName(id) }}</li>
          </ul>
        </article>
        <article
          v-for="pair in organization.pairs ?? []"
          :key="`${pair.left}:${pair.right}`"
          class="organization-pair"
        >
          <span>{{ fileName(pair.left) }}<br />{{ fileName(pair.right) }}</span>
          <div class="pair-actions">
            <strong
              >{{ pair.score.toFixed(4)
              }}<small>{{ t(pair.exact ? '索引内容相同' : '语义相似') }}</small></strong
            ><button class="text-button" :disabled="busy" @click="archiveDuplicate(pair.left)">
              {{ t('暂存第一份') }}</button
            ><button class="text-button" :disabled="busy" @click="archiveDuplicate(pair.right)">
              {{ t('暂存第二份') }}
            </button>
          </div>
        </article>
        <p v-if="organization.pairs?.length === 0" class="semantic-description">
          {{ t('当前阈值下没有相似候选。') }}
        </p>
        <p class="semantic-footnote">
          {{ t('分数是相似度，不是概率。分类和聚类结果供整理参考；查重不会自动删除文件。') }}
        </p>
      </section>
      <section v-if="tab === 'organize' && archived.length" class="semantic-results">
        <h2>{{ t('重复资料暂存区') }} · {{ archived.length }}</h2>
        <p class="semantic-description">
          {{ t('暂存资料不参与检索，原件与索引快照仍在本机，可随时恢复。') }}
        </p>
        <div v-for="doc in archived" :key="doc.id" class="organization-row">
          <strong>{{ doc.filename }}</strong
          ><button class="button secondary small" :disabled="busy" @click="restore(doc.id)">
            {{ t('恢复资料') }}
          </button>
        </div>
      </section>
    </div>
  </section>
</template>
