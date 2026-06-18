<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { AppLocale } from "@/i18n";

const { locale } = useI18n();

const current = computed<AppLocale>(() => (locale.value as AppLocale) ?? "zh");

function toggle(): void {
  locale.value = current.value === "zh" ? "en" : "zh";
}
</script>

<template>
  <el-button text @click="toggle">
    {{ current === "zh" ? "EN" : "中文" }}
  </el-button>
</template>
