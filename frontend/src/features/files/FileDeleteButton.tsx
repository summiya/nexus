import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { deleteFile } from "./api";
import { fileKeys } from "./queries";

const DELETE_ERROR_MESSAGE = "File could not be deleted. Try again.";

export function FileDeleteButton({
  filePublicId,
  originalName,
}: {
  filePublicId: string;
  originalName: string;
}) {
  const queryClient = useQueryClient();
  const [isDeleting, setIsDeleting] = useState(false);
  const [hasError, setHasError] = useState(false);

  async function remove() {
    if (isDeleting) {
      return;
    }
    const confirmed = window.confirm(
      `Delete "${originalName}"? This cannot be undone.`,
    );
    if (!confirmed) {
      return;
    }

    setIsDeleting(true);
    setHasError(false);
    try {
      await deleteFile(filePublicId);
      await queryClient.invalidateQueries({ queryKey: fileKeys.all });
    } catch {
      setHasError(true);
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <div className="file-delete-action">
      <button
        className="text-button"
        disabled={isDeleting}
        type="button"
        onClick={() => void remove()}
      >
        {isDeleting ? "Deleting…" : "Delete"}
      </button>
      {hasError ? (
        <span className="file-delete-error" role="alert">
          {DELETE_ERROR_MESSAGE}
        </span>
      ) : null}
    </div>
  );
}
