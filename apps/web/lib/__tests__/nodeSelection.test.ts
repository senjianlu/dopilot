import { describe, expect, it } from "vitest";
import type { NodeInfo } from "@/lib/api/types";
import {
  nodeKey,
  nodeToneForKey,
  schedulableNodes,
  selectableNodes,
} from "@/lib/nodeSelection";
import { nodeBadge } from "@/lib/nodeBadge";

function makeNode(overrides: Partial<NodeInfo> = {}): NodeInfo {
  return {
    id: "node-1",
    agent_id: "agent-1",
    endpoint: "http://a1:6800",
    status: "healthy",
    capabilities: { scrapy: true },
    health: {},
    last_seen_at: "2026-06-19T00:00:00Z",
    scheduling_enabled: true,
    scheduling_disabled_at: null,
    deleted_at: null,
    ...overrides,
  };
}

const nodes: NodeInfo[] = [
  makeNode(),
  makeNode({ id: "node-2", agent_id: "agent-2", scheduling_enabled: false }),
  makeNode({
    id: "node-3",
    agent_id: "agent-3",
    deleted_at: "2026-06-20T00:00:00Z",
  }),
  // configured-but-unseen endpoint (no DB id): excluded everywhere.
  makeNode({ id: null, agent_id: null, endpoint: "http://a4:6800" }),
];

describe("nodeSelection", () => {
  it("schedulable excludes offline, deleted, and unseen nodes", () => {
    expect(schedulableNodes(nodes).map((n) => n.id)).toEqual(["node-1"]);
  });

  it("selectable excludes offline, deleted, and unseen nodes", () => {
    expect(selectableNodes(nodes).map((n) => n.id)).toEqual(["node-1"]);
  });

  it("nodeKey prefers id, then agent_id, then endpoint", () => {
    expect(nodeKey(makeNode())).toBe("node-1");
    expect(nodeKey(makeNode({ id: null }))).toBe("agent-1");
    expect(nodeKey(makeNode({ id: null, agent_id: null }))).toBe(
      "http://a1:6800",
    );
  });
});

describe("nodeBadge tone", () => {
  it("maps health/offline/deleted to traffic-light tones", () => {
    expect(nodeToneForKey(nodes, "node-1")).toBe("green");
    expect(nodeToneForKey(nodes, "node-2")).toBe("red");
    expect(nodeToneForKey(nodes, "node-3")).toBe("gray");
  });

  it("classifies unknown online health as amber", () => {
    expect(nodeBadge(makeNode({ status: "unknown" }))).toBe("unknown");
    expect(nodeToneForKey([makeNode({ status: "unknown" })], "node-1")).toBe(
      "amber",
    );
  });
});
