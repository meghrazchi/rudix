import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NextIntlClientProvider } from "next-intl";

import { KeyboardShortcutsModal } from "@/components/help/KeyboardShortcutsModal";

const messages = {
  help: {
    keyboardShortcutsTitle: "Keyboard shortcuts",
    close: "Close",
    shortcuts: {
      search: "Open global search",
      openShortcuts: "Open keyboard shortcuts",
      submitMessage: "Send chat message",
      closeOverlay: "Close overlay or menu",
      focusNext: "Move focus forward",
      focusPrevious: "Move focus backward",
      groups: {
        navigation: "Navigation",
        chat: "Chat",
        overlays: "Overlays & Focus",
      },
    },
  },
};

function renderModal(isOpen: boolean, onClose: () => void = vi.fn()) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <KeyboardShortcutsModal isOpen={isOpen} onClose={onClose} />
    </NextIntlClientProvider>,
  );
}

describe("KeyboardShortcutsModal", () => {
  it("renders nothing when closed", () => {
    renderModal(false);
    expect(
      screen.queryByRole("dialog", { name: "Keyboard shortcuts" }),
    ).not.toBeInTheDocument();
  });

  it("renders dialog and shortcut groups when open", () => {
    renderModal(true);

    expect(
      screen.getByRole("dialog", { name: "Keyboard shortcuts" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Navigation")).toBeInTheDocument();
    expect(screen.getByText("Chat")).toBeInTheDocument();
    expect(screen.getByText("Overlays & Focus")).toBeInTheDocument();
  });

  it("shows expected shortcut descriptions", () => {
    renderModal(true);

    expect(screen.getByText("Open global search")).toBeInTheDocument();
    expect(screen.getByText("Open keyboard shortcuts")).toBeInTheDocument();
    expect(screen.getByText("Send chat message")).toBeInTheDocument();
    expect(screen.getByText("Close overlay or menu")).toBeInTheDocument();
    expect(screen.getByText("Move focus forward")).toBeInTheDocument();
  });

  it("calls onClose when backdrop is clicked", async () => {
    const onClose = vi.fn();
    const { container } = renderModal(true, onClose);

    const backdrop = container.firstChild as HTMLElement;
    await userEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when Esc button is clicked", async () => {
    const onClose = vi.fn();
    renderModal(true, onClose);

    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not propagate click on dialog content to backdrop", async () => {
    const onClose = vi.fn();
    renderModal(true, onClose);

    const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
    await userEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("has aria-modal on the dialog element", () => {
    renderModal(true);

    const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });
});
