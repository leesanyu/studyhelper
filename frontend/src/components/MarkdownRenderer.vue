<template>
  <view class="markdown-body">
    <!-- #ifdef H5 -->
    <div ref="containerRef" class="markdown-html" v-html="renderedHtml" />
    <!-- #endif -->
    <!-- #ifndef H5 -->
    <text class="markdown-plain">{{ content }}</text>
    <!-- #endif -->
  </view>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted } from 'vue'
import { renderMarkdown, FIGURE_BLOCK_MARKER, CODE_BLOCK_MARKER } from '../utils/markdown'

const props = defineProps<{
  content: string
  /** figure_result 列表（按出现顺序），message_end 后由聊天页传入 */
  figureResults?: Array<{ asset_id: string; image_url: string }>
  /** true = message_end 已到达，超时后未匹配的 figure 块标记为 failed */
  messageEnded?: boolean
}>()

const renderedHtml = ref('')
const containerRef = ref<HTMLElement | null>(null)

// 记录每个 figure 块的 DOM wrapper，按出现顺序存储
const figureWrappers: HTMLElement[] = []

function updateHtml() {
  figureWrappers.length = 0
  renderedHtml.value = renderMarkdown(props.content)
  nextTick(() => postProcessDom())
}

function postProcessDom() {
  const container = containerRef.value
  if (!container) return

  // 处理 python:figure 占位块（流式期间遇到完整标记就立即渲染为 waiting）
  container.querySelectorAll(`[${FIGURE_BLOCK_MARKER}]`).forEach((el) => {
    const code = decodeURIComponent(el.getAttribute(FIGURE_BLOCK_MARKER) || '')
    const wrapper = document.createElement('div')
    wrapper.className = 'figure-block-wrapper figure-waiting'
    wrapper.dataset.figureIndex = String(figureWrappers.length)
    wrapper.innerHTML = buildFigureWaitingHtml(code)
    el.replaceWith(wrapper)
    figureWrappers.push(wrapper)
  })

  // 处理普通代码块占位
  container.querySelectorAll(`[${CODE_BLOCK_MARKER}-code]`).forEach((el) => {
    const lang = decodeURIComponent(el.getAttribute(`${CODE_BLOCK_MARKER}-lang`) || '')
    const code = decodeURIComponent(el.getAttribute(`${CODE_BLOCK_MARKER}-code`) || '')
    const wrapper = document.createElement('div')
    wrapper.className = 'code-block-wrapper'
    wrapper.innerHTML = buildCodeBlockHtml(lang, code)
    el.replaceWith(wrapper)
  })

  // 应用已有的 figureResults
  applyFigureResults()
}

function applyFigureResults() {
  const results = props.figureResults || []
  figureWrappers.forEach((wrapper, idx) => {
    const result = results[idx]
    if (result) {
      // 渲染图片
      wrapper.className = 'figure-block-wrapper figure-success'
      wrapper.innerHTML = `<img src="${result.image_url}" class="figure-image" alt="生成图形" />`
    } else if (props.messageEnded) {
      // message_end 已到达但没有对应 result → failed
      wrapper.className = 'figure-block-wrapper figure-failed'
      wrapper.innerHTML = '<div class="figure-block-failed">图形生成失败</div>'
    }
    // 否则保持 waiting 状态
  })
}

function buildFigureWaitingHtml(code: string): string {
  return `<div class="figure-block-waiting">
    <span class="figure-waiting-text">图形生成中…</span>
    <pre class="figure-code">${escapeHtml(code)}</pre>
  </div>`
}

function buildCodeBlockHtml(lang: string, code: string): string {
  const escapedCode = escapeHtml(code)
  const jsonCode = JSON.stringify(code)
  return `
    <div class="code-block-header">
      <span class="code-lang">${escapeHtml(lang) || 'code'}</span>
      <button class="code-copy-btn" onclick="navigator.clipboard?.writeText(${jsonCode})">复制</button>
    </div>
    <pre class="code-content"><code>${escapedCode}</code></pre>
  `
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

watch(() => props.content, updateHtml)
// figureResults 或 messageEnded 变化时重新应用状态
watch([() => props.figureResults, () => props.messageEnded], () => {
  nextTick(() => applyFigureResults())
}, { deep: true })
onMounted(updateHtml)
</script>

<style scoped>
.markdown-body { width: 100%; }
.markdown-plain { font-size: 15px; line-height: 1.6; color: #1a1a1a; }
</style>

<style>
.markdown-html {
  font-size: 15px;
  line-height: 1.6;
  color: #1a1a1a;
  word-break: break-word;
}
.markdown-html p { margin: 0 0 8px; }
.markdown-html p:last-child { margin-bottom: 0; }
.markdown-html h1, .markdown-html h2, .markdown-html h3 { font-weight: 600; margin: 12px 0 6px; }
.markdown-html h1 { font-size: 18px; }
.markdown-html h2 { font-size: 16px; }
.markdown-html h3 { font-size: 15px; }
.markdown-html ul, .markdown-html ol { padding-left: 20px; margin: 6px 0; }
.markdown-html li { margin: 2px 0; }
.markdown-html code {
  background-color: #f0f0f0;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 13px;
  font-family: 'Courier New', monospace;
}
.markdown-html hr { border: none; border-top: 1px solid #e0e0e0; margin: 10px 0; }

/* 代码块 */
.code-block-wrapper { background-color: #1e1e1e; border-radius: 8px; overflow: hidden; margin: 8px 0; }
.code-block-header { display: flex; justify-content: space-between; align-items: center; padding: 6px 12px; background-color: #2d2d2d; }
.code-lang { font-size: 12px; color: #999; font-family: monospace; }
.code-copy-btn { font-size: 12px; color: #aaa; background: none; border: none; cursor: pointer; padding: 2px 6px; }
.code-content { margin: 0; padding: 12px; overflow-x: auto; font-size: 13px; line-height: 1.5; color: #d4d4d4; font-family: 'Courier New', monospace; }

/* python:figure 块 */
.figure-block-wrapper { margin: 8px 0; border-radius: 8px; overflow: hidden; }
.figure-block-waiting { background-color: #f8f9fa; border: 1px dashed #d0d0d0; border-radius: 8px; padding: 16px; text-align: center; }
.figure-waiting-text { font-size: 13px; color: #888; display: block; margin-bottom: 8px; }
.figure-code { font-size: 11px; color: #bbb; text-align: left; overflow: hidden; max-height: 48px; margin: 0; white-space: pre-wrap; }
.figure-image { max-width: 100%; border-radius: 8px; display: block; cursor: pointer; }
.figure-block-failed { background-color: #fff2f0; border: 1px solid #ffccc7; border-radius: 8px; padding: 12px; text-align: center; font-size: 13px; color: #ff4d4f; }

/* KaTeX */
.markdown-html .katex-display { overflow-x: auto; margin: 8px 0; }
</style>
