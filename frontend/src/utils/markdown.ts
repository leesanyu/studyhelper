/**
 * Markdown 渲染工具：markdown-it + KaTeX（通过 markdown-it-texmath 插件）
 *
 * 自定义 fence renderer：
 *   - ```python:figure ... ``` → 输出特殊标记，供 MarkdownRenderer.vue 替换为 FigureBlock 组件
 *   - 其他代码块 → 输出带语言标签的 <pre> 标记，供 MarkdownRenderer.vue 替换为 CodeBlock 组件
 */

import MarkdownIt from 'markdown-it'
import texmath from 'markdown-it-texmath'
import katex from 'katex'

// 代码块占位标记（用于 Vue 组件替换）
export const FIGURE_BLOCK_MARKER = 'data-figure-block'
export const CODE_BLOCK_MARKER = 'data-code-block'

const md = new MarkdownIt({
  html: false,       // 禁止原始 HTML，防止 XSS
  linkify: true,
  typographer: false,
})

// 注册 KaTeX 插件，启用 $...$ 行内和 $$...$$ 块级公式
md.use(texmath, {
  engine: katex,
  delimiters: 'dollars',
  katexOptions: { throwOnError: false },
})

// 自定义 fence renderer：区分 python:figure 和普通代码块
md.renderer.rules.fence = (tokens, idx) => {
  const token = tokens[idx]
  const lang = (token.info || '').trim()
  const code = token.content

  if (lang === 'python:figure') {
    // 输出占位 div，MarkdownRenderer 将其替换为 FigureBlock 组件
    const encoded = encodeURIComponent(code)
    return `<div ${FIGURE_BLOCK_MARKER}="${encoded}"></div>`
  }

  // 普通代码块：输出占位 div，MarkdownRenderer 将其替换为 CodeBlock 组件
  const encodedCode = encodeURIComponent(code)
  const encodedLang = encodeURIComponent(lang)
  return `<div ${CODE_BLOCK_MARKER}-lang="${encodedLang}" ${CODE_BLOCK_MARKER}-code="${encodedCode}"></div>`
}

/**
 * 将 Markdown 文本渲染为 HTML 字符串。
 * 流式场景下，每次 delta 累积后调用此函数重新渲染。
 */
export function renderMarkdown(text: string): string {
  return md.render(text)
}
