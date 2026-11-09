import type { components } from "./api";

export type PhotographerPlanRequest =
  components["schemas"]["PhotographerPlanRequest"];
export type PhotographerPlanResponse =
  components["schemas"]["PhotographerPlanResponse"];
export type AcceptPlanRequest = components["schemas"]["AcceptPlanRequest"];
export type PhotographerPatchRequest =
  components["schemas"]["PhotographerPatchRequest"];
export type PhotographerPatchResponse =
  components["schemas"]["PhotographerPatchResponse"];
export type PhotographerDiagnosis = components["schemas"]["DiagnosisResult"];
export type PhotographerDiagnosisItem = components["schemas"]["DiagnosisItem"];
export type PhotographerCreativeChoice =
  components["schemas"]["CreativeChoice"];
export type PhotographerDirection = components["schemas"]["CreativeDirection"];
export type PhotographerParameterChange =
  components["schemas"]["ParameterChange"];
export type PhotographerProviderInfo = components["schemas"]["ProviderInfo"];
export type PlannerMode = components["schemas"]["PlannerMode"];
export type PhotographerStyle = components["schemas"]["StyleDefinition"];
export type StyleCategory = components["schemas"]["StyleCategory"];
export type SceneLabel = components["schemas"]["SceneLabel"];
export type StyleListResponse = components["schemas"]["StyleListResponse"];
export type PhotographerCritiqueRequest =
  components["schemas"]["PhotographerCritiqueRequest"];
export type PhotographerCritique = components["schemas"]["CritiqueResponse"];
export type PhotographerCritiquePoint =
  components["schemas"]["CritiquePoint"];
export type PhotographerCritiqueCreative =
  components["schemas"]["CritiqueCreative"];
export type PhotographerCritiqueSuggestion =
  components["schemas"]["CritiqueSuggestion"];
export type CritiqueApplyRequest = components["schemas"]["CritiqueApplyRequest"];
export type CritiqueApplyResponse =
  components["schemas"]["CritiqueApplyResponse"];
export type AdjustmentIntent = components["schemas"]["AdjustmentIntent"];
export type RecommendationCategory =
  components["schemas"]["RecommendationCategory"];
export type FeedbackAction = components["schemas"]["FeedbackAction"];
export type FeedbackSource = components["schemas"]["FeedbackSource"];
export type FeedbackRubric = components["schemas"]["FeedbackRubric"];
export type PhotographerFeedbackRequest =
  components["schemas"]["PhotographerFeedbackRequest"];
export type PhotographerFeedback =
  components["schemas"]["PhotographerFeedbackResponse"];
export type FeedbackListResponse =
  components["schemas"]["PhotographerFeedbackListResponse"];
export type FeedbackSummary = components["schemas"]["FeedbackSummary"];
export type FeedbackDimension = keyof FeedbackRubric;
