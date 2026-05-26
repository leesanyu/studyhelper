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
  /** message_end 已到达，表示后置反思 / 辅助线等流程已结束，可展示反馈按钮 */
  message_completed?: boolean
  /** 文字答案结束后、后置流程结束前展示的状态提示 */
  post_answer_status?: string
  /** 收到的 figure_result 事件列表（Story 3.7+4.4 处理） */
  figure_results?: Array<{ asset_id: string; image_url: string; message_id?: string }>
  /** 收到的透明自检结果 */
  reflexion_results?: Array<{
    status: string
    visible_message: string
    corrected_content?: string
    issues?: string[]
    figure_guidance?: string
    message_id?: string
  }>
  /** 当前 thinking 步骤提示（如"分析题目中..."） */
  thinking_message?: string
  /** 收到的 tool_result 事件列表 */
  tool_results?: Array<{ tool: string; data: Record<string, unknown> }>
}

export interface ChatCompletionRequest {
  session_id?: string
  message: string
  asset_ids?: string[]
  client_user_id: string
}
