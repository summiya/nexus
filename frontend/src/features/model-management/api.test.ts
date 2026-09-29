import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearModelDefault,
  deleteConfiguredModel,
  discoverProviderModels,
  getModelDefaults,
  listConfiguredModels,
  registerModels,
  setConfiguredModelEnabled,
  setModelDefault,
} from "./api";

const providerId = "11111111-1111-4111-8111-111111111111";
const modelId = "22222222-2222-4222-8222-222222222222";
const embeddingId = "33333333-3333-4333-8333-333333333333";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function configuredModel(overrides: Record<string, unknown> = {}) {
  return {
    public_id: modelId,
    provider_public_id: providerId,
    provider_type: "openai",
    provider_model_name: "gpt-5",
    display_name: "GPT-5",
    model_type: "chat",
    capabilities: ["streaming", "tools"],
    embedding_dimension: null,
    enabled: true,
    ...overrides,
  };
}

describe("Model Management API", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch");
  });

  it("strictly parses configured models and preserves provider identity", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      jsonResponse({
        items: [
          configuredModel(),
          configuredModel({
            public_id: embeddingId,
            provider_public_id: "44444444-4444-4444-8444-444444444444",
            provider_type: "gemini",
            provider_model_name: "gemini-embedding-001",
            display_name: "Gemini Embedding",
            model_type: "embedding",
            capabilities: [],
            embedding_dimension: 3072,
          }),
          configuredModel({
            public_id: "55555555-5555-4555-8555-555555555555",
            provider_type: "openai_compatible",
            provider_model_name: "rerank-v1",
            display_name: "Reranker",
            model_type: "reranker",
            capabilities: [],
          }),
        ],
      }),
    );

    await expect(listConfiguredModels()).resolves.toEqual([
      expect.objectContaining({
        publicId: modelId,
        providerPublicId: providerId,
        modelType: "chat",
        capabilities: ["streaming", "tools"],
      }),
      expect.objectContaining({
        publicId: embeddingId,
        providerType: "gemini",
        modelType: "embedding",
        embeddingDimension: 3072,
      }),
      expect.objectContaining({ modelType: "reranker" }),
    ]);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/configured-models",
      expect.any(Object),
    );
  });

  it("parses discovery candidates including an unknown embedding dimension", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      jsonResponse({
        items: [
          {
            provider_model_name: "gpt-5-mini",
            display_name: "GPT-5 Mini",
            model_type: "chat",
            capabilities: ["streaming", "vision"],
            embedding_dimension: null,
          },
          {
            provider_model_name: "embedding-new",
            display_name: "Embedding New",
            model_type: "embedding",
            capabilities: [],
            embedding_dimension: null,
          },
        ],
      }),
    );

    await expect(discoverProviderModels(providerId)).resolves.toEqual([
      expect.objectContaining({
        providerModelName: "gpt-5-mini",
        capabilities: ["streaming", "vision"],
      }),
      expect.objectContaining({
        modelType: "embedding",
        embeddingDimension: null,
      }),
    ]);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      `http://localhost:8000/api/v1/model-providers/${providerId}/models`,
      expect.any(Object),
    );
  });

  it("sends discovered batch registration in request order", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      jsonResponse({ items: [configuredModel()] }, 201),
    );

    await registerModels(providerId, {
      registrationMode: "discovered",
      providerModelNames: ["gpt-5", "gpt-5-mini"],
    });

    const request = vi.mocked(globalThis.fetch).mock.calls[0][1];
    expect(request?.method).toBe("POST");
    expect(JSON.parse(request?.body as string)).toEqual({
      registration_mode: "discovered",
      provider_model_names: ["gpt-5", "gpt-5-mini"],
    });
  });

  it("maps manual registration without inventing metadata", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      jsonResponse({
        items: [
          configuredModel({
            provider_type: "azure_openai",
            provider_model_name: "chat-production",
            display_name: "Production Chat",
            capabilities: ["streaming", "structured_output"],
          }),
        ],
      }),
    );

    await registerModels(providerId, {
      registrationMode: "manual",
      providerModelName: "chat-production",
      displayName: "Production Chat",
      modelType: "chat",
      capabilities: ["streaming", "structured_output"],
      embeddingDimension: null,
    });

    const request = vi.mocked(globalThis.fetch).mock.calls[0][1];
    expect(JSON.parse(request?.body as string)).toEqual({
      registration_mode: "manual",
      provider_model_name: "chat-production",
      display_name: "Production Chat",
      model_type: "chat",
      capabilities: ["streaming", "structured_output"],
      embedding_dimension: null,
    });
  });

  it("enables, disables, and deletes a configured model", async () => {
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(jsonResponse(configuredModel()))
      .mockResolvedValueOnce(jsonResponse(configuredModel({ enabled: false })))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(
      setConfiguredModelEnabled(modelId, true),
    ).resolves.toMatchObject({ enabled: true });
    await expect(
      setConfiguredModelEnabled(modelId, false),
    ).resolves.toMatchObject({ enabled: false });
    await expect(deleteConfiguredModel(modelId)).resolves.toBeUndefined();

    const calls = vi.mocked(globalThis.fetch).mock.calls;
    expect(calls.map(([, request]) => request?.method)).toEqual([
      "PATCH",
      "PATCH",
      "DELETE",
    ]);
    expect(JSON.parse(calls[0][1]?.body as string)).toEqual({ enabled: true });
    expect(JSON.parse(calls[1][1]?.body as string)).toEqual({ enabled: false });
  });

  it("gets, sets every type, and clears defaults", async () => {
    const defaults = { chat: modelId, embedding: null, reranker: null };
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(jsonResponse(defaults))
      .mockResolvedValueOnce(jsonResponse(defaults))
      .mockResolvedValueOnce(
        jsonResponse({ ...defaults, embedding: embeddingId }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ ...defaults, reranker: embeddingId }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(getModelDefaults()).resolves.toEqual(defaults);
    await setModelDefault("chat", modelId);
    await setModelDefault("embedding", embeddingId);
    await setModelDefault("reranker", embeddingId);
    await expect(clearModelDefault("chat")).resolves.toBeUndefined();

    const calls = vi.mocked(globalThis.fetch).mock.calls;
    expect(calls.slice(1, 4).map(([url]) => url.toString())).toEqual([
      "http://localhost:8000/api/v1/model-defaults/chat",
      "http://localhost:8000/api/v1/model-defaults/embedding",
      "http://localhost:8000/api/v1/model-defaults/reranker",
    ]);
  });

  it("rejects unexpected successful delete and clear statuses", async () => {
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(jsonResponse({}, 200))
      .mockResolvedValueOnce(jsonResponse({}, 200));

    await expect(deleteConfiguredModel(modelId)).rejects.toThrow(
      "The Model Management service returned an invalid response.",
    );
    await expect(clearModelDefault("chat")).rejects.toThrow(
      "The Model Management service returned an invalid response.",
    );
  });

  it.each([
    configuredModel({ embedding_dimension: 3 }),
    configuredModel({
      model_type: "embedding",
      capabilities: [],
      embedding_dimension: null,
    }),
    configuredModel({
      model_type: "reranker",
      capabilities: ["streaming"],
    }),
    configuredModel({ capabilities: ["streaming", "streaming"] }),
    configuredModel({ provider_type: "unknown" }),
  ])("rejects malformed configured-model responses safely", async (item) => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      jsonResponse({ items: [item] }),
    );

    await expect(listConfiguredModels()).rejects.toThrow(
      "The Model Management service returned an invalid response.",
    );
  });

  it("rejects malformed discovery and defaults responses safely", async () => {
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(
        jsonResponse({
          items: [
            {
              provider_model_name: "rerank",
              display_name: "Rerank",
              model_type: "reranker",
              capabilities: [],
              embedding_dimension: 12,
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ chat: "not-a-uuid", embedding: null, reranker: null }),
      );

    await expect(discoverProviderModels(providerId)).rejects.toThrow(
      "The Model Management service returned an invalid response.",
    );
    await expect(getModelDefaults()).rejects.toThrow(
      "The Model Management service returned an invalid response.",
    );
  });
});
