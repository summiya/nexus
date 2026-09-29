import {
  type QueryClient,
  useQueryClient,
} from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../features/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../features/auth")>();
  return {
    ...actual,
    initializeSession: vi.fn().mockResolvedValue("authenticated"),
  };
});

import { setAuthStatus } from "../features/auth/store";
import { AppProviders } from "./providers";

let capturedQueryClient: QueryClient | null = null;

function QueryClientProbe() {
  capturedQueryClient = useQueryClient();
  return null;
}

describe("AppProviders authenticated query cache", () => {
  beforeEach(() => {
    capturedQueryClient = null;
    setAuthStatus("authenticated");
  });

  it(
    "clears tenant-scoped cached data before another authenticated session can reuse it",
    async () => {
      render(
        <AppProviders>
          <QueryClientProbe />
        </AppProviders>,
      );

      await waitFor(() => expect(capturedQueryClient).not.toBeNull());
      const queryClient = capturedQueryClient;
      if (queryClient === null) {
        throw new Error("QueryClient was not mounted.");
      }

      const chatModelsKey = ["conversations", "chat-models"] as const;
      act(() => {
        queryClient.setQueryData(chatModelsKey, {
          items: [
            { publicId: "org-a-model", displayName: "Org A private model" },
          ],
        });
      });
      expect(queryClient.getQueryData(chatModelsKey)).toBeDefined();

      act(() => {
        setAuthStatus("unauthenticated");
      });

      await waitFor(() =>
        expect(queryClient.getQueryData(chatModelsKey)).toBeUndefined(),
      );

      act(() => {
        setAuthStatus("authenticated");
      });

      expect(queryClient.getQueryData(chatModelsKey)).toBeUndefined();
    },
  );
});
