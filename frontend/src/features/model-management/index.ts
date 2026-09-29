export { AIModelsSettings } from "./AIModelsSettings";
export {
  clearModelDefault,
  deleteConfiguredModel,
  discoverProviderModels,
  getModelDefaults,
  listConfiguredModels,
  registerModels,
  setConfiguredModelEnabled,
  setModelDefault,
} from "./api";
export {
  modelManagementKeys,
  useConfiguredModelsQuery,
  useModelDefaultsQuery,
  useProviderModelDiscoveryQuery,
} from "./queries";
export type {
  ConfiguredModel,
  DiscoveredModelRegistrationInput,
  ManualModelRegistrationInput,
  ModelCandidate,
  ModelCapability,
  ModelDefaults,
  ModelRegistrationInput,
  ModelType,
} from "./types";
