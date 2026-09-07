<template>
  <teleport to="body">
    <div class="drawer-overlay" @click="$emit('close')"></div>
    <aside class="drawer" role="dialog" aria-modal="true">
      <div class="drawer-head">
        <span class="drawer-title">{{ title }}</span>
        <button class="drawer-close" type="button" aria-label="关闭" @click="$emit('close')">✕</button>
      </div>
      <div class="drawer-body">
        <slot />
      </div>
    </aside>
  </teleport>
</template>

<script setup>
// 右侧抽屉（词典编辑 / JD 工序留档）。
defineProps({ title: { type: String, default: '' } })
defineEmits(['close'])
</script>
