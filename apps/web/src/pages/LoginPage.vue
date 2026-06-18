<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n();
const router = useRouter();
const auth = useAuthStore();

const form = reactive({
  username: "",
  password: "",
});
const loading = ref(false);
const errorMsg = ref("");

async function onSubmit(): Promise<void> {
  errorMsg.value = "";
  loading.value = true;
  try {
    await auth.login(form.username, form.password);
    await router.push("/dashboard");
  } catch {
    errorMsg.value = t("login.error");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-wrapper">
    <el-card class="login-card">
      <template #header>
        <span>{{ t("login.title") }}</span>
      </template>
      <el-form label-position="top" @submit.prevent="onSubmit">
        <el-form-item :label="t('login.username')">
          <el-input v-model="form.username" autocomplete="username" />
        </el-form-item>
        <el-form-item :label="t('login.password')">
          <el-input
            v-model="form.password"
            type="password"
            autocomplete="current-password"
            show-password
          />
        </el-form-item>
        <el-alert
          v-if="errorMsg"
          :title="errorMsg"
          type="error"
          :closable="false"
          show-icon
        />
        <el-form-item>
          <el-button
            type="primary"
            :loading="loading"
            native-type="submit"
            @click="onSubmit"
          >
            {{ t("login.submit") }}
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
}
.login-card {
  width: 360px;
}
</style>
