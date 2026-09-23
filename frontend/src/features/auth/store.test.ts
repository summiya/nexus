import { beforeEach, describe, expect, it } from "vitest";

import { setAuthStatus, useAuthStore } from "./store";

describe("authentication store", () => {
  beforeEach(() => {
    setAuthStatus("initializing");
  });

  it("contains only the React-visible authentication status", () => {
    expect(useAuthStore.getState()).toEqual({ status: "initializing" });

    setAuthStatus("authenticated");

    expect(useAuthStore.getState()).toEqual({ status: "authenticated" });

    setAuthStatus("unavailable");

    expect(useAuthStore.getState()).toEqual({ status: "unavailable" });
  });
});
