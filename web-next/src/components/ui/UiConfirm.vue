<template>
  <UiModal :title="title" :sub="sub" :confirm-text="confirmText" :danger="danger" @close="$emit('close')" @confirm="$emit('confirm')">
    <p style="font-size: 13px; line-height: 1.7">{{ message }}</p>
  </UiModal>
</template>

<script setup>
// 确认弹窗：包装 UiModal 的危险操作确认样式。
import UiModal from './UiModal.vue'

defineProps({
  title: { type: String, default: '请确认' },
  sub: { type: String, default: '' },
  message: { type: String, required: true },
  confirmText: { type: String, default: '确认执行' },
  danger: { type: Boolean, default: false }
})
defineEmits(['close', 'confirm'])
</script>
