/**
 * Session-only fallback used when the onboarding marker cannot be written.
 * This is deliberately not the persistence mechanism: the workbench is gated by
 * the data-directory marker, and this cookie only prevents a read-only data
 * directory from locking the user out for the current browser session.
 */
export const ONBOARDING_SESSION_COOKIE = "frame_onboarding_session";
export const ONBOARDING_SESSION_VALUE = "1";
