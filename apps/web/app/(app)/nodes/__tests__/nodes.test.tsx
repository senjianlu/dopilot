import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/lib/test/render";
import type { NodeInfo } from "@/lib/api/types";

const listNodes = vi.fn();
const offlineNode = vi.fn();
const onlineNode = vi.fn();
const deleteNode = vi.fn();
vi.mock("@/lib/api/nodes", () => ({
  listNodes: () => listNodes(),
  offlineNode: (id: string) => offlineNode(id),
  onlineNode: (id: string) => onlineNode(id),
  deleteNode: (id: string) => deleteNode(id),
}));

import NodesPage from "@/app/(app)/nodes/page";

function makeNode(overrides: Partial<NodeInfo> = {}): NodeInfo {
  return {
    id: "node-1",
    agent_id: "agent-1",
    endpoint: "http://a1:6800",
    status: "healthy",
    capabilities: { scrapy: true, script: true },
    health: {},
    last_seen_at: "2026-06-19T00:00:00Z",
    scheduling_enabled: true,
    scheduling_disabled_at: null,
    deleted_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  listNodes.mockReset().mockResolvedValue([makeNode()]);
  offlineNode.mockReset().mockResolvedValue(makeNode({ scheduling_enabled: false }));
  onlineNode.mockReset().mockResolvedValue(makeNode());
  deleteNode.mockReset().mockResolvedValue(makeNode());
});

afterEach(() => vi.clearAllMocks());

describe("NodesPage", () => {
  it("renders a node with a healthy badge and active capability tags", async () => {
    renderWithProviders(<NodesPage />);
    await waitFor(() =>
      expect(screen.getByTestId("node-agent-agent-1")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("node-badge-agent-1")).toHaveAttribute(
      "data-tone",
      "green",
    );
    // scrapy + script advertised -> green; docker reserved -> gray.
    expect(screen.getByTestId("node-cap-agent-1-scrapy")).toHaveAttribute(
      "data-tone",
      "green",
    );
    expect(screen.getByTestId("node-cap-agent-1-script")).toHaveAttribute(
      "data-tone",
      "green",
    );
    expect(screen.getByTestId("node-cap-agent-1-docker")).toHaveAttribute(
      "data-tone",
      "gray",
    );
  });

  it("offlines a node only after confirmation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<NodesPage />);
    await waitFor(() =>
      expect(screen.getByTestId("node-offline-agent-1")).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("node-offline-agent-1"));
    await waitFor(() =>
      expect(screen.getByTestId("confirm-dialog")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("confirm-accept"));
    await waitFor(() => expect(offlineNode).toHaveBeenCalledWith("node-1"));
  });

  it("does not offline when the confirmation is cancelled", async () => {
    const user = userEvent.setup();
    renderWithProviders(<NodesPage />);
    await waitFor(() =>
      expect(screen.getByTestId("node-offline-agent-1")).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("node-offline-agent-1"));
    await user.click(screen.getByTestId("confirm-cancel"));
    expect(offlineNode).not.toHaveBeenCalled();
  });
});
