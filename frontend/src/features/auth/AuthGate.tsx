import { Navigate, Outlet, useLocation } from "react-router-dom";

import { AuthStatusView } from "./AuthStatusView";
import { useAuthStore } from "./store";

function currentInternalLocation(location: {
  pathname: string;
  search: string;
  hash: string;
}): string {
  return `${location.pathname}${location.search}${location.hash}`;
}

export function AuthGate() {
  const status = useAuthStore((state) => state.status);
  const location = useLocation();

  if (status === "initializing" || status === "unavailable") {
    return <AuthStatusView status={status} />;
  }

  if (status === "unauthenticated") {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: currentInternalLocation(location) }}
      />
    );
  }

  return <Outlet />;
}
