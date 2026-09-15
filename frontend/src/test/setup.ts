import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

vi.stubEnv("VITE_API_BASE_URL", "http://localhost:8000/api/v1");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
