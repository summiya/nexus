import { expect, test } from "@playwright/test";

test("login restores the intended protected route and survives reload", async ({
  page,
}) => {
  await page.route("**/api/v1/auth/**", async (route) => {
    const url = new URL(route.request().url());
    const body = route.request().postDataJSON() as Record<string, unknown>;

    if (url.pathname.endsWith("/auth/login/verify")) {
      expect(body).toEqual({
        email: "person@example.com",
        otp: "123456",
      });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "completed",
          access_token: "access-token",
          refresh_token: "refresh-token",
          token_type: "bearer",
          expires_in: 900,
        }),
      });
      return;
    }

    if (url.pathname.endsWith("/auth/login")) {
      expect(body).toEqual({ email: "person@example.com" });
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: '{"status":"accepted"}',
      });
      return;
    }

    expect(url.pathname).toContain("/auth/refresh");
    expect(body).toEqual({ refresh_token: "refresh-token" });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "restored-access-token",
        refresh_token: "restored-refresh-token",
        token_type: "bearer",
        expires_in: 900,
      }),
    });
  });

  await page.goto("/settings?tab=profile#security");

  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page
    .getByRole("textbox", { name: "Email address" })
    .fill("person@example.com");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(
    page.getByText(
      "If an account exists for this email, a verification code has been sent.",
    ),
  ).toBeVisible();
  await page.getByRole("textbox", { name: "Verification code" }).fill("123456");
  await page.getByRole("button", { name: "Verify" }).click();

  await expect(
    page.getByRole("heading", { name: "Foundation configuration" }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/settings\?tab=profile#security$/);

  await page.reload();

  await expect(
    page.getByRole("heading", { name: "Foundation configuration" }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/settings\?tab=profile#security$/);

  await page.getByRole("link", { name: "Files" }).click();
  await expect(
    page.getByRole("heading", { name: "Upload a file" }),
  ).toBeVisible();
  await expect(page.getByLabel("Choose a file")).toBeVisible();
  await expect(page.getByText("Maximum file size: 512 MB.")).toBeVisible();
});
