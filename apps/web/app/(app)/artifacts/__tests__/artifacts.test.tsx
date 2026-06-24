import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/lib/test/render";
import type { BuildArtifact } from "@/lib/api/types";

const listBuildArtifacts = vi.fn();
const uploadEgg = vi.fn();
const uploadWheel = vi.fn();
const archiveArtifact = vi.fn();
const unarchiveArtifact = vi.fn();
vi.mock("@/lib/api/artifacts", () => ({
  listBuildArtifacts: () => listBuildArtifacts(),
  uploadEgg: (input: unknown) => uploadEgg(input),
  uploadWheel: (input: unknown) => uploadWheel(input),
  archiveArtifact: (id: string) => archiveArtifact(id),
  unarchiveArtifact: (id: string) => unarchiveArtifact(id),
}));

import BuildArtifactsPage from "@/app/(app)/artifacts/page";

const scrapyArtifact: BuildArtifact = {
  id: "art-1",
  artifact_type: "scrapy",
  package_format: "egg",
  name: "demo",
  filename: "demo.egg",
  content_hash: "sha-abc",
  size_bytes: 1024,
  project: "demo",
  version: "v1",
  spiders: ["phase1", "phase2"],
  fetch_path: null,
  runnable: false,
  archived: false,
  archived_at: null,
  created_at: null,
  updated_at: null,
};

const wheelArtifact: BuildArtifact = {
  id: "art-wheel",
  artifact_type: "python_wheel",
  package_format: "wheel",
  name: "dopilot-demo",
  filename: "dopilot_demo-0.1.0-py3-none-any.whl",
  content_hash: "sha-whl",
  size_bytes: 3 * 1024 * 1024,
  project: null,
  version: "0.1.0",
  distribution: "dopilot-demo",
  spiders: [],
  fetch_path: null,
  runnable: true,
  archived: false,
  archived_at: null,
  created_at: null,
  updated_at: null,
};

beforeEach(() => {
  listBuildArtifacts.mockReset().mockResolvedValue([scrapyArtifact, wheelArtifact]);
  uploadEgg.mockReset().mockResolvedValue({ artifact: scrapyArtifact, spiders: [] });
  uploadWheel.mockReset().mockResolvedValue({ artifact: wheelArtifact, spiders: [] });
  archiveArtifact.mockReset().mockResolvedValue({ ...scrapyArtifact, archived: true });
  unarchiveArtifact.mockReset().mockResolvedValue(scrapyArtifact);
});

afterEach(() => vi.clearAllMocks());

describe("BuildArtifactsPage", () => {
  it("renders artifact rows with type, format, and runnable status", async () => {
    renderWithProviders(<BuildArtifactsPage />);
    await waitFor(() =>
      expect(screen.getByTestId("artifact-name-demo")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("artifact-type-demo")).toHaveTextContent("scrapy");
    expect(screen.getByTestId("artifact-format-demo")).toHaveTextContent("egg");
    expect(
      screen.getByTestId("artifact-type-dopilot-demo"),
    ).toHaveTextContent("python_wheel");
  });

  it("renders sizes adaptively in KB (under 1 MB) and MB (1 MB+)", async () => {
    renderWithProviders(<BuildArtifactsPage />);
    await waitFor(() =>
      expect(screen.getByTestId("artifact-size-demo")).toBeInTheDocument(),
    );
    // 1024 bytes -> KB; 3 MiB -> MB.
    expect(screen.getByTestId("artifact-size-demo")).toHaveTextContent(
      "1.00 KB",
    );
    expect(
      screen.getByTestId("artifact-size-dopilot-demo"),
    ).toHaveTextContent("3.00 MB");
  });

  it("uploads a selected egg file", async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<BuildArtifactsPage />);
    await waitFor(() =>
      expect(screen.getByTestId("artifact-name-demo")).toBeInTheDocument(),
    );
    const input = container.querySelector(
      '[data-testid="artifact-upload"] input[type="file"]',
    ) as HTMLInputElement;
    const file = new File(["egg-bytes"], "demo.egg");
    await user.upload(input, file);
    await waitFor(() => expect(uploadEgg).toHaveBeenCalledTimes(1));
    expect(uploadEgg.mock.calls[0][0]).toMatchObject({ file });
  });

  it("archives a non-archived artifact and reloads", async () => {
    const user = userEvent.setup();
    renderWithProviders(<BuildArtifactsPage />);
    await waitFor(() =>
      expect(screen.getByTestId("artifact-archive-demo")).toBeInTheDocument(),
    );
    // A non-archived artifact shows the "Archive" action and no archived badge.
    expect(screen.getByTestId("artifact-archive-demo")).toHaveTextContent(
      "Archive",
    );
    expect(
      screen.queryByTestId("artifact-archived-demo"),
    ).not.toBeInTheDocument();
    await user.click(screen.getByTestId("artifact-archive-demo"));
    await waitFor(() => expect(archiveArtifact).toHaveBeenCalledWith("art-1"));
    expect(unarchiveArtifact).not.toHaveBeenCalled();
  });

  it("shows the archived badge and an Unarchive action for archived rows", async () => {
    const user = userEvent.setup();
    listBuildArtifacts
      .mockReset()
      .mockResolvedValue([
        { ...scrapyArtifact, archived: true, archived_at: "2026-06-24T00:00:00Z" },
      ]);
    renderWithProviders(<BuildArtifactsPage />);
    await waitFor(() =>
      expect(screen.getByTestId("artifact-archived-demo")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("artifact-archive-demo")).toHaveTextContent(
      "Unarchive",
    );
    await user.click(screen.getByTestId("artifact-archive-demo"));
    await waitFor(() => expect(unarchiveArtifact).toHaveBeenCalledWith("art-1"));
    expect(archiveArtifact).not.toHaveBeenCalled();
  });

  it("shows the wheel distribution in the details dialog", async () => {
    const user = userEvent.setup();
    renderWithProviders(<BuildArtifactsPage />);
    await waitFor(() =>
      expect(
        screen.getByTestId("artifact-details-dopilot-demo"),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("artifact-details-dopilot-demo"));
    const dialog = await screen.findByTestId("artifact-details-dialog");
    expect(dialog).toHaveTextContent("Distribution");
    expect(dialog).toHaveTextContent("dopilot_demo-0.1.0-py3-none-any.whl");
  });
});
