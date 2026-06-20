// Phase 1.8.2: a small shared confirmation helper for destructive/offline
// actions. It wraps Element Plus' ElMessageBox so every page asks before an
// irreversible or service-affecting operation, and keeps the pages simple.
//
// It is a standalone module on purpose: page unit tests mock `@/utils/confirm`
// to drive the confirm/cancel branches without rendering a real message box.
import { ElMessageBox } from "element-plus";

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmText: string;
  cancelText: string;
  // Element Plus message-box icon style; destructive actions use "warning".
  type?: "warning" | "error" | "info" | "success";
}

// Resolve to true when the user confirms, false when they cancel/close.
export async function confirmAction(opts: ConfirmOptions): Promise<boolean> {
  try {
    await ElMessageBox.confirm(opts.message, opts.title, {
      confirmButtonText: opts.confirmText,
      cancelButtonText: opts.cancelText,
      type: opts.type ?? "warning",
    });
    return true;
  } catch {
    // ElMessageBox.confirm rejects on cancel or close — treat as "do not proceed".
    return false;
  }
}
