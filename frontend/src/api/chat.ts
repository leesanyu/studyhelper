/**
 * 聊天相关类型定义和 API（SSE 流式接口在 utils/sse.ts 实现）
 */

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  /** 用户消息附带的图片 asset_id 列表 */
  asset_ids?: string[]
  /** 用户消息附带的图片本地预览路径（仅前端展示用） */
  image_paths?: string[]
  loading?: boolean
  error?: string
  /** 后端返回的消息 ID（message_end 后写入） */
  message_id?: string
  /** message_end 已到达，用于触发 figure 块超时检查 */
  message_ended?: boolean
  /** 收到的 figure_result 事件列表（Story 3.7+4.4 处理） */
  figure_results?: Array<{ asset_id: string; image_url: string }>
  /** 当前 thinking 步骤提示（如"分析题目中..."） */
  thinking_message?: string
  /** 收到的 tool_result 事件列表 */
  tool_results?: Array<{ tool: string; data: Record<string, unknown> }>
  /** 收到的 reflexion_patch 事件 */
  reflexion_message?: string
}

export interface ChatCompletionRequest {
  session_id?: string
  message: string
  asset_ids?: string[]
  client_user_id: string
}
