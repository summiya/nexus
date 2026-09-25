import { type FormEvent, useState } from "react";

import { MAX_FILE_SIZE_BYTES } from "./types";
import {
  type FileUploadFeedback,
  type FileUploadPhase,
  useFileUpload,
} from "./useFileUpload";

const feedbackMessages: Record<FileUploadFeedback["kind"], string> = {
  file_too_large: "Maximum file size is 512 MB.",
  initiation_failure: "Unable to start the upload. Please try again.",
  transfer_failure: "Upload failed. Please try again.",
};

function phaseMessage(phase: FileUploadPhase): string | null {
  if (phase === "cancelled") {
    return "Upload cancelled.";
  }
  if (phase === "transferred") {
    return "Upload completed. The file is awaiting verification.";
  }
  if (phase === "initiating") {
    return "Preparing upload…";
  }
  if (phase === "uploading") {
    return "Uploading file…";
  }
  return null;
}

function formatFileSize(size: number): string {
  return `${new Intl.NumberFormat().format(size)} bytes`;
}

export function FileUploadPanel() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const { cancelUpload, feedback, phase, progress, reset, startUpload } =
    useFileUpload();
  const active = phase === "initiating" || phase === "uploading";
  const selectedFileIsTooLarge =
    selectedFile !== null && selectedFile.size > MAX_FILE_SIZE_BYTES;
  const message = phaseMessage(phase);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedFile === null || selectedFileIsTooLarge || active) {
      return;
    }
    void startUpload(selectedFile);
  }

  return (
    <section className="file-upload-card" aria-labelledby="file-upload-heading">
      <div className="file-upload-copy">
        <p className="eyebrow">Files</p>
        <h1 id="file-upload-heading">Upload a file</h1>
        <p>
          Upload one file directly to secure storage. It will remain pending
          until Nexus verifies it.
        </p>
      </div>

      <form className="file-upload-form" onSubmit={handleSubmit}>
        <div className="form-field">
          <label htmlFor="file-upload-input">Choose a file</label>
          <input
            id="file-upload-input"
            disabled={active}
            type="file"
            onChange={(event) => {
              setSelectedFile(event.target.files?.item(0) ?? null);
              reset();
            }}
          />
          <p className="file-upload-limit">Maximum file size: 512 MB.</p>
        </div>

        {selectedFile ? (
          <dl className="selected-file-summary">
            <div>
              <dt>File</dt>
              <dd>{selectedFile.name}</dd>
            </div>
            <div>
              <dt>Size</dt>
              <dd>{formatFileSize(selectedFile.size)}</dd>
            </div>
          </dl>
        ) : null}

        {phase === "uploading" ? (
          <div className="file-upload-progress">
            <label htmlFor="file-upload-progress">Upload progress</label>
            <progress id="file-upload-progress" max={100} value={progress} />
            <span>{progress}%</span>
          </div>
        ) : null}

        <div className="file-upload-actions">
          <button
            className="primary-button"
            disabled={selectedFile === null || selectedFileIsTooLarge || active}
            type="submit"
          >
            {phase === "initiating"
              ? "Preparing…"
              : phase === "uploading"
                ? "Uploading…"
                : "Upload"}
          </button>
          {active ? (
            <button
              className="text-button"
              type="button"
              onClick={cancelUpload}
            >
              Cancel
            </button>
          ) : null}
        </div>

        {selectedFileIsTooLarge ? (
          <p className="file-upload-feedback" role="alert">
            {feedbackMessages.file_too_large}
          </p>
        ) : feedback ? (
          <p className="file-upload-feedback" role="alert">
            {feedbackMessages[feedback.kind]}
          </p>
        ) : message ? (
          <p
            className={`file-upload-status file-upload-status-${phase}`}
            role={phase === "cancelled" ? "alert" : "status"}
          >
            {message}
          </p>
        ) : null}
      </form>
    </section>
  );
}
