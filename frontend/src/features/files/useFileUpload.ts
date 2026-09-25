import { useCallback, useEffect, useRef, useState } from "react";

import { initiateFileUpload } from "./api";
import { MAX_FILE_SIZE_BYTES, type PendingFileSummary } from "./types";
import { uploadGrantedFile } from "./upload";

export type FileUploadPhase =
  "idle" | "initiating" | "uploading" | "transferred" | "failed" | "cancelled";

export type FileUploadFeedback =
  | { kind: "file_too_large" }
  | { kind: "initiation_failure" }
  | { kind: "transfer_failure" };

interface FileUploadState {
  phase: FileUploadPhase;
  feedback: FileUploadFeedback | null;
  progress: number;
  file: PendingFileSummary | null;
}

interface ActiveUpload {
  controller: AbortController;
  operationId: number;
}

const idleState: FileUploadState = {
  phase: "idle",
  feedback: null,
  progress: 0,
  file: null,
};

export function useFileUpload() {
  const [state, setState] = useState<FileUploadState>(idleState);
  const activeUploadRef = useRef<ActiveUpload | null>(null);
  const nextOperationIdRef = useRef(0);
  const mountedRef = useRef(true);

  const operationIsCurrent = useCallback(
    (operation: ActiveUpload) =>
      mountedRef.current &&
      activeUploadRef.current?.operationId === operation.operationId,
    [],
  );

  const startUpload = useCallback(
    async (file: File): Promise<void> => {
      if (activeUploadRef.current !== null) {
        return;
      }

      if (file.size > MAX_FILE_SIZE_BYTES) {
        setState({
          phase: "failed",
          feedback: { kind: "file_too_large" },
          progress: 0,
          file: null,
        });
        return;
      }

      const operation: ActiveUpload = {
        controller: new AbortController(),
        operationId: nextOperationIdRef.current + 1,
      };
      nextOperationIdRef.current = operation.operationId;
      activeUploadRef.current = operation;
      setState({
        phase: "initiating",
        feedback: null,
        progress: 0,
        file: null,
      });

      let initiatedFile: PendingFileSummary | null = null;

      try {
        const initiation = await initiateFileUpload(
          file,
          operation.controller.signal,
        );
        initiatedFile = initiation.file;
        if (!operationIsCurrent(operation)) {
          return;
        }

        setState({
          phase: "uploading",
          feedback: null,
          progress: 0,
          file: initiatedFile,
        });

        await uploadGrantedFile({
          file,
          grant: initiation.upload,
          signal: operation.controller.signal,
          onProgress: (loadedBytes) => {
            if (!operationIsCurrent(operation) || file.size === 0) {
              return;
            }
            const progress = Math.min(
              100,
              Math.max(0, Math.round((loadedBytes / file.size) * 100)),
            );
            setState((current) => ({ ...current, progress }));
          },
        });

        if (operationIsCurrent(operation)) {
          setState({
            phase: "transferred",
            feedback: null,
            progress: 100,
            file: initiatedFile,
          });
        }
      } catch {
        if (!operationIsCurrent(operation)) {
          return;
        }

        if (operation.controller.signal.aborted) {
          setState({
            phase: "cancelled",
            feedback: null,
            progress: 0,
            file: initiatedFile,
          });
        } else {
          setState({
            phase: "failed",
            feedback: {
              kind:
                initiatedFile === null
                  ? "initiation_failure"
                  : "transfer_failure",
            },
            progress: 0,
            file: initiatedFile,
          });
        }
      } finally {
        if (operationIsCurrent(operation)) {
          activeUploadRef.current = null;
        }
      }
    },
    [operationIsCurrent],
  );

  const cancelUpload = useCallback(() => {
    activeUploadRef.current?.controller.abort();
  }, []);

  const reset = useCallback(() => {
    if (activeUploadRef.current === null) {
      setState(idleState);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const activeUpload = activeUploadRef.current;
      activeUploadRef.current = null;
      activeUpload?.controller.abort();
    };
  }, []);

  return {
    ...state,
    cancelUpload,
    reset,
    startUpload,
  };
}
