import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { DashboardIcon } from "../components/dashboard/DashboardIcon";

type AccountSection = "profile" | "preferences" | "usage" | "security";

export function AccountSettingsSection({
  section,
}: {
  section: AccountSection;
}) {
  const [displayName, setDisplayName] = useState("");
  const [draftSaved, setDraftSaved] = useState(false);
  const [density, setDensity] = useState<"comfortable" | "compact">(
    "comfortable",
  );
  const [motion, setMotion] = useState(true);

  function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setDraftSaved(true);
  }

  if (section === "profile") {
    return (
      <div className="nx-account-section">
        <header className="settings-section-heading">
          <p className="eyebrow">ACCOUNT</p>
          <h2>Profile</h2>
          <p>Manage how you appear in your NEXUS workspace.</p>
        </header>
        <section className="nx-account-card">
          <div className="nx-account-card-heading">
            <span className="nx-account-card-icon">
              <DashboardIcon name="profile" size={21} />
            </span>
            <div>
              <h3>Personal information</h3>
              <p>Profile details for your workspace identity.</p>
            </div>
          </div>
          <div className="nx-profile-identity">
            <span
              className="nx-profile-large-avatar"
              aria-label="Example profile initial"
            >
              S
            </span>
            <span>
              <strong>{displayName.trim() || "Your profile"}</strong>
              <small>
                The S avatar is an interface placeholder until profile identity
                is connected.
              </small>
            </span>
          </div>
          <form className="nx-profile-form" onSubmit={saveProfile}>
            <div>
              <label htmlFor="nx-profile-name">Display name</label>
              <input
                id="nx-profile-name"
                value={displayName}
                onChange={(event) => {
                  setDisplayName(event.target.value);
                  setDraftSaved(false);
                }}
                placeholder="Enter a display name"
                maxLength={80}
              />
              <small>
                Changes here are a local design preview and are not saved to
                your account.
              </small>
            </div>
            <button className="nx-ui-button nx-ui-button-primary" type="submit">
              Save preview
            </button>
            {draftSaved ? (
              <p className="nx-ui-notice" role="status">
                Profile preview updated on this page only.
              </p>
            ) : null}
          </form>
        </section>
        <section className="nx-account-card nx-account-card-inline">
          <DashboardIcon name="security" size={22} />
          <div>
            <h3>Sign-in & identity</h3>
            <p>
              NEXUS currently uses email one-time-code sign-in. Your real
              identity comes from the authenticated session, not this sample
              form.
            </p>
          </div>
        </section>
      </div>
    );
  }

  if (section === "preferences") {
    return (
      <div className="nx-account-section">
        <header className="settings-section-heading">
          <p className="eyebrow">PERSONALIZATION</p>
          <h2>Preferences</h2>
          <p>Explore appearance and experience options for your workspace.</p>
        </header>
        <section className="nx-account-card">
          <div className="nx-account-card-heading">
            <span className="nx-account-card-icon">
              <DashboardIcon name="preferences" size={22} />
            </span>
            <div>
              <h3>Appearance</h3>
              <p>See how settings could shape your experience.</p>
            </div>
          </div>
          <div className="nx-preference-row">
            <span>
              <strong>Theme</strong>
              <small>Light workspace with a dark navigation sidebar</small>
            </span>
            <div className="nx-preference-theme">
              <span aria-hidden="true">◐</span> Light{" "}
              <DashboardIcon name="check" size={15} />
            </div>
          </div>
          <div className="nx-preference-row">
            <span>
              <strong>Display density</strong>
              <small>Change the spacing of the example below</small>
            </span>
            <div
              className="nx-preference-choice"
              role="group"
              aria-label="Preview display density"
            >
              <button
                type="button"
                aria-pressed={density === "comfortable"}
                onClick={() => setDensity("comfortable")}
              >
                Comfortable
              </button>
              <button
                type="button"
                aria-pressed={density === "compact"}
                onClick={() => setDensity("compact")}
              >
                Compact
              </button>
            </div>
          </div>
          <div className="nx-preference-row">
            <span>
              <strong>Interface motion</strong>
              <small>Preview the motion preference</small>
            </span>
            <button
              type="button"
              className={"nx-preference-toggle" + (motion ? " is-on" : "")}
              aria-label="Preview interface motion"
              aria-pressed={motion}
              onClick={() => setMotion((current) => !current)}
            >
              <span />
            </button>
          </div>
          <div className={"nx-preference-example nx-density-" + density}>
            <span>PREVIEW / {motion ? "MOTION ON" : "MOTION OFF"}</span>
            <div>
              <DashboardIcon name="chat" size={19} /> Conversation example{" "}
              <DashboardIcon name="arrow" size={16} />
            </div>
            <div>
              <DashboardIcon name="projects" size={19} /> Project example{" "}
              <DashboardIcon name="arrow" size={16} />
            </div>
          </div>
        </section>
        <p className="nx-account-footnote">
          These preferences demonstrate the design only. They do not change
          global account settings.
        </p>
      </div>
    );
  }

  if (section === "usage") {
    return (
      <div className="nx-account-section">
        <header className="settings-section-heading">
          <p className="eyebrow">WORKSPACE ANALYTICS</p>
          <h2>Usage</h2>
          <p>
            A dedicated place for conversations, model tokens and usage
            insights.
          </p>
        </header>
        <div className="nx-usage-stats">
          {(
            [
              ["Messages", "chat", "No aggregate count connected"],
              ["Model tokens", "usage", "No token metering connected"],
              ["Provider spend", "overview", "No billing totals connected"],
            ] as const
          ).map(([label, icon, caption]) => (
            <div className="nx-usage-stat" key={label}>
              <span>
                <DashboardIcon name={icon} size={21} />
              </span>
              <strong>—</strong>
              <h3>{label}</h3>
              <small>{caption}</small>
            </div>
          ))}
        </div>
        <div className="nx-account-card nx-usage-chart">
          <div className="nx-ui-section-heading">
            <div>
              <span className="nx-ui-eyebrow">USAGE OVER TIME</span>
              <h3>Activity</h3>
            </div>
            <span className="nx-ui-muted">Awaiting telemetry</span>
          </div>
          <div
            className="nx-usage-chart-placeholder"
            aria-label="Usage chart placeholder"
          >
            <div className="nx-usage-chart-bars" aria-hidden="true">
              {[40, 52, 35, 61, 46, 72, 55, 64, 43, 58, 39, 65].map(
                (height, index) => (
                  <span key={index} style={{ height: height + "%" }} />
                ),
              )}
            </div>
            <span>
              <DashboardIcon name="usage" size={20} /> Usage reporting will
              appear when the metering API is connected.
            </span>
          </div>
          <p>
            Values are intentionally not fabricated. Individual generation token
            metadata exists, but this consolidated dashboard is not yet
            connected to an organization-level usage API.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="nx-account-section">
      <header className="settings-section-heading">
        <p className="eyebrow">ORGANIZATION CONTROLS</p>
        <h2>Security</h2>
        <p>Understand the access controls protecting the NEXUS workspace.</p>
      </header>
      <div className="nx-security-settings-grid">
        <section className="nx-account-card">
          <div className="nx-account-card-heading">
            <span className="nx-account-card-icon">
              <DashboardIcon name="security" size={22} />
            </span>
            <div>
              <h3>Multi-tenant isolation</h3>
              <p>
                Core records are scoped to an organization, with tenant-aware
                authorization boundaries.
              </p>
            </div>
          </div>
          <span className="nx-account-status">Platform foundation</span>
        </section>
        <section className="nx-account-card">
          <div className="nx-account-card-heading">
            <span className="nx-account-card-icon">
              <DashboardIcon name="profile" size={22} />
            </span>
            <div>
              <h3>Role-based access</h3>
              <p>
                Runtime permissions protect supported operations. Fine-grained
                document access will expand with RAG.
              </p>
            </div>
          </div>
          <span className="nx-account-status">Platform foundation</span>
        </section>
        <section className="nx-account-card">
          <div className="nx-account-card-heading">
            <span className="nx-account-card-icon">
              <DashboardIcon name="settings" size={22} />
            </span>
            <div>
              <h3>Bring your own key</h3>
              <p>
                Provider credentials are configured in a write-only flow and are
                not displayed after entry.
              </p>
            </div>
          </div>
          <Link className="nx-ui-text-link" to="/settings/ai-providers">
            Manage provider configuration →
          </Link>
        </section>
      </div>
    </div>
  );
}
