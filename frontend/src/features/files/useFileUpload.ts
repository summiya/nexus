import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { initiateFileUpload } from "./api";
import { fileKeys } from "./queries";
import { MAX_FILE_SIZE_BYTES } from "./types";
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
}

interface ActiveUpload {
  controller: AbortController;
  operationId: number;
}

const idleState: FileUploadState = {
  phase: "idle",
  feedback: null,
  progress: 0,
};

export function useFileUpload() {
  const queryClient = useQueryClient();
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
      });

      let transferStarted = false;

      try {
        const initiation = await initiateFileUpload(
          file,
          operation.controller.signal,
        );
        if (!operationIsCurrent(operation)) {
          return;
        }
        transferStarted = true;

        setState({
          phase: "uploading",
          feedback: null,
          progress: 0,
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
          });
          await queryClient.invalidateQueries({ queryKey: fileKeys.all });
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
          });
        } else {
          setState({
            phase: "failed",
            feedback: {
              kind: !transferStarted
                ? "initiation_failure"
                : "transfer_failure",
            },
            progress: 0,
          });
        }
      } finally {
        if (operationIsCurrent(operation)) {
          activeUploadRef.current = null;
        }
      }
    },
    [operationIsCurrent, queryClient],
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
