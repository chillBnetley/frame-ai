import type { components } from "./api";

export type EditRecipe = components["schemas"]["EditRecipe"];
export type Adjustments = components["schemas"]["Adjustments"];
export type Crop = components["schemas"]["Crop"];
export type SessionState = components["schemas"]["SessionState"];
export type RevisionView = components["schemas"]["RevisionView"];
export type RevisionSummary = components["schemas"]["RevisionSummary"];
export type RevisionListResponse = components["schemas"]["RevisionListResponse"];
export type RevisionSource = RevisionSummary["source"];
export type RenderRequest = components["schemas"]["RenderRequest"];
export type RenderResponse = components["schemas"]["RenderResponse"];
export type CompareResponse = components["schemas"]["CompareResponse"];
export type ExportFormat = components["schemas"]["ExportRequest"]["format"];

export interface EditorRecipe
  extends Omit<EditRecipe, "adjustments" | "rationale" | "warnings"> {
  adjustments: Adjustments;
  rationale: string[];
  warnings: string[];
}
