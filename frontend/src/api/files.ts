/**
 * 文件上传 API
 */
import { clientUserId } from '../utils/request'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

export interface UploadResult {
  asset_id: string
  preview_url: string
  mime_type: string
  size: number
}

export function uploadFile(filePath: string): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: BASE_URL + '/api/v1/files/upload',
      filePath,
      name: 'file',
      formData: { client_user_id: clientUserId },
      success(res) {
        if (res.statusCode === 200) {
          try {
            const data = typeof res.data === 'string' ? JSON.parse(res.data) : res.data
            resolve(data as UploadResult)
          } catch {
            reject(new Error('上传响应解析失败'))
          }
        } else {
          reject(new Error(`上传失败: HTTP ${res.statusCode}`))
        }
      },
      fail(err) {
        reject(new Error(err.errMsg || '上传失败'))
      },
    })
  })
}
