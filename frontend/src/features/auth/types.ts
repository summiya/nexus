export type AuthStatus = "initializing" | "authenticated" | "unauthenticated";

export interface SessionTokens {
  accessToken: string;
  refreshToken: string;
  tokenType: "bearer";
  expiresIn: number;
}
