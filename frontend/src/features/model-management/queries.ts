import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { conversationKeys } from "../conversations";
import {
  clearModelDefault,
  deleteConfiguredModel,
  discoverProviderModels,
  getModelDefaults,
  listConfiguredModels,
  registerModels,
  setConfiguredModelEnabled,
  setModelDefault,
} from "./api";
import type { ModelRegistrationInput, ModelType } from "./types";

export const modelManagementKeys = {
  all: ["model-management"] as const,
  configuredModels: () => ["model-management", "configured-models"] as const,
  defaults: () => ["model-management", "defaults"] as const,
  discovery: (providerPublicId: string) =>
    ["model-management", "discovery", providerPublicId] as const,
};

export function useConfiguredModelsQuery(enabled: boolean) {
  return useQuery({
    queryKey: modelManagementKeys.configuredModels(),
    queryFn: listConfiguredModels,
    enabled,
  });
}

export function useModelDefaultsQuery(enabled: boolean) {
  return useQuery({
    queryKey: modelManagementKeys.defaults(),
    queryFn: getModelDefaults,
    enabled,
  });
}

export function useProviderModelDiscoveryQuery(providerPublicId: string) {
  return useQuery({
    queryKey: modelManagementKeys.discovery(providerPublicId),
    queryFn: () => discoverProviderModels(providerPublicId),
    enabled: false,
    retry: false,
  });
}

export function useRegisterModelsMutation(providerPublicId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: ModelRegistrationInput) =>
      registerModels(providerPublicId, input),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: modelManagementKeys.configuredModels(),
        }),
        queryClient.invalidateQueries({
          queryKey: modelManagementKeys.discovery(providerPublicId),
        }),
        queryClient.invalidateQueries({
          queryKey: conversationKeys.chatModels(),
        }),
      ]);
    },
  });
}

export function useSetConfiguredModelEnabledMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      modelPublicId,
      enabled,
    }: {
      modelPublicId: string;
      enabled: boolean;
    }) => setConfiguredModelEnabled(modelPublicId, enabled),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: modelManagementKeys.configuredModels(),
        }),
        queryClient.invalidateQueries({
          queryKey: conversationKeys.chatModels(),
        }),
      ]);
    },
  });
}

export function useDeleteConfiguredModelMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (modelPublicId: string) => deleteConfiguredModel(modelPublicId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: modelManagementKeys.configuredModels(),
        }),
        queryClient.invalidateQueries({
          queryKey: modelManagementKeys.defaults(),
        }),
        queryClient.invalidateQueries({
          queryKey: conversationKeys.chatModels(),
        }),
      ]);
    },
  });
}

export function useSetModelDefaultMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      modelType,
      modelPublicId,
    }: {
      modelType: ModelType;
      modelPublicId: string;
    }) => setModelDefault(modelType, modelPublicId),
    onSuccess: async (_defaults, variables) => {
      const invalidations = [
        queryClient.invalidateQueries({
          queryKey: modelManagementKeys.defaults(),
        }),
      ];
      if (variables.modelType === "chat") {
        invalidations.push(
          queryClient.invalidateQueries({
            queryKey: conversationKeys.chatModels(),
          }),
        );
      }
      await Promise.all(invalidations);
    },
  });
}

export function useClearModelDefaultMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (modelType: ModelType) => clearModelDefault(modelType),
    onSuccess: async (_result, modelType) => {
      const invalidations = [
        queryClient.invalidateQueries({
          queryKey: modelManagementKeys.defaults(),
        }),
      ];
      if (modelType === "chat") {
        invalidations.push(
          queryClient.invalidateQueries({
            queryKey: conversationKeys.chatModels(),
          }),
        );
      }
      await Promise.all(invalidations);
    },
  });
}
