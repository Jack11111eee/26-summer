<template>
  <teleport to="body">
    <div class="overlay" @click.self="$emit('close')">
      <div class="modal" :class="{ wide }" role="dialog" aria-modal="true">
        <div class="modal-title">{{ title }}</div>
        <div v-if="sub" class="modal-sub">{{ sub }}</div>
        <slot />
        <div class="modal-actions">
          <button class="btn" type="button" @click="$emit('close')">{{ cancelText || '取消' }}</button>
          <slot name="actions">
            <button class="btn primary" :class="{ danger }" type="button" :disabled="disabled" @click="$emit('confirm')">{{ confirmText || '确定' }}</button>
          </slot>
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup>
// 通用 modal：素色白卡。点遮罩关闭可由 no-close 禁用（危险操作防误触）。
defineProps({
  title: { type: String, default: '' },
  sub: { type: String, default: '' },
  wide: { type: Boolean, default: false },
  confirmText: { type: String, default: '' },
  cancelText: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  noClose: { type: Boolean, default: false },
  danger: { type: Boolean, default: false }
})
defineEmits(['close', 'confirm'])
</script>
