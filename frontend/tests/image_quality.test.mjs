import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const imageUtil = readFileSync(resolve('src/utils/image.ts'), 'utf8')

assert.match(
  imageUtil,
  /const MAX_DIMENSION = 3000/,
  'H5 image upload should preserve enough pixels for geometry overlay crops',
)
assert.match(
  imageUtil,
  /const JPEG_QUALITY = 0\.92/,
  'H5 image upload should avoid aggressive JPEG quality loss for geometry point location',
)
assert.match(
  imageUtil,
  /sizeType:\s*\['original'\]/,
  'image picker should hand the original image to our controlled compressor',
)
