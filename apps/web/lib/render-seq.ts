let lastSeq = 0;

/**
 * Render sequence for this browser tab. Anchored to the wall clock so a remount
 * or a second tab can never reuse a stale value, with a +1 floor so two requests
 * inside the same millisecond still order correctly.
 */
export function nextRenderSeq(): number {
  lastSeq = Math.max(Date.now(), lastSeq + 1);
  return lastSeq;
}
