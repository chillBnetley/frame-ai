import {
  issueTypeLabel,
  sortIssues,
  subjectTypeLabel,
} from "@/features/analysis/presentation";
import type {
  AnalysisBBox,
  AnalysisIssue,
  AnalysisReport,
  AnalysisSubject,
  IssueSeverity,
} from "@/types/analysis";
import type { StudioCapability } from "./studio/use-studio-state";

export type SuggestionRoute = "generative" | "adjustment";

export interface GenerativeSuggestion {
  id: string;
  route: SuggestionRoute;
  capability: StudioCapability | null;
  label: string;
  severity: IssueSeverity;
  evidence: string;
  advice: string | null;
  instruction: string | null;
  subjectLabel: string | null;
  subjectBbox: AnalysisBBox | null;
}

/**
 * Only composition and detail defects can be fixed by redrawing pixels.
 * Exposure, colour, noise and tilt stay in 参数精修 so generation is never
 * used to paper over a measurement the renderer already handles.
 */
const GENERATIVE_ROUTES: Partial<
  Record<AnalysisIssue["type"], { capability: StudioCapability; instruction: string }>
> = {
  negative_space_issue: {
    capability: "outpaint",
    instruction: "向外扩展画面补足留白，保持主体位置、透视与原有光线一致",
  },
  subject_placement: {
    capability: "outpaint",
    instruction: "扩展画幅重新安排主体位置，保持原有透视、光线与色调",
  },
  balance_issue: {
    capability: "outpaint",
    instruction: "向失衡的一侧扩展画面以平衡构图，保持原有光线与色调",
  },
  low_detail: {
    capability: "local_edit",
    instruction: "在选定区域补回真实纹理细节，保持原有光线与色彩",
  },
  focus_issue: {
    capability: "local_edit",
    instruction: "重绘选定区域使其清晰合焦，保持内容与光线不变",
  },
  motion_blur: {
    capability: "local_edit",
    instruction: "消除选定区域的动态模糊，恢复清晰边缘并保持内容一致",
  },
};

function matchedSubject(
  issue: AnalysisIssue,
  subjects: readonly AnalysisSubject[],
): AnalysisSubject | null {
  const regionIds = new Set(issue.regionIds);
  const candidates = subjects.filter((subject) => regionIds.has(subject.regionId));
  return candidates.find((subject) => subject.role === "primary") ?? candidates[0] ?? null;
}

function toSuggestion(
  issue: AnalysisIssue,
  subjects: readonly AnalysisSubject[],
): GenerativeSuggestion {
  const route = GENERATIVE_ROUTES[issue.type];
  const subject = route?.capability === "local_edit" ? matchedSubject(issue, subjects) : null;
  return {
    id: issue.id,
    route: route ? "generative" : "adjustment",
    capability: route?.capability ?? null,
    label: issueTypeLabel(issue.type),
    severity: issue.severity,
    evidence: issue.evidence,
    advice: issue.suggestion ?? null,
    instruction: route?.instruction ?? null,
    subjectLabel: subject ? subjectTypeLabel(subject.type) : null,
    subjectBbox: subject?.bbox ?? null,
  };
}

export function buildGenerativeSuggestions(
  report: AnalysisReport | null,
): GenerativeSuggestion[] {
  if (!report) {
    return [];
  }
  const suggestions = sortIssues(report.issues).map((issue) =>
    toSuggestion(issue, report.subjects),
  );
  return [
    ...suggestions.filter((item) => item.route === "generative"),
    ...suggestions.filter((item) => item.route === "adjustment"),
  ];
}