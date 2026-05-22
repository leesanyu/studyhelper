<template>
  <view class="feedback-buttons">
    <view
      class="feedback-btn feedback-btn-confused"
      :class="{ 'feedback-btn-disabled': disabled }"
      @click="onConfused"
    >
      <text class="feedback-btn-text">不甚理解</text>
    </view>
    <view
      class="feedback-btn feedback-btn-got"
      :class="{ 'feedback-btn-disabled': disabled }"
      @click="onGotIt"
    >
      <text class="feedback-btn-text">我会了</text>
    </view>
  </view>
</template>

<script setup lang="ts">
const props = defineProps<{
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'send', message: string): void
}>()

function onConfused() {
  if (props.disabled) return
  emit('send', '我还是不太理解，请更细致地引导我')
}

function onGotIt() {
  if (props.disabled) return
  emit('send', '我理解了，请总结一下并给我一道相似题')
}
</script>

<style scoped>
.feedback-buttons {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #f0f0f0;
}

.feedback-btn {
  flex: 1;
  padding: 6px 0;
  border-radius: 16px;
  text-align: center;
  border: 1px solid #e0e0e0;
  background-color: #fafafa;
  cursor: pointer;
  transition: background-color 0.15s;
}

.feedback-btn:active {
  background-color: #f0f0f0;
}

.feedback-btn-confused {
  border-color: #faad14;
  color: #faad14;
}

.feedback-btn-got {
  border-color: #52c41a;
  color: #52c41a;
}

.feedback-btn-disabled {
  opacity: 0.4;
  pointer-events: none;
}

.feedback-btn-text {
  font-size: 13px;
}
</style>
