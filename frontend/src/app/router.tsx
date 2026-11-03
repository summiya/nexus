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
import { AccountSettingsSection } from "../pages/AccountSettingsSection";
import {
  WorkspaceConceptPage,
  WorkspaceOverviewPage,
} from "../pages/WorkspaceDashboardPages";
import { HomePage } from "../pages/HomePage";
import { FilesPage } from "../pages/FilesPage";
import { SettingsPage } from "../pages/SettingsPage";

function SettingsIndexRedirect() {
  const location = useLocation();

  return (
    <Navigate
      to={{
        pathname: "/settings/profile",
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
        <Route path="/" element={<HomePage />} />
        <Route path="/explore" element={<HomePage showForAuthenticated />} />
        <Route path="/login" element={<LoginPage />} />
        <Route element={<AuthGate />}>
          <Route element={<AppLayout />}>
            <Route path="/workspace" element={<WorkspaceOverviewPage />} />
            <Route
              path="/projects"
              element={<WorkspaceConceptPage section="projects" />}
            />
            <Route
              path="/knowledge-bases"
              element={<WorkspaceConceptPage section="knowledge-bases" />}
            />
            <Route
              path="/artifacts"
              element={<WorkspaceConceptPage section="artifacts" />}
            />
            <Route
              path="/agents"
              element={<WorkspaceConceptPage section="agents" />}
            />
            <Route
              path="/tools"
              element={<WorkspaceConceptPage section="tools" />}
            />
            <Route
              path="/incidents"
              element={<WorkspaceConceptPage section="incidents" />}
            />
            <Route path="/conversations" element={<ConversationPage />} />
            <Route
              path="/conversations/:conversationId"
              element={<ConversationPage />}
            />
            <Route path="/files" element={<FilesPage />} />
            <Route path="/settings" element={<SettingsPage />}>
              <Route index element={<SettingsIndexRedirect />} />
              <Route
                path="profile"
                element={<AccountSettingsSection section="profile" />}
              />
              <Route
                path="preferences"
                element={<AccountSettingsSection section="preferences" />}
              />
              <Route
                path="usage"
                element={<AccountSettingsSection section="usage" />}
              />
              <Route
                path="security"
                element={<AccountSettingsSection section="security" />}
              />
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
