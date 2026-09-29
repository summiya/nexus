import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createProvider,
  deleteProvider,
  getModelProviderCapabilities,
  listConfiguredProviders,
  listProviderCatalog,
  setProviderCredential,
  setProviderEnabled,
  updateProvider,
  validateProvider,
} from "./api";

const providerId = "11111111-1111-4111-8111-111111111111";
const checkedAt = "2026-09-29T23:14:00+04:00";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function configuredProvider(overrides: Record<string, unknown> = {}) {
  return {
    public_id: providerId,
    provider_type: "azure_openai",
    display_name: "Azure production",
    settings: {
      endpoint: "https://example.openai.azure.com",
      api_version: "2026-01-01",
    },
    enabled: false,
    credential_configured: true,
    validation_status: "valid",
    last_validated_at: checkedAt,
    ...overrides,
  };
}

describe("Model Provider API", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch");
  });

  it("maps the focused capability projection", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      jsonResponse({ can_read: true, can_manage: false }),
    );

    await expect(getModelProviderCapabilities()).resolves.toEqual({
      canRead: true,
      canManage: false,
    });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/model-providers/capabilities",
      expect.any(Object),
    );
  });

  it("maps catalog-driven setting requirements", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      jsonResponse({
        items: [
          {
            provider_type: "azure_openai",
            display_name: "Azure OpenAI",
            required_settings: ["endpoint", "api_version"],
          },
          {
            provider_type: "openai_compatible",
            display_name: "OpenAI-compatible",
            required_settings: ["base_url"],
          },
        ],
      }),
    );

    await expect(listProviderCatalog()).resolves.toEqual([
      {
        providerType: "azure_openai",
        displayName: "Azure OpenAI",
        requiredSettings: ["endpoint", "api_version"],
      },
      {
        providerType: "openai_compatible",
        displayName: "OpenAI-compatible",
        requiredSettings: ["base_url"],
      },
    ]);
  });

  it("preserves multiple configured instances of one provider type", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      jsonResponse({
        items: [
          configuredProvider(),
          configuredProvider({
            public_id: "22222222-2222-4222-8222-222222222222",
            display_name: "Azure research",
          }),
        ],
      }),
    );

    const result = await listConfiguredProviders();

    expect(result).toHaveLength(2);
    expect(result.map((provider) => provider.displayName)).toEqual([
      "Azure production",
      "Azure research",
    ]);
    expect(result[0]).toMatchObject({
      publicId: providerId,
      providerType: "azure_openai",
      credentialConfigured: true,
      validationStatus: "valid",
      lastValidatedAt: checkedAt,
    });
  });

  it("creates providers disabled regardless of form input concerns", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      jsonResponse(configuredProvider(), 201),
    );

    await createProvider({
      providerType: "azure_openai",
      displayName: "Azure production",
      settings: {
        endpoint: "https://example.openai.azure.com",
        api_version: "2026-01-01",
      },
    });

    const request = vi.mocked(globalThis.fetch).mock.calls[0][1];
    expect(request?.method).toBe("POST");
    expect(JSON.parse(request?.body as string)).toEqual({
      provider_type: "azure_openai",
      display_name: "Azure production",
      settings: {
        endpoint: "https://example.openai.azure.com",
        api_version: "2026-01-01",
      },
      enabled: false,
    });
  });

  it("sends only fields supplied to a partial update", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      jsonResponse(configuredProvider()),
    );

    await updateProvider(providerId, { displayName: "Renamed" });

    const request = vi.mocked(globalThis.fetch).mock.calls[0][1];
    expect(request?.method).toBe("PUT");
    expect(JSON.parse(request?.body as string)).toEqual({
      display_name: "Renamed",
    });
  });

  it("writes a credential without returning or retaining its value", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      jsonResponse({ credential_configured: true }),
    );

    await setProviderCredential(providerId, "distinctive-secret");

    const [url, request] = vi.mocked(globalThis.fetch).mock.calls[0];
    expect(url.toString()).toContain(`/${providerId}/credential`);
    expect(JSON.parse(request?.body as string)).toEqual({
      credential: "distinctive-secret",
    });
  });

  it("maps validation, enabled, and delete operations", async () => {
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(
        jsonResponse({
          status: "invalid_credentials",
          last_validated_at: checkedAt,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse(configuredProvider({ enabled: true })),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(validateProvider(providerId)).resolves.toEqual({
      status: "invalid_credentials",
      lastValidatedAt: checkedAt,
    });
    await expect(setProviderEnabled(providerId, true)).resolves.toMatchObject({
      enabled: true,
    });
    await expect(deleteProvider(providerId)).resolves.toBeUndefined();
    expect(
      vi
        .mocked(globalThis.fetch)
        .mock.calls.map(([, request]) => request?.method),
    ).toEqual(["POST", "PATCH", "DELETE"]);
  });

  it.each([
    { can_read: true, can_manage: false, role: "Administrator" },
    {
      items: [
        {
          provider_type: "azure_openai",
          display_name: "Azure",
          required_settings: ["unknown"],
        },
      ],
    },
    { items: [configuredProvider({ credential_reference: "must-not-leak" })] },
  ])(
    "rejects malformed successful responses without leaking them",
    async (payload) => {
      vi.mocked(globalThis.fetch).mockResolvedValue(jsonResponse(payload));

      const operation =
        "can_read" in payload
          ? getModelProviderCapabilities()
          : "credential_reference" in ((payload.items as object[])[0] ?? {})
            ? listConfiguredProviders()
            : listProviderCatalog();

      await expect(operation).rejects.toThrow(
        "The Model Provider service returned an invalid response.",
      );
      await expect(operation).rejects.not.toThrow("must-not-leak");
    },
  );
});
