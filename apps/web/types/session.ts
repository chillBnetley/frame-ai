import type { components } from "./api";

export type EditRecipe = components["schemas"]["EditRecipe"];
export type Adjustments = components["schemas"]["Adjustments"];
export type LocalAdjustments = components["schemas"]["LocalAdjustments"];
export type LocalAdjustment = components["schemas"]["LocalAdjustment"];
export type UserMask = components["schemas"]["UserMask"];
export type MaskShape = UserMask["shape"];
export type Crop = components["schemas"]["Crop"];
export type CurvePoint = components["schemas"]["CurvePoint"];
export type CurveSet = components["schemas"]["CurveSet"];
export type CurveChannel = keyof CurveSet;
export type HslBand = components["schemas"]["HslBand"];
export type HslAdjustments = components["schemas"]["HslAdjustments"];
export type HslBandName = keyof HslAdjustments;
export type ColorGradeZone = components["schemas"]["ColorGradeZone"];
export type ColorGrading = components["schemas"]["ColorGrading"];
export type ColorGradeZoneName = "shadows" | "midtones" | "highlights";
export type OutputSettings = components["schemas"]["OutputSettings"];
export type SessionState = components["schemas"]["SessionState"];
export type RevisionView = components["schemas"]["RevisionView"];
export type RevisionSummary = components["schemas"]["RevisionSummary"];
export type RevisionListResponse = components["schemas"]["RevisionListResponse"];
export type RevisionSource = RevisionSummary["source"];
export type RenderRequest = components["schemas"]["RenderRequest"];
export type RenderResponse = components["schemas"]["RenderResponse"];
export type CompareResponse = components["schemas"]["CompareResponse"];
export type ExportFormat = components["schemas"]["ExportRequest"]["format"];
export type ExportBitDepth = components["schemas"]["ExportRequest"]["bitDepth"];

export interface EditorRecipe
  extends Omit<
    EditRecipe,
    | "adjustments"
    | "curve"
    | "hsl"
    | "colorGrading"
    | "masks"
    | "localAdjustments"
    | "output"
    | "rationale"
    | "warnings"
  > {
  adjustments: Adjustments;
  curve: CurveSet;
  hsl: Required<HslAdjustments>;
  colorGrading: Required<ColorGrading>;
  masks: UserMask[];
  localAdjustments: LocalAdjustment[];
  output: OutputSettings;
  rationale: string[];
  warnings: string[];
}
