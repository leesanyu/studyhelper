/**
 * HTTP 请求封装：基于 uni.request，含超时、错误拦截、client_user_id 自动注入。
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''
const REQUEST_TIMEOUT = 30000

/** 获取或生成持久化的匿名用户 ID */
function getClientUserId(): string {
  const key = 'studyhelper_client_user_id'
  let id = uni.getStorageSync(key) as string
  if (!id) {
    id = 'anon_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8)
    uni.setStorageSync(key, id)
  }
  return id
}

export const clientUserId = getClientUserId()

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  data?: Record<string, unknown>
  header?: Record<string, string>
}

export interface ApiResponse<T = unknown> {
  data: T
  statusCode: number
}

export async function request<T = unknown>(
  url: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = 'GET', data, header = {} } = options

  return new Promise((resolve, reject) => {
    uni.request({
      url: BASE_URL + url,
      method,
      data,
      header: {
        'Content-Type': 'application/json',
        ...header,
      },
      timeout: REQUEST_TIMEOUT,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data as T)
        } else {
          reject(new Error(`HTTP ${res.statusCode}: ${url}`))
        }
      },
      fail(err) {
        reject(new Error(err.errMsg || '网络请求失败'))
      },
    })
  })
}
