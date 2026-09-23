interface FrontendEnv {
  appName: string;
  appEnv: string;
  apiBaseUrl: string;
  conversationModel: string;
}

function requireEnv(value: string | undefined, name: string): string {
  const normalized = value?.trim();
  if (!normalized) {
    throw new Error(`Missing required frontend environment variable: ${name}`);
  }

  return normalized;
}

export const env: FrontendEnv = {
  appName: import.meta.env.VITE_APP_NAME ?? "NEXUS",
  appEnv: import.meta.env.VITE_APP_ENV ?? "development",
  apiBaseUrl: requireEnv(
    import.meta.env.VITE_API_BASE_URL,
    "VITE_API_BASE_URL",
  ),
  conversationModel: requireEnv(
    import.meta.env.VITE_CONVERSATION_MODEL,
    "VITE_CONVERSATION_MODEL",
  ),
};
