import { describe, expect, it, vi, beforeEach } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import type { BuildArtifact } from "@/api/types";
import zh from "@/i18n/locales/zh";
import en from "@/i18n/locales/en";

function makeArtifact(overrides: Partial<BuildArtifact> = {}): BuildArtifact {
  return {
    id: "art-1",
    artifact_type: "scrapy",
    package_format: "egg",
    name: "demo",
    filename: "demo_phase1.egg",
    content_hash: "abcdef0123456789abcdef",
    size_bytes: 1290000,
    project: "demo",
    version: "1.0",
    spiders: ["phase1", "phase2"],
    fetch_path: null,
    runnable: true,
    created_at: "2026-06-18T00:00:00Z",
    updated_at: "2026-06-18T00:00:00Z",
    ...overrides,
  };
}

const listBuildArtifacts = vi.fn(async () => [makeArtifact()]);
const uploadEgg = vi.fn(async (_input: unknown) => ({
  artifact: makeArtifact(),
  spiders: [] as string[],
}));

vi.mock("@/api/artifacts", () => ({
  listBuildArtifacts: () => listBuildArtifacts(),
  uploadEgg: (input: unknown) => uploadEgg(input),
}));

import BuildArtifactsPage from "@/pages/BuildArtifactsPage.vue";

function makeI18n() {
  return createI18n({
    legacy: false,
    locale: "zh",
    fallbackLocale: "en",
    messages: { zh, en },
  });
}

function makeStubs() {
  return {
    "el-card": { template: "<div><slot name='header' /><slot /></div>" },
    "el-button": {
      template: "<button @click=\"$emit('click')\"><slot /></button>",
    },
    "el-upload": { template: "<div><slot /></div>" },
    "el-table": { props: ["data"], template: "<div class='el-table'><slot /></div>" },
    "el-table-column": {
      props: ["label", "prop"],
      template: "<div class='col'>{{ label }}</div>",
    },
    "el-dialog": {
      props: ["modelValue"],
      template: "<div v-if='modelValue'><slot /><slot name='footer' /></div>",
    },
    "el-descriptions": { template: "<div><slot /></div>" },
    "el-descriptions-item": {
      props: ["label"],
      template: "<div>{{ label }}<slot /></div>",
    },
    "el-tag": { template: "<span class='el-tag'><slot /></span>" },
  };
}

describe("BuildArtifactsPage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    listBuildArtifacts.mockClear();
    uploadEgg.mockClear();
  });

  it("formats size as MB", async () => {
    const wrapper = mount(BuildArtifactsPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      formatMB: (n: number) => string;
    };
    // Raw size_bytes is displayed as a rounded MB string.
    expect(vm.formatMB(1290000)).toBe("1.23 MB");
    expect(vm.formatMB(0)).toBe("0.00 MB");
    expect(vm.formatMB(2097152)).toBe("2.00 MB");
  });

  it("opens Details with the artifact's spiders for read-only display", async () => {
    const wrapper = mount(BuildArtifactsPage, {
      global: { plugins: [makeI18n()], stubs: makeStubs() },
    });
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      detailsVisible: boolean;
      selected: BuildArtifact | null;
      openDetails: (a: BuildArtifact) => void;
    };
    expect(vm.detailsVisible).toBe(false);
    vm.openDetails(makeArtifact());
    await flushPromises();
    expect(vm.detailsVisible).toBe(true);
    expect(vm.selected?.spiders).toEqual(["phase1", "phase2"]);
    // The dialog renders the spiders as tags (read-only, no input element).
    const box = wrapper.find('[data-testid="artifact-details-spiders"]');
    expect(box.exists()).toBe(true);
    expect(box.findAll(".el-tag").length).toBe(2);
    expect(box.text()).toContain("phase1");
    expect(box.text()).toContain("phase2");
  });
});
