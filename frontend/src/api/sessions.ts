/**
 * 会话相关 API
 */
import { request, clientUserId } from '../utils/request'

export interface Session {
  session_id: string
  title: string
  status: string
  client_user_id: string
  asset_ids: string[]
  messages: Message[]
}

export interface Message {
  message_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface SessionListItem {
  session_id: string
  title: string
  status: string
  last_message: string
  subject: string
  knowledge_points: string[]
}

export function createSession(params?: { title?: string; asset_ids?: string[] }) {
  return request<Session>('/api/v1/sessions', {
    method: 'POST',
    data: {
      client_user_id: clientUserId,
      ...params,
    },
  })
}

export function getSessions() {
  return request<{ items: SessionListItem[] }>(
    `/api/v1/sessions?client_user_id=${encodeURIComponent(clientUserId)}`,
  )
}

export function getSession(sessionId: string) {
  return request<Session>(`/api/v1/sessions/${sessionId}`)
}
