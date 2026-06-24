import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/lib/test/render";
import type { BuildArtifact, ExecutionTemplate, NodeInfo } from "@/lib/api/types";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/templates",
}));

const listTemplates = vi.fn();
const createTemplate = vi.fn();
const updateTemplate = vi.fn();
const runTemplate = vi.fn();
const deleteTemplate = vi.fn();
vi.mock("@/lib/api/templates", () => ({
  listTemplates: () => listTemplates(),
  createTemplate: (p: unknown) => createTemplate(p),
  updateTemplate: (id: string, p: unknown) => updateTemplate(id, p),
  runTemplate: (id: string) => runTemplate(id),
  deleteTemplate: (id: string) => deleteTemplate(id),
}));
const listBuildArtifacts = vi.fn();
vi.mock("@/lib/api/artifacts", () => ({
  listBuildArtifacts: () => listBuildArtifacts(),
}));
const listNodes = vi.fn();
vi.mock("@/lib/api/nodes", () => ({ listNodes: () => listNodes() }));

import TemplatesPage from "@/app/(app)/templates/page";

const template: ExecutionTemplate = {
  id: "tpl-1",
  name: "demo-template",
  description: null,
  build_artifact_id: "art-1",
  artifact_type: "scrapy",
  project: "demo",
  version: "v1",
  command: "scrapy crawl phase1",
  node_strategy: "all",
  node_ids: [],
  created_at: null,
  updated_at: null,
};

const artifact: BuildArtifact = {
  id: "art-1",
  artifact_type: "scrapy",
  package_format: "egg",
  name: "demo",
  filename: "demo.egg",
  content_hash: "h",
  size_bytes: 1,
  project: "demo",
  version: "v1",
  spiders: ["phase1", "phase2"],
  fetch_path: null,
  runnable: true,
  archived: false,
  archived_at: null,
  created_at: null,
  updated_at: null,
};

const node: NodeInfo = {
  id: "node-1",
  agent_id: "agent-1",
  endpoint: "http://a1:6800",
  status: "healthy",
  capabilities: { scrapy: true },
  health: {},
  last_seen_at: null,
  scheduling_enabled: true,
  scheduling_disabled_at: null,
  deleted_at: null,
};

beforeEach(() => {
  push.mockReset();
  listTemplates.mockReset().mockResolvedValue([template]);
  createTemplate.mockReset().mockResolvedValue(template);
  updateTemplate.mockReset().mockResolvedValue(template);
  runTemplate.mockReset().mockResolvedValue({ task_id: "task-9", status: "queued" });
  deleteTemplate.mockReset().mockResolvedValue(undefined);
  listBuildArtifacts.mockReset().mockResolvedValue([artifact]);
  listNodes.mockReset().mockResolvedValue([node]);
});

afterEach(() => vi.clearAllMocks());

describe("TemplatesPage", () => {
  it("renders templates and their command", async () => {
    renderWithProviders(<TemplatesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("template-name-demo-template"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("template-command-demo-template"),
    ).toHaveTextContent("scrapy crawl phase1");
  });

  it("defaults the command from the artifact's first spider on open", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TemplatesPage />);
    await waitFor(() =>
      expect(screen.getByTestId("template-create")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("template-create"));
    await waitFor(() =>
      expect(screen.getByTestId("template-dialog")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("template-command-input")).toHaveValue(
      "scrapy crawl phase1",
    );
  });

  it("runs a template and navigates to the created task detail route", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TemplatesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("template-run-demo-template"),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("template-run-demo-template"));
    await waitFor(() => expect(runTemplate).toHaveBeenCalledWith("tpl-1"));
    expect(push).toHaveBeenCalledWith("/tasks/detail?id=task-9");
  });

  it("edits a template: pre-fills the dialog and calls updateTemplate", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TemplatesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("template-edit-demo-template"),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("template-edit-demo-template"));
    await waitFor(() =>
      expect(screen.getByTestId("template-dialog")).toBeInTheDocument(),
    );
    // Dialog is pre-filled from the row.
    expect(screen.getByTestId("template-name-input")).toHaveValue(
      "demo-template",
    );
    expect(screen.getByTestId("template-command-input")).toHaveValue(
      "scrapy crawl phase1",
    );
    await user.click(screen.getByTestId("template-submit"));
    await waitFor(() =>
      expect(updateTemplate).toHaveBeenCalledWith("tpl-1", {
        name: "demo-template",
        build_artifact_id: "art-1",
        command: "scrapy crawl phase1",
        node_strategy: "all",
        node_ids: [],
      }),
    );
    expect(createTemplate).not.toHaveBeenCalled();
  });

  it("edit form keeps an archived current binding visible but not a fresh option", async () => {
    const user = userEvent.setup();
    // The template is bound to art-1, which has since been archived. A second,
    // non-archived artifact is the only fresh selectable option.
    const archived: BuildArtifact = {
      ...artifact,
      archived: true,
      archived_at: "2026-06-24T00:00:00Z",
    };
    const fresh: BuildArtifact = {
      ...artifact,
      id: "art-2",
      name: "fresh",
      filename: "fresh.egg",
      archived: false,
      archived_at: null,
    };
    listBuildArtifacts.mockReset().mockResolvedValue([archived, fresh]);
    renderWithProviders(<TemplatesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("template-edit-demo-template"),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("template-edit-demo-template"));
    await waitFor(() =>
      expect(screen.getByTestId("template-dialog")).toBeInTheDocument(),
    );
    // Open the artifact picker.
    await user.click(screen.getByTestId("template-artifact-select"));
    // The current (archived) binding is shown but disabled — not a fresh choice.
    const current = await screen.findByTestId(
      "template-artifact-archived-current",
    );
    expect(current).toHaveTextContent("Archived");
    expect(current).toHaveAttribute("data-disabled");
    // The non-archived artifact IS offered as a selectable option.
    const freshOption = screen.getByText("fresh · fresh.egg");
    expect(freshOption).not.toHaveAttribute("data-disabled");
  });

  it("deletes a template only after confirmation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TemplatesPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("template-name-demo-template"),
      ).toBeInTheDocument(),
    );
    // Cancel first: no delete.
    await user.click(screen.getByText("Delete"));
    await user.click(screen.getByTestId("confirm-cancel"));
    expect(deleteTemplate).not.toHaveBeenCalled();
    // Confirm: deletes.
    await user.click(screen.getByText("Delete"));
    await user.click(screen.getByTestId("confirm-accept"));
    await waitFor(() => expect(deleteTemplate).toHaveBeenCalledWith("tpl-1"));
  });
});
