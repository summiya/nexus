import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  clearModelDefault: vi.fn(),
  deleteConfiguredModel: vi.fn(),
  discoverProviderModels: vi.fn(),
  getModelDefaults: vi.fn(),
  listConfiguredModels: vi.fn(),
  registerModels: vi.fn(),
  setConfiguredModelEnabled: vi.fn(),
  setModelDefault: vi.fn(),
}));

vi.mock("./api", () => apiMocks);

import { conversationKeys } from "../conversations";
import {
  modelManagementKeys,
  useConfiguredModelsQuery,
  useDeleteConfiguredModelMutation,
  useProviderModelDiscoveryQuery,
  useRegisterModelsMutation,
  useSetConfiguredModelEnabledMutation,
  useSetModelDefaultMutation,
} from "./queries";

const providerId = "11111111-1111-4111-8111-111111111111";
const modelId = "22222222-2222-4222-8222-222222222222";
const providerRevision = "2026-09-30T00:00:00Z";

function createClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function wrapper(client: QueryClient) {
  return function TestProvider({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

describe("Model Management queries", () => {
  beforeEach(() => {
    Object.values(apiMocks).forEach((mock) => mock.mockReset());
  });

  it("defines stable keys and disables reads without permission", async () => {
    const client = createClient();
    const { result } = renderHook(() => useConfiguredModelsQuery(false), {
      wrapper: wrapper(client),
    });

    await waitFor(() => expect(result.current.fetchStatus).toBe("idle"));
    expect(apiMocks.listConfiguredModels).not.toHaveBeenCalled();
    expect(modelManagementKeys.all).toEqual(["model-management"]);
    expect(modelManagementKeys.configuredModels()).toEqual([
      "model-management",
      "configured-models",
    ]);
    expect(modelManagementKeys.defaults()).toEqual([
      "model-management",
      "defaults",
    ]);
    expect(modelManagementKeys.discoveryProvider(providerId)).toEqual([
      "model-management",
      "discovery",
      providerId,
    ]);
    expect(
      modelManagementKeys.discovery(providerId, providerRevision),
    ).toEqual([
      "model-management",
      "discovery",
      providerId,
      providerRevision,
    ]);
  });

  it("runs discovery only after an explicit refetch", async () => {
    apiMocks.discoverProviderModels.mockResolvedValue([]);
    const client = createClient();
    const { result } = renderHook(
      () => useProviderModelDiscoveryQuery(providerId, providerRevision),
      { wrapper: wrapper(client) },
    );

    expect(apiMocks.discoverProviderModels).not.toHaveBeenCalled();
    await act(async () => {
      await result.current.refetch();
    });
    expect(apiMocks.discoverProviderModels).toHaveBeenCalledWith(providerId);
  });

  it("does not reuse discovery data across provider validation revisions", () => {
    const client = createClient();
    client.setQueryData(
      modelManagementKeys.discovery(providerId, "2026-09-29T00:00:00Z"),
      [{ providerModelName: "stale-model" }],
    );

    const { result } = renderHook(
      () => useProviderModelDiscoveryQuery(providerId, providerRevision),
      { wrapper: wrapper(client) },
    );

    expect(result.current.data).toBeUndefined();
    expect(apiMocks.discoverProviderModels).not.toHaveBeenCalled();
  });

  it("invalidates registration data without globally clearing the cache", async () => {
    apiMocks.registerModels.mockResolvedValue([]);
    const client = createClient();
    const invalidate = vi
      .spyOn(client, "invalidateQueries")
      .mockResolvedValue();
    const clear = vi.spyOn(client, "clear");
    const { result } = renderHook(() => useRegisterModelsMutation(providerId), {
      wrapper: wrapper(client),
    });

    await act(async () => {
      await result.current.mutateAsync({
        registrationMode: "discovered",
        providerModelNames: ["gpt-5"],
      });
    });

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: modelManagementKeys.configuredModels(),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: modelManagementKeys.discoveryProvider(providerId),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: conversationKeys.chatModels(),
    });
    expect(clear).not.toHaveBeenCalled();
  });

  it("invalidates only configured and chat models after enablement", async () => {
    apiMocks.setConfiguredModelEnabled.mockResolvedValue({});
    const client = createClient();
    const invalidate = vi
      .spyOn(client, "invalidateQueries")
      .mockResolvedValue();
    const { result } = renderHook(
      () => useSetConfiguredModelEnabledMutation(),
      { wrapper: wrapper(client) },
    );

    await act(async () => {
      await result.current.mutateAsync({
        modelPublicId: modelId,
        enabled: true,
      });
    });

    expect(invalidate).toHaveBeenCalledTimes(2);
    expect(invalidate).not.toHaveBeenCalledWith({
      queryKey: modelManagementKeys.defaults(),
    });
  });

  it("invalidates models, defaults, and chat projection after deletion", async () => {
    apiMocks.deleteConfiguredModel.mockResolvedValue(undefined);
    const client = createClient();
    const invalidate = vi
      .spyOn(client, "invalidateQueries")
      .mockResolvedValue();
    const { result } = renderHook(() => useDeleteConfiguredModelMutation(), {
      wrapper: wrapper(client),
    });

    await act(async () => {
      await result.current.mutateAsync(modelId);
    });

    expect(invalidate).toHaveBeenCalledTimes(3);
  });

  it("invalidates chat projection only for the chat default", async () => {
    apiMocks.setModelDefault.mockResolvedValue({});
    const client = createClient();
    const invalidate = vi
      .spyOn(client, "invalidateQueries")
      .mockResolvedValue();
    const { result } = renderHook(() => useSetModelDefaultMutation(), {
      wrapper: wrapper(client),
    });

    await act(async () => {
      await result.current.mutateAsync({
        modelType: "embedding",
        modelPublicId: modelId,
      });
    });
    expect(invalidate).toHaveBeenCalledTimes(1);

    invalidate.mockClear();
    await act(async () => {
      await result.current.mutateAsync({
        modelType: "chat",
        modelPublicId: modelId,
      });
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: conversationKeys.chatModels(),
    });
  });
});
