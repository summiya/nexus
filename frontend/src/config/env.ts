interface FrontendEnv {
  appName: string;
  appEnv: string;
  apiBaseUrl: string;
}

function requireEnv(value: string | undefined, name: string): string {
  if (!value) {
    throw new Error(`Missing required frontend environment variable: ${name}`);
  }

  return value;
}

export const env: FrontendEnv = {
  appName: import.meta.env.VITE_APP_NAME ?? "NEXUS",
  appEnv: import.meta.env.VITE_APP_ENV ?? "development",
  apiBaseUrl: requireEnv(
    import.meta.env.VITE_API_BASE_URL,
    "VITE_API_BASE_URL",
  ),
};
