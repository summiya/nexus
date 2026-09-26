import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  requestFileDownload: vi.fn(),
}));

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    requestFileDownload: apiMocks.requestFileDownload,
  };
});

import { FileDownloadButton } from "./FileDownloadButton";

const URL = "https://storage.example/file?sig=SENSITIVE";

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("FileDownloadButton", () => {
  beforeEach(() => {
    apiMocks.requestFileDownload.mockReset();
  });

  it("requests a grant then navigates with a temporary body-attached anchor", async () => {
    const user = userEvent.setup();
    apiMocks.requestFileDownload.mockResolvedValue({
      url: URL,
      expiresAt: "2026-09-26T15:05:00Z",
    });
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        expect(document.body.contains(this)).toBe(true);
        expect(this.href).toBe(URL);
      });

    render(
      <FileDownloadButton filePublicId="11111111-1111-4111-8111-111111111111" />,
    );

    await user.click(screen.getByRole("button", { name: "Download" }));

    expect(apiMocks.requestFileDownload).toHaveBeenCalledWith(
      "11111111-1111-4111-8111-111111111111",
    );
    expect(clickSpy).toHaveBeenCalledOnce();
    expect(document.querySelector(`a[href="${URL}"]`)).toBeNull();
    expect(screen.queryByText(URL)).not.toBeInTheDocument();
  });

  it("shows a busy state and prevents duplicate requests", async () => {
    const user = userEvent.setup();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      () => undefined,
    );
    const grant = deferred<{ url: string; expiresAt: string }>();
    apiMocks.requestFileDownload.mockReturnValue(grant.promise);

    render(
      <FileDownloadButton filePublicId="11111111-1111-4111-8111-111111111111" />,
    );

    await user.click(screen.getByRole("button", { name: "Download" }));

    const button = screen.getByRole("button", { name: "Preparing…" });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(apiMocks.requestFileDownload).toHaveBeenCalledOnce();

    grant.resolve({
      url: URL,
      expiresAt: "2026-09-26T15:05:00Z",
    });
    expect(
      await screen.findByRole("button", { name: "Download" }),
    ).toBeEnabled();
  });

  it("shows a safe error without rendering provider details", async () => {
    const user = userEvent.setup();
    apiMocks.requestFileDownload.mockRejectedValue(
      new Error(`provider failed ${URL}`),
    );

    render(
      <FileDownloadButton filePublicId="11111111-1111-4111-8111-111111111111" />,
    );

    await user.click(screen.getByRole("button", { name: "Download" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Download could not be started. Try again.",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent("SENSITIVE");
    expect(screen.queryByText(URL)).not.toBeInTheDocument();
  });
});
