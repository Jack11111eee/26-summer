<template>
  <select class="select" :value="modelValue" @change="onChange">
    <option v-if="placeholder" value="" disabled>{{ placeholder }}</option>
    <option v-for="o in options" :key="o.value" :value="o.value">{{ o.label }}</option>
  </select>
</template>

<script setup>
// 通用下拉：options [{value,label}]；v-model:value 形态。
const props = defineProps({
  modelValue: { type: [String, Number, null], default: '' },
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue'])

function onChange(e) {
  const raw = e.target.value
  emit('update:modelValue', raw === '' && props.placeholder ? '' : raw)
}
</script>
