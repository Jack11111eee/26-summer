<template>
  <div class="tabs">
    <button
      v-for="t in tabs"
      :key="t.key"
      type="button"
      class="tab"
      :class="{ active: t.key === modelValue }"
      @click="$emit('update:modelValue', t.key)"
    >
      {{ t.label }}<span v-if="t.cnt != null"> ({{ t.cnt }})</span>
    </button>
  </div>
</template>

<script setup>
// 通用 tab：tabs [{key,label,cnt?}]，v-model:key 形态（受控）。
defineProps({
  tabs: { type: Array, required: true },
  modelValue: { type: String, required: true }
})
defineEmits(['update:modelValue'])
</script>
