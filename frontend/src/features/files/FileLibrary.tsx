import { useState } from "react";

import { FileDownloadButton } from "./FileDownloadButton";
import { FileStatusBadge } from "./FileStatusBadge";
import { useFilesQuery } from "./queries";
import type { FileMetadata } from "./types";

function formatFileSize(sizeBytes: number | null): string {
  if (sizeBytes === null) {
    return "—";
  }
  if (sizeBytes < 1024) {
    return `${sizeBytes} B`;
  }

  const units = ["KB", "MB", "GB", "TB"] as const;
  let value = sizeBytes / 1024;
  let unit: (typeof units)[number] = units[0];

  for (const candidate of units) {
    unit = candidate;
    if (value < 1024 || candidate === units[units.length - 1]) {
      break;
    }
    value /= 1024;
  }

  return `${new Intl.NumberFormat(undefined, {
    maximumFractionDigits: value >= 10 ? 0 : 1,
  }).format(value)} ${unit}`;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

function FileRow({ file }: { file: FileMetadata }) {
  return (
    <li className="file-library-row">
      <div className="file-library-name">
        <strong title={file.originalName}>{file.originalName}</strong>
        <span>{file.mimeType}</span>
      </div>
      <span className="file-library-size">
        {formatFileSize(file.sizeBytes)}
      </span>
      <div className="file-library-status">
        <FileStatusBadge status={file.storageStatus} />
        {file.storageStatus === "pending" ? (
          <span className="file-status-explanation">
            Being checked for security
          </span>
        ) : null}
      </div>
      <time dateTime={file.createdAt}>{formatDate(file.createdAt)}</time>
      {file.storageStatus === "available" ? (
        <FileDownloadButton filePublicId={file.publicId} />
      ) : (
        <span aria-hidden="true" />
      )}
    </li>
  );
}

export function FileLibrary() {
  const [currentCursor, setCurrentCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<(string | null)[]>([]);
  const files = useFilesQuery(currentCursor);
  const page = files.data;
  const items = page?.items ?? [];
  const navigating = files.isPlaceholderData;

  function goNext() {
    if (
      page?.nextCursor === null ||
      page?.nextCursor === undefined ||
      navigating
    ) {
      return;
    }
    setCursorHistory((history) => [...history, currentCursor]);
    setCurrentCursor(page.nextCursor);
  }

  function goPrevious() {
    if (cursorHistory.length === 0 || navigating) {
      return;
    }
    const previousCursor = cursorHistory[cursorHistory.length - 1];
    setCursorHistory((history) => history.slice(0, -1));
    setCurrentCursor(previousCursor);
  }

  return (
    <section className="file-library" aria-labelledby="file-library-heading">
      <div className="file-library-header">
        <div>
          <p className="eyebrow">Library</p>
          <h2 id="file-library-heading">Your files</h2>
        </div>
        {cursorHistory.length > 0 ? (
          <span className="file-library-page-number">
            Page {cursorHistory.length + 1}
          </span>
        ) : null}
      </div>

      {files.isPending ? (
        <p className="file-library-state" role="status">
          Loading files…
        </p>
      ) : files.isError ? (
        <div className="file-library-error">
          <p role="alert">Files are temporarily unavailable.</p>
          <div className="file-library-error-actions">
            {cursorHistory.length > 0 ? (
              <button
                className="text-button"
                type="button"
                onClick={goPrevious}
              >
                Previous
              </button>
            ) : null}
            <button
              className="text-button"
              disabled={files.isFetching}
              type="button"
              onClick={() => void files.refetch()}
            >
              {files.isFetching ? "Retrying…" : "Retry"}
            </button>
          </div>
        </div>
      ) : items.length === 0 ? (
        <div className="file-library-empty">
          <p>No files yet.</p>
          <span>
            Upload your first file above and it will appear here after Nexus
            verifies it.
          </span>
        </div>
      ) : (
        <>
          <div className="file-library-column-headings" aria-hidden="true">
            <span>File</span>
            <span>Size</span>
            <span>Status</span>
            <span>Added</span>
            <span>Action</span>
          </div>
          <ul className="file-library-list">
            {items.map((file) => (
              <FileRow key={file.publicId} file={file} />
            ))}
          </ul>
          {files.isPlaceholderData ? (
            <p className="file-library-fetching" role="status">
              Loading page…
            </p>
          ) : null}
          <nav className="file-library-pagination" aria-label="File pages">
            <button
              className="text-button"
              disabled={cursorHistory.length === 0 || navigating}
              type="button"
              onClick={goPrevious}
            >
              Previous
            </button>
            <button
              className="text-button"
              disabled={page?.nextCursor == null || navigating}
              type="button"
              onClick={goNext}
            >
              Next
            </button>
          </nav>
        </>
      )}
    </section>
  );
}
