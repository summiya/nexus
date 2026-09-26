import { useState } from "react";

import { requestFileDownload } from "./api";

const DOWNLOAD_ERROR_MESSAGE = "Download could not be started. Try again.";

function startBrowserDownload(url: string): void {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.style.display = "none";
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  try {
    anchor.click();
  } finally {
    anchor.remove();
  }
}

export function FileDownloadButton({
  filePublicId,
}: {
  filePublicId: string;
}) {
  const [isRequesting, setIsRequesting] = useState(false);
  const [hasError, setHasError] = useState(false);

  async function download() {
    if (isRequesting) {
      return;
    }

    setIsRequesting(true);
    setHasError(false);
    try {
      const grant = await requestFileDownload(filePublicId);
      startBrowserDownload(grant.url);
    } catch {
      setHasError(true);
    } finally {
      setIsRequesting(false);
    }
  }

  return (
    <div className="file-download-action">
      <button
        className="text-button"
        disabled={isRequesting}
        type="button"
        onClick={() => void download()}
      >
        {isRequesting ? "Preparing…" : "Download"}
      </button>
      {hasError ? (
        <span className="file-download-error" role="alert">
          {DOWNLOAD_ERROR_MESSAGE}
        </span>
      ) : null}
    </div>
  );
}
