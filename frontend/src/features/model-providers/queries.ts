import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createProvider,
  deleteProvider,
  getModelProviderCapabilities,
  listConfiguredProviders,
  listProviderCatalog,
  setProviderEnabled,
  updateProvider,
  validateProvider,
} from "./api";
import type { CreateProviderInput, UpdateProviderInput } from "./types";

export const modelProviderKeys = {
  all: ["model-providers"] as const,
  capabilities: () => ["model-providers", "capabilities"] as const,
  catalog: () => ["model-providers", "catalog"] as const,
  list: () => ["model-providers", "list"] as const,
};

export function useModelProviderCapabilitiesQuery() {
  return useQuery({
    queryKey: modelProviderKeys.capabilities(),
    queryFn: getModelProviderCapabilities,
  });
}

export function useProviderCatalogQuery(enabled: boolean) {
  return useQuery({
    queryKey: modelProviderKeys.catalog(),
    queryFn: listProviderCatalog,
    enabled,
  });
}

export function useConfiguredProvidersQuery(enabled: boolean) {
  return useQuery({
    queryKey: modelProviderKeys.list(),
    queryFn: listConfiguredProviders,
    enabled,
  });
}

function useListInvalidation() {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({ queryKey: modelProviderKeys.list() });
}

export function useCreateProviderMutation() {
  const invalidateList = useListInvalidation();
  return useMutation({
    mutationFn: (input: CreateProviderInput) => createProvider(input),
    onSuccess: invalidateList,
  });
}

export function useUpdateProviderMutation(providerPublicId: string) {
  const invalidateList = useListInvalidation();
  return useMutation({
    mutationFn: (input: UpdateProviderInput) =>
      updateProvider(providerPublicId, input),
    onSuccess: invalidateList,
  });
}

export function useValidateProviderMutation(providerPublicId: string) {
  const invalidateList = useListInvalidation();
  return useMutation({
    mutationFn: () => validateProvider(providerPublicId),
    onSuccess: invalidateList,
  });
}

export function useSetProviderEnabledMutation(providerPublicId: string) {
  const invalidateList = useListInvalidation();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      setProviderEnabled(providerPublicId, enabled),
    onSuccess: invalidateList,
  });
}

export function useDeleteProviderMutation(providerPublicId: string) {
  const invalidateList = useListInvalidation();
  return useMutation({
    mutationFn: () => deleteProvider(providerPublicId),
    onSuccess: invalidateList,
  });
}
