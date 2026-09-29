import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  createProvider: vi.fn(),
  deleteProvider: vi.fn(),
  getModelProviderCapabilities: vi.fn(),
  listConfiguredProviders: vi.fn(),
  listProviderCatalog: vi.fn(),
  setProviderEnabled: vi.fn(),
  updateProvider: vi.fn(),
  validateProvider: vi.fn(),
}));

vi.mock("./api", () => apiMocks);

import {
  modelProviderKeys,
  useCreateProviderMutation,
  useModelProviderCapabilitiesQuery,
  useProviderCatalogQuery,
} from "./queries";

function createClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function wrapper(client: QueryClient) {
  return function Provider({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

describe("Model Provider queries", () => {
  beforeEach(() => {
    Object.values(apiMocks).forEach((mock) => mock.mockReset());
  });

  it("defines stable keys and wires capabilities", async () => {
    apiMocks.getModelProviderCapabilities.mockResolvedValue({
      canRead: true,
      canManage: false,
    });
    const client = createClient();
    const { result } = renderHook(() => useModelProviderCapabilitiesQuery(), {
      wrapper: wrapper(client),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(modelProviderKeys.all).toEqual(["model-providers"]);
    expect(modelProviderKeys.capabilities()).toEqual([
      "model-providers",
      "capabilities",
    ]);
    expect(modelProviderKeys.catalog()).toEqual(["model-providers", "catalog"]);
    expect(modelProviderKeys.list()).toEqual(["model-providers", "list"]);
  });

  it("does not fetch the catalog without read capability", async () => {
    const client = createClient();
    const { result } = renderHook(() => useProviderCatalogQuery(false), {
      wrapper: wrapper(client),
    });

    await waitFor(() => expect(result.current.fetchStatus).toBe("idle"));

    expect(apiMocks.listProviderCatalog).not.toHaveBeenCalled();
  });

  it("invalidates only the configured-provider list after create", async () => {
    apiMocks.createProvider.mockResolvedValue({ publicId: "provider-id" });
    const client = createClient();
    const invalidate = vi
      .spyOn(client, "invalidateQueries")
      .mockResolvedValue();
    const { result } = renderHook(() => useCreateProviderMutation(), {
      wrapper: wrapper(client),
    });

    await act(async () => {
      await result.current.mutateAsync({
        providerType: "openai",
        displayName: "OpenAI",
        settings: {},
      });
    });

    expect(invalidate).toHaveBeenCalledOnce();
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: modelProviderKeys.list(),
    });
    expect(invalidate).not.toHaveBeenCalledWith({
      queryKey: modelProviderKeys.catalog(),
    });
  });
});
