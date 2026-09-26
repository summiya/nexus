import type { FileStorageStatus } from "./types";

const labels: Record<FileStorageStatus, string> = {
  pending: "Pending",
  available: "Available",
  failed: "Failed",
};

export function FileStatusBadge({ status }: { status: FileStorageStatus }) {
  return (
    <span className={`file-status-badge file-status-badge-${status}`}>
      {labels[status]}
    </span>
  );
}
