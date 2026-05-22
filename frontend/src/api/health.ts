/**
 * 健康检查 API
 */
import { request } from '../utils/request'

export function checkHealth() {
  return request<{ status: string }>('/health')
}
