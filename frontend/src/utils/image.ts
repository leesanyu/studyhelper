/**
 * 图片工具：选择 + Canvas 压缩（最大 3000px 长边，JPEG quality 92）
 */

const MAX_DIMENSION = 3000
const JPEG_QUALITY = 0.92

export interface ChooseImageResult {
  /** 压缩后的临时文件路径 */
  filePath: string
  /** 原始临时路径（用于预览） */
  originalPath: string
}

/**
 * 选择图片并压缩。
 * H5 端使用 Canvas 控制压缩；非 H5 端直接使用原图。
 */
export function chooseAndCompressImage(): Promise<ChooseImageResult> {
  return new Promise((resolve, reject) => {
    uni.chooseImage({
      count: 1,
      sizeType: ['original'],
      sourceType: ['album', 'camera'],
      async success(res) {
        const originalPath = res.tempFilePaths[0]
        try {
          // #ifdef H5
          const compressed = await compressImageH5(originalPath)
          resolve({ filePath: compressed, originalPath })
          // #endif
          // #ifndef H5
          resolve({ filePath: originalPath, originalPath })
          // #endif
        } catch {
          // 压缩失败时降级使用原图
          resolve({ filePath: originalPath, originalPath })
        }
      },
      fail(err) {
        reject(new Error(err.errMsg || '选择图片失败'))
      },
    })
  })
}

/** H5 端 Canvas 压缩实现 */
async function compressImageH5(filePath: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => {
      let { width, height } = img
      // 按长边缩放
      if (width > MAX_DIMENSION || height > MAX_DIMENSION) {
        if (width >= height) {
          height = Math.round((height * MAX_DIMENSION) / width)
          width = MAX_DIMENSION
        } else {
          width = Math.round((width * MAX_DIMENSION) / height)
          height = MAX_DIMENSION
        }
      }

      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        reject(new Error('Canvas 不可用'))
        return
      }
      ctx.drawImage(img, 0, 0, width, height)
      resolve(canvas.toDataURL('image/jpeg', JPEG_QUALITY))
    }
    img.onerror = () => reject(new Error('图片加载失败'))
    img.src = filePath
  })
}
