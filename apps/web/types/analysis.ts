import type { components } from "./api";

export type AnalysisTaskCreated = components["schemas"]["AnalysisTaskCreated"];
export type AnalysisStatusResponse =
  components["schemas"]["AnalysisTaskStatusResponse"];
export type AnalysisReport = components["schemas"]["AnalysisReport"];
export type AnalysisScene = components["schemas"]["SceneResult"];
export type AnalysisSubject = components["schemas"]["SubjectInfo"];
export type AnalysisRegion = components["schemas"]["RegionInfo"];
export type AnalysisLighting = components["schemas"]["LightingResult"];
export type AnalysisColor = components["schemas"]["ColorResult"];
export type AnalysisComposition = components["schemas"]["CompositionReport"];
export type AnalysisIssue = components["schemas"]["IssueReport"];
export type AnalysisRecommendation =
  components["schemas"]["RecommendationReport"];
export type AnalysisBBox = components["schemas"]["BBox"];
export type AnalysisEngine = components["schemas"]["EngineInfo"];
export type TaskStatus = components["schemas"]["TaskStatus"];
export type TaskStage = components["schemas"]["TaskStage"];
export type IssueSeverity = components["schemas"]["Severity"];
export type RecommendationPriority = components["schemas"]["Priority"];