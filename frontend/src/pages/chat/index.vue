<template>
  <view class="chat-page">
    <!-- 消息列表 -->
    <scroll-view
      class="message-list"
      scroll-y
      :scroll-top="scrollTop"
      :scroll-with-animation="true"
      @scrolltoupper="onScrollToUpper"
    >
      <view class="message-list-inner">
        <view
          v-for="msg in messages"
          :key="msg.id"
          class="message-item"
          :class="msg.role === 'user' ? 'message-user' : 'message-ai'"
        >
          <!-- 用户消息 -->
          <template v-if="msg.role === 'user'">
            <view class="bubble bubble-user">
              <view v-if="msg.image_paths && msg.image_paths.length" class="bubble-images">
                <image
                  v-for="(path, i) in msg.image_paths"
                  :key="i"
                  :src="path"
                  class="bubble-image"
                  mode="aspectFill"
                  @click="previewImage(path, msg.image_paths!)"
                />
              </view>
              <text v-if="msg.content" class="bubble-text">{{ msg.content }}</text>
            </view>
          </template>

          <!-- AI 消息 -->
          <template v-else>
            <view class="bubble bubble-ai">
              <view v-if="msg.loading && !msg.thinking_message" class="bubble-loading">
                <text class="loading-dot">●</text>
                <text class="loading-dot">●</text>
                <text class="loading-dot">●</text>
              </view>
              <text v-else-if="msg.error" class="bubble-error">{{ msg.error }}</text>
              <template v-else>
                <!-- thinking 进度提示 -->
                <view v-if="msg.thinking_message" class="bubble-thinking">
                  <view class="thinking-dots">
                    <text class="thinking-dot">●</text>
                    <text class="thinking-dot">●</text>
                    <text class="thinking-dot">●</text>
                  </view>
                  <text class="thinking-text">{{ msg.thinking_message }}</text>
                </view>
                <!-- 工具结果摘要 -->
                <view v-if="msg.tool_results && msg.tool_results.length" class="bubble-tool-results">
                  <view v-for="(tr, idx) in msg.tool_results" :key="idx" class="tool-result-item">
                    <text class="tool-result-label">{{ formatToolLabel(tr.tool) }}</text>
                    <text class="tool-result-text">
                      {{ formatToolResult(tr) }}
                    </text>
                  </view>
                </view>
                <!-- 回复内容 -->
                <MarkdownRenderer
                  v-if="msg.content"
                  :content="msg.content"
                  :figure-results="msg.figure_results"
                  :message-ended="msg.message_ended"
                />
                <view v-if="standaloneFigureResults(msg).length" class="generated-figures">
                  <image
                    v-for="fig in standaloneFigureResults(msg)"
                    :key="fig.asset_id || fig.image_url"
                    :src="fig.image_url"
                    class="generated-figure-image"
                    mode="widthFix"
                    @click="previewFigure(fig.image_url, standaloneFigureResults(msg))"
                  />
                </view>
                <view v-if="msg.post_answer_status" class="bubble-post-answer-status">
                  <view class="thinking-dots">
                    <text class="thinking-dot">●</text>
                    <text class="thinking-dot">●</text>
                    <text class="thinking-dot">●</text>
                  </view>
                  <text class="post-answer-status-text">{{ msg.post_answer_status }}</text>
                </view>
                <!-- 透明自检结果 -->
                <view v-if="msg.reflexion_results && msg.reflexion_results.length" class="bubble-reflexion">
                  <view
                    v-for="(result, idx) in msg.reflexion_results"
                    :key="idx"
                    class="reflexion-item"
                  >
                    <text class="reflexion-title">{{ formatReflexionStatus(result.status) }}</text>
                    <text class="reflexion-text">{{ result.visible_message }}</text>
                    <text v-if="result.corrected_content" class="reflexion-correction">
                      {{ result.corrected_content }}
                    </text>
                  </view>
                </view>
                <!-- 反馈按钮：仅对最后一条已完成的 AI 消息显示 -->
                <FeedbackButtons
                  v-if="canShowFeedback(msg)"
                  :disabled="isLoading"
                  @send="sendFeedback"
                />
              </template>
            </view>
          </template>
        </view>
      </view>
    </scroll-view>

    <!-- 底部输入区 -->
    <view class="input-bar">
      <view class="input-icon" @click="chooseImage">
        <text class="icon-text">📷</text>
      </view>

      <view v-if="pendingImagePath" class="pending-image-wrap">
        <image :src="pendingImagePath" class="pending-image" mode="aspectFill" />
        <view class="pending-image-remove" @click="removePendingImage">
          <text>✕</text>
        </view>
      </view>

      <textarea
        v-model="inputText"
        class="input-textarea"
        placeholder="输入问题…"
        :auto-height="true"
        :max-height="120"
        confirm-type="send"
        @confirm="sendMessage"
      />

      <view
        class="send-btn"
        :class="{ 'send-btn-active': canSend }"
        @click="sendMessage"
      >
        <text class="send-btn-text">{{ isLoading ? '…' : '发送' }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onUnmounted } from 'vue'
import { clientUserId } from '../../utils/request'
import { streamChat } from '../../utils/sse'
import { chooseAndCompressImage } from '../../utils/image'
import { createSession } from '../../api/sessions'
import { uploadFile } from '../../api/files'
import type { ChatMessage } from '../../api/chat'
import MarkdownRenderer from '../../components/MarkdownRenderer.vue'
import FeedbackButtons from '../../components/FeedbackButtons.vue'

const messages = ref<ChatMessage[]>([])
const inputText = ref('')
const scrollTop = ref(0)
const sessionId = ref<string | null>(null)
const isLoading = ref(false)

const pendingImagePath = ref<string | null>(null)
const pendingAssetId = ref<string | null>(null)

// 当前 SSE 连接，用于中断
let currentAbortController: ReturnType<typeof streamChat> | null = null

const canSend = computed(() =>
  !isLoading.value && (inputText.value.trim().length > 0 || pendingAssetId.value !== null),
)

/** 判断是否为最后一条 AI 消息（用于显示反馈按钮） */
function isLastAiMessage(msgId: string): boolean {
  const aiMessages = messages.value.filter((m) => m.role === 'assistant' && !m.loading && !m.error)
  return aiMessages.length > 0 && aiMessages[aiMessages.length - 1].id === msgId
}

function canShowFeedback(msg: ChatMessage): boolean {
  return (
    isLastAiMessage(msg.id)
    && !isLoading.value
    && msg.message_completed === true
    && !msg.post_answer_status
  )
}

/** 反馈按钮点击：直接发送自然语言消息，Agent 规划层自动识别策略 */
async function sendFeedback(message: string) {
  inputText.value = message
  await sendMessage()
}

onUnmounted(() => {
  currentAbortController?.abort()
})

function scrollToBottom() {
  nextTick(() => {
    scrollTop.value = 999999
  })
}

function onScrollToUpper() {
  // 预留：后续加载更多历史消息
}

function previewImage(current: string, urls: string[]) {
  uni.previewImage({ current, urls })
}

function previewFigure(current: string, figures: Array<{ image_url: string }>) {
  uni.previewImage({ current, urls: figures.map((fig) => fig.image_url) })
}

function standaloneFigureResults(msg: ChatMessage) {
  if (!msg.figure_results || msg.figure_results.length === 0) return []
  if (msg.content.includes('```python:figure')) return []
  return msg.figure_results
}

function shouldShowPostAnswerFigureStatus(aiMsg: ChatMessage, userMsg: ChatMessage): boolean {
  const hasUploadedImage = (userMsg.asset_ids?.length || 0) > 0
  const content = aiMsg.content || ''
  return (
    hasUploadedImage
    || content.includes('辅助线')
    || content.includes('```python:figure')
  )
}

function findAssistantMessageByBackendId(messageId?: string, fallback?: ChatMessage) {
  if (!messageId) return fallback
  return messages.value.find((msg) => msg.role === 'assistant' && msg.message_id === messageId) || fallback
}

async function chooseImage() {
  try {
    const { filePath, originalPath } = await chooseAndCompressImage()
    pendingImagePath.value = originalPath  // 预览用原始路径
    pendingAssetId.value = null
    try {
      const result = await uploadFile(filePath)  // 上传压缩后的文件
      pendingAssetId.value = result.asset_id
    } catch {
      uni.showToast({ title: '图片上传失败', icon: 'none' })
      pendingImagePath.value = null
    }
  } catch (e: unknown) {
    if (e instanceof Error && !e.message.includes('cancel')) {
      uni.showToast({ title: '选择图片失败', icon: 'none' })
    }
  }
}

function removePendingImage() {
  pendingImagePath.value = null
  pendingAssetId.value = null
}

function newMessageId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
}

function formatToolLabel(tool: string): string {
  if (tool === 'process_question') return '题目识别'
  if (tool === 'extract_knowledge') return '知识点'
  if (tool === 'geometry_validator') return '几何图校验'
  return '工具结果'
}

function formatReflexionStatus(status: string): string {
  if (status === 'passed') return '自检通过'
  if (status === 'corrected') return '自检修正'
  if (status === 'unreliable') return '自检未通过'
  if (status === 'failed') return '自检未完成'
  return '自检结果'
}

/** 格式化工具结果为可读文本 */
function formatToolResult(tr: { tool: string; data: Record<string, unknown> }): string {
  if (tr.tool === 'process_question') {
    const d = tr.data
    const parts: string[] = []
    if (d.subject) parts.push(String(d.subject))
    if (d.has_figure) parts.push('含图形')
    return parts.join(' · ') || '已识别'
  }
  if (tr.tool === 'extract_knowledge') {
    const d = tr.data
    const points = d.knowledge_points
    if (Array.isArray(points) && points.length > 0) {
      return points.join('、')
    }
    return String(d.difficulty || '已提取')
  }
  if (tr.tool === 'geometry_validator') {
    const d = tr.data
    if (d.status === 'failed') {
      return `几何图校验未通过：${String(d.message || '无法生成可靠图形')}`
    }
    return String(d.message || '已校验')
  }
  if (tr.tool === 'figure_agent') {
    const d = tr.data
    return String(d.message || '辅助线处理完成')
  }
  return '完成'
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!canSend.value) return

  if (pendingImagePath.value && !pendingAssetId.value) {
    uni.showToast({ title: '图片上传中，请稍候', icon: 'none' })
    return
  }

  // 添加用户消息气泡
  const userMsg: ChatMessage = {
    id: newMessageId(),
    role: 'user',
    content: text,
    asset_ids: pendingAssetId.value ? [pendingAssetId.value] : [],
    image_paths: pendingImagePath.value ? [pendingImagePath.value] : [],
  }
  messages.value.push(userMsg)

  inputText.value = ''
  const assetId = pendingAssetId.value
  pendingImagePath.value = null
  pendingAssetId.value = null
  scrollToBottom()

  // 添加 AI loading 气泡（所有字段必须初始化，否则 Vue 无法追踪动态添加的属性）
  const aiMsgId = newMessageId()
  messages.value.push({
    id: aiMsgId,
    role: 'assistant',
    content: '',
    loading: true,
    thinking_message: '',
    tool_results: [],
    figure_results: [],
    reflexion_results: [],
    message_completed: false,
    post_answer_status: '',
  })
  isLoading.value = true
  scrollToBottom()

  // 通过索引获取响应式引用（Vue Proxy），确保赋值触发模板更新
  const aiMsg = messages.value[messages.value.length - 1]

  try {
    // 确保有会话 ID
    if (!sessionId.value) {
      const session = await createSession()
      sessionId.value = session.session_id
    }
  } catch {
    aiMsg.loading = false
    aiMsg.error = '创建会话失败，请重试'
    isLoading.value = false
    return
  }

  // 启动 SSE 流式请求
  let requestController: ReturnType<typeof streamChat> | null = null
  const finishActiveRequest = () => {
    if (currentAbortController === requestController) {
      isLoading.value = false
      currentAbortController = null
    }
  }

  requestController = streamChat(
    {
      session_id: sessionId.value,
      message: text || '（图片）',
      asset_ids: assetId ? [assetId] : [],
      client_user_id: clientUserId,
    },
    {
      onMessageStart(data) {
        // 后端返回的 session_id 以后端为准
        if (data.session_id && data.session_id !== 'local-session') {
          sessionId.value = data.session_id
        }
        aiMsg.loading = false
      },
      onThinking(data) {
        aiMsg.loading = false
        aiMsg.thinking_message = data.message
        scrollToBottom()
      },
      onToolResult(data) {
        const targetMsg = findAssistantMessageByBackendId(
          typeof data.data.message_id === 'string' ? data.data.message_id : undefined,
          aiMsg,
        )
        if (!targetMsg) return
        targetMsg.tool_results ||= []
        targetMsg.tool_results.push(data)
        if (data.tool === 'figure_agent') {
          targetMsg.post_answer_status = ''
        }
        scrollToBottom()
      },
      onDelta(data) {
        aiMsg.thinking_message = ''
        aiMsg.content += data.text
        scrollToBottom()
      },
      onAnswerEnd(data) {
        if (data.session_id && data.session_id !== 'local-session') {
          sessionId.value = data.session_id
        }
        aiMsg.thinking_message = ''
        if (shouldShowPostAnswerFigureStatus(aiMsg, userMsg)) {
          aiMsg.post_answer_status = '答案已生成，正在处理辅助线图…'
        }
        finishActiveRequest()
        scrollToBottom()
      },
      onFigureResult(data) {
        const targetMsg = findAssistantMessageByBackendId(data.message_id, aiMsg)
        if (!targetMsg) return
        targetMsg.figure_results ||= []
        targetMsg.figure_results.push(data)
        targetMsg.post_answer_status = ''
        scrollToBottom()
      },
      onReflexionResult(data) {
        const targetMsg = findAssistantMessageByBackendId(data.message_id, aiMsg)
        if (!targetMsg) return
        targetMsg.reflexion_results ||= []
        targetMsg.reflexion_results.push(data)
        scrollToBottom()
      },
      onMessageEnd(data) {
        if (data.message_id) aiMsg.message_id = data.message_id
        aiMsg.thinking_message = ''
        aiMsg.post_answer_status = ''
        aiMsg.message_completed = true
        finishActiveRequest()
        scrollToBottom()
        // 5 秒后标记 message_ended，触发 MarkdownRenderer 将未收到 figure_result 的块标为 failed
        setTimeout(() => {
          aiMsg.message_ended = true
        }, 5000)
      },
      onError(data) {
        aiMsg.loading = false
        aiMsg.thinking_message = ''
        aiMsg.post_answer_status = ''
        aiMsg.message_completed = true
        aiMsg.error = data.message || 'AI 回复出错'
        finishActiveRequest()
      },
      onNetworkError(err) {
        aiMsg.loading = false
        aiMsg.thinking_message = ''
        aiMsg.post_answer_status = ''
        aiMsg.message_completed = true
        aiMsg.error = err.message || '网络连接失败，请重试'
        finishActiveRequest()
      },
    },
  )
  currentAbortController = requestController
}
</script>

<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background-color: #f5f5f5;
}

.message-list {
  flex: 1;
  overflow: hidden;
}

.message-list-inner {
  padding: 12px 12px 8px;
}

.message-item {
  display: flex;
  margin-bottom: 12px;
}

.message-user {
  justify-content: flex-end;
}

.message-ai {
  justify-content: flex-start;
}

.bubble {
  max-width: 72%;
  padding: 10px 14px;
  border-radius: 16px;
  word-break: break-word;
}

.bubble-user {
  background-color: #2B7FFF;
  border-bottom-right-radius: 4px;
}

.bubble-ai {
  background-color: #FFFFFF;
  border-bottom-left-radius: 4px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.bubble-text {
  font-size: 15px;
  line-height: 1.5;
  color: inherit;
}

.bubble-user .bubble-text {
  color: #FFFFFF;
}

.bubble-ai .bubble-text {
  color: #1a1a1a;
}

.bubble-error {
  font-size: 14px;
  color: #ff4d4f;
}

.bubble-thinking {
  padding: 4px 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.thinking-dots {
  display: flex;
  gap: 3px;
  align-items: center;
  flex-shrink: 0;
}

.thinking-dot {
  font-size: 6px;
  color: #2B7FFF;
  animation: thinking-pulse 1.4s ease-in-out infinite;
}

.thinking-dot:nth-child(2) { animation-delay: 0.2s; }
.thinking-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes thinking-pulse {
  0%, 80%, 100% { opacity: 0.2; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1.2); }
}

.thinking-text {
  font-size: 13px;
  color: #999;
  font-style: italic;
}

.bubble-tool-results {
  margin-bottom: 8px;
  padding: 8px 10px;
  background-color: #f8f9fa;
  border-radius: 8px;
}

.tool-result-item {
  margin-bottom: 4px;
}

.tool-result-item:last-child {
  margin-bottom: 0;
}

.tool-result-label {
  font-size: 12px;
  color: #2B7FFF;
  font-weight: 600;
  margin-right: 6px;
}

.tool-result-text {
  font-size: 13px;
  color: #555;
}

.bubble-reflexion {
  margin-top: 6px;
  padding: 6px 8px;
  background-color: #fff7e6;
  border-radius: 4px;
}

.bubble-post-answer-status {
  margin-top: 8px;
  padding: 7px 9px;
  display: flex;
  align-items: center;
  gap: 8px;
  background-color: #f6f9ff;
  border: 1px solid #dbe8ff;
  border-radius: 6px;
}

.post-answer-status-text {
  font-size: 12px;
  color: #2B5CAD;
}

.reflexion-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.reflexion-title {
  font-size: 12px;
  color: #ad6800;
  font-weight: 600;
}

.reflexion-text {
  font-size: 12px;
  color: #d48806;
}

.reflexion-correction {
  font-size: 13px;
  line-height: 1.5;
  color: #5f3b00;
  white-space: pre-wrap;
}

.bubble-loading {
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 2px 0;
}

.loading-dot {
  font-size: 8px;
  color: #999;
  animation: blink 1.2s infinite;
}

.loading-dot:nth-child(2) { animation-delay: 0.2s; }
.loading-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes blink {
  0%, 80%, 100% { opacity: 0.2; }
  40% { opacity: 1; }
}

.bubble-images {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}

.bubble-image {
  width: 120px;
  height: 120px;
  border-radius: 8px;
}

.generated-figures {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.generated-figure-image {
  width: 100%;
  max-width: 520px;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  background-color: #fff;
}

.input-bar {
  display: flex;
  align-items: flex-end;
  padding: 8px 12px;
  background-color: #FFFFFF;
  border-top: 1px solid #f0f0f0;
  gap: 8px;
}

.input-icon {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.icon-text {
  font-size: 22px;
}

.pending-image-wrap {
  position: relative;
  flex-shrink: 0;
}

.pending-image {
  width: 48px;
  height: 48px;
  border-radius: 6px;
}

.pending-image-remove {
  position: absolute;
  top: -6px;
  right: -6px;
  width: 16px;
  height: 16px;
  background-color: rgba(0, 0, 0, 0.5);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  color: #fff;
}

.input-textarea {
  flex: 1;
  min-height: 36px;
  max-height: 120px;
  padding: 8px 10px;
  background-color: #f5f5f5;
  border-radius: 18px;
  font-size: 15px;
  line-height: 1.4;
}

.send-btn {
  flex-shrink: 0;
  padding: 8px 14px;
  border-radius: 18px;
  background-color: #d0d0d0;
}

.send-btn-active {
  background-color: #2B7FFF;
}

.send-btn-text {
  font-size: 14px;
  color: #FFFFFF;
}
</style>
