import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const page = readFileSync(resolve('src/pages/chat/index.vue'), 'utf8')
const chatTypes = readFileSync(resolve('src/api/chat.ts'), 'utf8')

assert.match(page, /post_answer_status/, 'chat page should track post-answer figure status')
assert.match(page, /canShowFeedback\(msg\)/, 'feedback buttons should use completion-aware guard')
assert.match(page, /message_completed\s*=\s*true/, 'message_end should mark the assistant message completed')
assert.match(
  page,
  /答案已生成，正在处理辅助线图/,
  'answer_end should show an explicit figure generation status',
)
assert.match(
  chatTypes,
  /message_completed\?: boolean/,
  'ChatMessage should expose immediate message completion state',
)
assert.match(
  chatTypes,
  /post_answer_status\?: string/,
  'ChatMessage should expose post-answer status text',
)
