import { vi } from "vitest";

import type { UseFeedbackResult } from "@/features/photographer/hooks/use-feedback";
import type {
  FeedbackRubric,
  FeedbackSummary,
  PhotographerFeedback,
} from "@/types/photographer";

import { PLAN_ID } from "./photographer-fixtures";
import { IMAGE_ID, REVISION_ID, SESSION_ID } from "./session-fixtures";

export const FEEDBACK_ID = "66666666-6666-4666-8666-666666666666";

export function feedbackSummary(
  overrides: Partial<FeedbackSummary> = {},
): FeedbackSummary {
  return {
    total: 0,
    accepted: 0,
    rejected: 0,
    modified: 0,
    reset: 0,
    bySource: { plan: 0, chat: 0, critique: 0, unset: 0 },
    mockCount: 0,
    realCount: 0,
    degradedCount: 0,
    ratedCount: 0,
    changeFrequency: [],
    rubricAverages: [],
    disclaimers: [
      "接受、拒绝、修改与重置只记录用户行为，不代表方案在客观质量上更优。",
    ],
    ...overrides,
  };
}

export function feedbackRecord(
  overrides: Partial<PhotographerFeedback> = {},
): PhotographerFeedback {
  const rubric: FeedbackRubric = { exposure: 4, skinTone: 3 };
  return {
    id: FEEDBACK_ID,
    sessionId: SESSION_ID,
    imageId: IMAGE_ID,
    planId: PLAN_ID,
    revisionId: REVISION_ID,
    source: "plan",
    action: "accepted",
    changedPaths: ["adjustments.contrast"],
    rubric,
    isMock: true,
    degraded: false,
    createdAt: "2026-11-05T10:12:00Z",
    ...overrides,
  };
}

/** A hook stand-in whose network calls are all no-op mocks. */
export function feedbackState(
  overrides: Partial<UseFeedbackResult> = {},
): UseFeedbackResult {
  return {
    sessionId: SESSION_ID,
    items: [],
    summary: null,
    loading: false,
    historyError: null,
    unsent: 0,
    sendError: null,
    rating: null,
    record: vi.fn(async () => true),
    recordAndAskForRating: vi.fn(async () => true),
    submitRating: vi.fn(async () => true),
    dismissRating: vi.fn(),
    retryUnsent: vi.fn(async () => true),
    refresh: vi.fn(async () => undefined),
    remove: vi.fn(async () => undefined),
    ...overrides,
  };
}
