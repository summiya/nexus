export type AuthStatus =
  "initializing" | "authenticated" | "unauthenticated" | "unavailable";

export interface SessionTokens {
  accessToken: string;
  refreshToken: string;
  tokenType: "bearer";
  expiresIn: number;
}
