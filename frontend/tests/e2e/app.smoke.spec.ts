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
    page.getByRole("heading", { name: "Organization settings" }),
  ).toBeVisible();
  await expect(page).toHaveURL(
    /\/settings\/ai-providers\?tab=profile#security$/,
  );

  await page.reload();

  await expect(
    page.getByRole("heading", { name: "Organization settings" }),
  ).toBeVisible();
  await expect(page).toHaveURL(
    /\/settings\/ai-providers\?tab=profile#security$/,
  );

  await page.getByRole("link", { name: "Files" }).click();
  await expect(
    page.getByRole("heading", { name: "Upload a file" }),
  ).toBeVisible();
  await expect(page.getByLabel("Choose a file")).toBeVisible();
  await expect(page.getByText("Maximum file size: 512 MB.")).toBeVisible();
});

test("configured models and defaults flow into the chat model selector", async ({
  page,
}) => {
  const providerPublicId = "11111111-1111-4111-8111-111111111111";
  const defaultModelPublicId = "22222222-2222-4222-8222-222222222222";
  const alternateModelPublicId = "33333333-3333-4333-8333-333333333333";

  await page.addInitScript(() => {
    window.sessionStorage.setItem(
      "nexus.authentication.refresh-token",
      "refresh-token",
    );
  });

  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());

    if (url.pathname.endsWith("/auth/refresh")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: "access-token",
          refresh_token: "refresh-token",
          token_type: "bearer",
          expires_in: 900,
        }),
      });
      return;
    }

    if (url.pathname.endsWith("/model-providers/capabilities")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ can_read: true, can_manage: true }),
      });
      return;
    }

    if (url.pathname.endsWith("/model-providers")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              public_id: providerPublicId,
              provider_type: "openai",
              display_name: "Production OpenAI",
              settings: {},
              enabled: true,
              credential_configured: true,
              validation_status: "valid",
              last_validated_at: "2026-09-30T00:00:00Z",
            },
          ],
        }),
      });
      return;
    }

    if (url.pathname.endsWith("/configured-models")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              public_id: defaultModelPublicId,
              provider_public_id: providerPublicId,
              provider_type: "openai",
              provider_model_name: "gpt-5",
              display_name: "GPT-5",
              model_type: "chat",
              capabilities: ["streaming"],
              embedding_dimension: null,
              enabled: true,
            },
            {
              public_id: alternateModelPublicId,
              provider_public_id: providerPublicId,
              provider_type: "openai",
              provider_model_name: "gpt-5-mini",
              display_name: "GPT-5 mini",
              model_type: "chat",
              capabilities: ["streaming"],
              embedding_dimension: null,
              enabled: true,
            },
          ],
        }),
      });
      return;
    }

    if (url.pathname.endsWith("/model-defaults")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          chat: defaultModelPublicId,
          embedding: null,
          reranker: null,
        }),
      });
      return;
    }

    if (url.pathname.endsWith("/chat-models")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              public_id: defaultModelPublicId,
              display_name: "GPT-5",
              provider_type: "openai",
              provider_display_name: "Production OpenAI",
            },
            {
              public_id: alternateModelPublicId,
              display_name: "GPT-5 mini",
              provider_type: "openai",
              provider_display_name: "Production OpenAI",
            },
          ],
          default_model_public_id: defaultModelPublicId,
        }),
      });
      return;
    }

    if (url.pathname.endsWith("/conversations")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ items: [] }),
      });
      return;
    }

    await route.fulfill({ status: 404, body: "{}" });
  });

  await page.goto("/settings/ai-models");

  await expect(page.getByRole("heading", { name: "AI Models" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Production OpenAI" }),
  ).toBeVisible();
  await expect(page.getByText("GPT-5", { exact: true })).toBeVisible();
  await expect(page.getByText("Default chat", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Conversations" }).click();
  await expect(page).toHaveURL(/\/conversations$/);

  const modelSelector = page.getByRole("combobox", {
    name: "Model",
    exact: true,
  });
  await expect(modelSelector).toHaveValue(defaultModelPublicId);
  await expect(
    modelSelector.locator("optgroup[label='Production OpenAI']"),
  ).toHaveCount(1);
  await modelSelector.selectOption(alternateModelPublicId);
  await expect(modelSelector).toHaveValue(alternateModelPublicId);
});
