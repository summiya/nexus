import { DashboardIcon } from "../components/dashboard/DashboardIcon";
import { FileLibrary, FileUploadPanel } from "../features/files";

export function FilesPage() {
  return (
    <section className="nx-ui-page nx-files-page">
      <header className="nx-ui-heading">
        <div>
          <span className="nx-ui-eyebrow">
            <DashboardIcon name="files" size={16} /> WORKSPACE / FILES
          </span>
          <h1>Files & storage</h1>
          <p>
            Upload, organize and manage your organization's documents in one
            secure workspace.
          </p>
        </div>
        <span className="nx-ui-outline-tag">
          <DashboardIcon name="security" size={16} /> Organization-scoped
          storage
        </span>
      </header>
      <div
        className="nx-file-overview-strip"
        aria-label="File workspace capabilities"
      >
        <div>
          <span>
            <DashboardIcon name="files" size={20} />
          </span>
          <strong>Secure upload</strong>
          <small>Direct storage transfer</small>
        </div>
        <div>
          <span>
            <DashboardIcon name="security" size={20} />
          </span>
          <strong>512 MB</strong>
          <small>Maximum file size</small>
        </div>
        <div>
          <span>
            <DashboardIcon name="check" size={20} />
          </span>
          <strong>Verified storage</strong>
          <small>Tracked file status</small>
        </div>
      </div>
      <div className="files-page">
        <FileUploadPanel />
        <FileLibrary />
      </div>
    </section>
  );
}
