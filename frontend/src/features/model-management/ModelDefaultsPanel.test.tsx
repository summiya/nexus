import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  clearModelDefault: vi.fn(),
  setModelDefault: vi.fn(),
}));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  ...apiMocks,
}));

import { ModelDefaultsPanel } from "./ModelDefaultsPanel";
import type { ConfiguredModel } from "./types";
import type { ConfiguredProvider } from "../model-providers";

const readyProvider: ConfiguredProvider = {
  publicId: "11111111-1111-4111-8111-111111111111",
  providerType: "openai",
  displayName: "OpenAI production",
  settings: {},
  enabled: true,
  credentialConfigured: true,
  validationStatus: "valid",
  lastValidatedAt: "2026-09-30T00:00:00Z",
};
const unreadyProvider: ConfiguredProvider = {
  ...readyProvider,
  publicId: "22222222-2222-4222-8222-222222222222",
  displayName: "OpenAI unready",
  validationStatus: "unvalidated",
  lastValidatedAt: null,
};

function model(
  publicId: string,
  providerPublicId: string,
  displayName: string,
  streaming = true,
): ConfiguredModel {
  return {
    publicId,
    providerPublicId,
    providerType: "openai",
    providerModelName: displayName.toLowerCase(),
    displayName,
    modelType: "chat",
    capabilities: streaming ? ["streaming"] : ["tools"],
    embeddingDimension: null,
    enabled: true,
  };
}

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ModelDefaultsPanel
        defaults={{ chat: null, embedding: null, reranker: null }}
        providers={[readyProvider, unreadyProvider]}
        models={[
          model(
            "33333333-3333-4333-8333-333333333333",
            readyProvider.publicId,
            "Ready Chat",
          ),
          model(
            "44444444-4444-4444-8444-444444444444",
            unreadyProvider.publicId,
            "Unready Chat",
          ),
          model(
            "55555555-5555-4555-8555-555555555555",
            readyProvider.publicId,
            "No Stream",
            false,
          ),
        ]}
        canManage
      />
    </QueryClientProvider>,
  );
}

describe("ModelDefaultsPanel", () => {
  beforeEach(() => {
    apiMocks.setModelDefault.mockReset();
    apiMocks.clearModelDefault.mockReset();
    apiMocks.setModelDefault.mockResolvedValue({});
    apiMocks.clearModelDefault.mockResolvedValue(undefined);
  });

  it("offers only ready streaming chat models", () => {
    renderPanel();

    const chat = screen.getByRole("combobox", { name: "Default Chat Model" });
    expect(
      within(chat).getByRole("option", { name: /Ready Chat/ }),
    ).toBeInTheDocument();
    expect(
      within(chat).queryByRole("option", { name: /Unready Chat/ }),
    ).not.toBeInTheDocument();
    expect(
      within(chat).queryByRole("option", { name: /No Stream/ }),
    ).not.toBeInTheDocument();
  });

  it("sets and clears an organization default", async () => {
    const user = userEvent.setup();
    renderPanel();
    const chat = screen.getByRole("combobox", { name: "Default Chat Model" });

    await user.selectOptions(chat, "33333333-3333-4333-8333-333333333333");
    expect(apiMocks.setModelDefault).toHaveBeenCalledWith(
      "chat",
      "33333333-3333-4333-8333-333333333333",
    );
    await user.selectOptions(chat, "");
    expect(apiMocks.clearModelDefault).toHaveBeenCalledWith("chat");
  });
});
