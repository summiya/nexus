import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";

import { AppLayout } from "../components/AppLayout";
import { AuthGate, LoginPage } from "../features/auth";
import { AIModelsSettings } from "../features/model-management";
import { AIProvidersSettings } from "../features/model-providers";
import { ConversationPage } from "../pages/ConversationPage";
import { FilesPage } from "../pages/FilesPage";
import { SettingsPage } from "../pages/SettingsPage";

function SettingsIndexRedirect() {
  const location = useLocation();

  return (
    <Navigate
      to={{
        pathname: "/settings/ai-providers",
        search: location.search,
        hash: location.hash,
      }}
      replace
    />
  );
}

export function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<AuthGate />}>
          <Route element={<AppLayout />}>
            <Route
              path="/"
              element={<Navigate to="/conversations" replace />}
            />
            <Route path="/conversations" element={<ConversationPage />} />
            <Route
              path="/conversations/:conversationId"
              element={<ConversationPage />}
            />
            <Route path="/files" element={<FilesPage />} />
            <Route path="/settings" element={<SettingsPage />}>
              <Route index element={<SettingsIndexRedirect />} />
              <Route path="ai-providers" element={<AIProvidersSettings />} />
              <Route path="ai-models" element={<AIModelsSettings />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/conversations" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
