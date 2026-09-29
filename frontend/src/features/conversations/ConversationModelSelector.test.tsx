import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { ConversationModelSelector } from "./ConversationModelSelector";
import type { SelectableChatModel } from "./types";

const defaultModelId = "11111111-1111-4111-8111-111111111111";
const alternateModelId = "22222222-2222-4222-8222-222222222222";
const models: SelectableChatModel[] = [
  {
    publicId: defaultModelId,
    displayName: "GPT-5",
    providerType: "openai",
    providerDisplayName: "OpenAI",
  },
  {
    publicId: alternateModelId,
    displayName: "Claude Sonnet",
    providerType: "anthropic",
    providerDisplayName: "Anthropic",
  },
];

function renderSelector(
  overrides: Partial<ComponentProps<typeof ConversationModelSelector>> = {},
) {
  const onChange = vi.fn();
  const onRetry = vi.fn();
  const rendered = render(
    <ConversationModelSelector
      models={models}
      defaultModelPublicId={defaultModelId}
      explicitModelPublicId={null}
      isLoading={false}
      isError={false}
      disabled={false}
      onChange={onChange}
      onRetry={onRetry}
      {...overrides}
    />,
  );
  return { ...rendered, onChange, onRetry };
}

describe("ConversationModelSelector", () => {
  it("shows the default and safe provider labels", () => {
    renderSelector();

    expect(screen.getByRole("combobox", { name: "Model" })).toHaveValue(
      defaultModelId,
    );
    expect(
      screen.getByRole("option", { name: "GPT-5 · OpenAI — Default" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Claude Sonnet · Anthropic" }),
    ).toBeInTheDocument();
  });

  it("reports an explicit selection and clears it when returning to default", async () => {
    const user = userEvent.setup();
    const { onChange } = renderSelector();
    const select = screen.getByRole("combobox", { name: "Model" });

    await user.selectOptions(select, alternateModelId);
    await user.selectOptions(select, defaultModelId);

    expect(onChange).toHaveBeenNthCalledWith(1, alternateModelId);
    expect(onChange).toHaveBeenNthCalledWith(2, null);
  });

  it("requires a deliberate selection when there is no default", () => {
    renderSelector({ defaultModelPublicId: null });

    expect(screen.getByRole("combobox", { name: "Model" })).toHaveValue("");
    expect(
      screen.getByText("Select a model before sending a message."),
    ).toBeVisible();
  });

  it("shows loading, failure recovery, and empty states safely", async () => {
    const user = userEvent.setup();
    const { rerender } = renderSelector({ isLoading: true, models: [] });
    expect(screen.getByRole("status")).toHaveTextContent("Loading models…");
    expect(screen.getByRole("combobox")).toBeDisabled();

    const onRetry = vi.fn();
    rerender(
      <ConversationModelSelector
        models={[]}
        defaultModelPublicId={null}
        explicitModelPublicId={null}
        isLoading={false}
        isError
        disabled={false}
        onChange={vi.fn()}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Chat models are temporarily unavailable.",
    );
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();

    rerender(
      <ConversationModelSelector
        models={[]}
        defaultModelPublicId={null}
        explicitModelPublicId={null}
        isLoading={false}
        isError={false}
        disabled={false}
        onChange={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    expect(
      screen.getByText(
        "No chat model is available. Ask an administrator to configure one.",
      ),
    ).toBeVisible();
  });

  it("disables selection during an active operation", () => {
    renderSelector({ disabled: true });

    expect(screen.getByRole("combobox", { name: "Model" })).toBeDisabled();
  });
});
