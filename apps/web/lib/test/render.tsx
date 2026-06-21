import * as React from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n/config";
import { ConfirmProvider } from "@/hooks/use-confirm";

// Render a component inside the i18n + confirm providers the (app) pages rely on.
export function renderWithProviders(
  ui: React.ReactElement,
  options?: RenderOptions,
) {
  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <I18nextProvider i18n={i18n}>
        <ConfirmProvider>{children}</ConfirmProvider>
      </I18nextProvider>
    );
  }
  return render(ui, { wrapper: Wrapper, ...options });
}
