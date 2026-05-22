/**
 * SSE 流式读取模块：fetch POST + ReadableStream
 *
 * 解析后端 SSE 事件格式：
 *   data: {"event": "message_start", "data": {"session_id": "..."}}\n\n
 *   data: {"event": "thinking",    "data": {"type": "...", "message": "..."}}\n\n
 *   data: {"event": "tool_result", "data": {"tool": "...", "data": {...}}}\n\n
 *   data: {"event": "delta",       "data": {"text": "...", "session_id": "..."}}\n\n
 *   data: {"event": "figure_result","data": {"asset_id": "...", "image_url": "..."}}\n\n
 *   data: {"event": "reflexion_patch","data": {"message": "..."}}\n\n
 *   data: {"event": "message_end", "data": {"session_id": "...", "message_id": "..."}}\n\n
 *   data: {"event": "error",       "data": {"code": "...", "message": "..."}}\n\n
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

export interface SseMessageStart {
  event: 'message_start'
  data: { session_id: string }
}

export interface SseThinking {
  event: 'thinking'
  data: { type: string; message: string }
}

export interface SseToolResult {
  event: 'tool_result'
  data: { tool: string; data: Record<string, unknown> }
}

export interface SseDelta {
  event: 'delta'
  data: { text: string; session_id: string }
}

export interface SseFigureResult {
  event: 'figure_result'
  data: { asset_id: string; image_url: string }
}

export interface SseReflexionPatch {
  event: 'reflexion_patch'
  data: { message: string }
}

export interface SseMessageEnd {
  event: 'message_end'
  data: { session_id: string; message_id: string }
}

export interface SseError {
  event: 'error'
  data: { code: string; message: string }
}

export type SseEvent =
  | SseMessageStart
  | SseThinking
  | SseToolResult
  | SseDelta
  | SseFigureResult
  | SseReflexionPatch
  | SseMessageEnd
  | SseError

export interface SseCallbacks {
  onMessageStart?: (data: SseMessageStart['data']) => void
  onThinking?: (data: SseThinking['data']) => void
  onToolResult?: (data: SseToolResult['data']) => void
  onDelta?: (data: SseDelta['data']) => void
  onFigureResult?: (data: SseFigureResult['data']) => void
  onReflexionPatch?: (data: SseReflexionPatch['data']) => void
  onMessageEnd?: (data: SseMessageEnd['data']) => void
  onError?: (data: SseError['data']) => void
  onNetworkError?: (err: Error) => void
}

export interface ChatCompletionPayload {
  session_id?: string | null
  message: string
  asset_ids?: string[]
  client_user_id: string
}

/**
 * 发起 SSE 聊天请求，通过回调分发各类事件。
 * 返回 AbortController，调用 abort() 可中断连接。
 */
export function streamChat(payload: ChatCompletionPayload, callbacks: SseCallbacks): AbortController {
  const controller = new AbortController()

  // 清理 payload 中的 null/undefined 字段
  const body: Record<string, unknown> = { ...payload }
  Object.keys(body).forEach((k) => {
    if (body[k] == null) delete body[k]
  })

  fetch(BASE_URL + '/api/v1/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      if (!response.body) {
        throw new Error('响应体为空')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // SSE 事件以 \n\n 分隔
        const parts = buffer.split('\n\n')
        // 最后一段可能不完整，保留到下次
        buffer = parts.pop() ?? ''

        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith('data:')) continue

          const jsonStr = line.slice(5).trim()
          if (!jsonStr || jsonStr === '[DONE]') continue

          try {
            const evt = JSON.parse(jsonStr) as SseEvent
            dispatchEvent(evt, callbacks)
          } catch {
            // 忽略解析失败的行
          }
        }
      }
    })
    .catch((err: Error) => {
      if (err.name === 'AbortError') return
      callbacks.onNetworkError?.(err)
    })

  return controller
}

function dispatchEvent(evt: SseEvent, callbacks: SseCallbacks) {
  switch (evt.event) {
    case 'message_start':
      callbacks.onMessageStart?.(evt.data)
      break
    case 'thinking':
      callbacks.onThinking?.(evt.data)
      break
    case 'tool_result':
      callbacks.onToolResult?.(evt.data)
      break
    case 'delta':
      callbacks.onDelta?.(evt.data)
      break
    case 'figure_result':
      callbacks.onFigureResult?.(evt.data)
      break
    case 'reflexion_patch':
      callbacks.onReflexionPatch?.(evt.data)
      break
    case 'message_end':
      callbacks.onMessageEnd?.(evt.data)
      break
    case 'error':
      callbacks.onError?.(evt.data)
      break
  }
}
