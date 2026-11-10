import type { components } from "./api";

export type StyleMixSourceRef = components["schemas"]["StyleMixSourceRef"];
export type StyleMixRequest = components["schemas"]["StyleMixRequest"];
export type StyleMixSaveRequest = components["schemas"]["StyleMixSaveRequest"];
export type StyleMixPreviewResponse =
  components["schemas"]["StyleMixPreviewResponse"];
export type StyleMixProvenance = components["schemas"]["StyleMixProvenance"];
export type StyleMixConflict = components["schemas"]["StyleMixConflict"];
export type StyleMixDimensionPlan =
  components["schemas"]["StyleMixDimensionPlan"];
export type MixDimension = StyleMixDimensionPlan["dimension"];
export type MixSource = StyleMixDimensionPlan["source"];
export type ConflictResolution = StyleMixConflict["resolution"];