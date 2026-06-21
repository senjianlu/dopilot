import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import i18n from "@/lib/i18n/config";

// Assert against English strings deterministically (the app default is zh).
void i18n.changeLanguage("en");

afterEach(() => {
  cleanup();
});

// jsdom lacks matchMedia (next-themes), ResizeObserver (recharts/sidebar), and
// a few element methods radix overlays touch. Provide minimal stubs.
if (!window.matchMedia) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
const g = globalThis as unknown as Record<string, unknown>;
g.ResizeObserver = g.ResizeObserver ?? ResizeObserverStub;

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}

// jsdom has no EventSource; the LogViewer constructs one on mount. A no-op
// default keeps unrelated page tests from throwing (the log-viewer test installs
// its own recording stand-in).
class EventSourceStub {
  static CLOSED = 2;
  addEventListener() {}
  removeEventListener() {}
  close() {}
}
g.EventSource = g.EventSource ?? EventSourceStub;
// Radix uses these in jsdom where they are missing.
Element.prototype.hasPointerCapture =
  Element.prototype.hasPointerCapture ?? (() => false);
Element.prototype.setPointerCapture =
  Element.prototype.setPointerCapture ?? (() => {});
Element.prototype.releasePointerCapture =
  Element.prototype.releasePointerCapture ?? (() => {});
