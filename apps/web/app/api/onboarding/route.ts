import { connection } from "next/server";

import {
  readOnboardingCompleted,
  writeOnboardingCompleted,
} from "@/lib/onboarding-state";

function isSameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (origin === null) {
    return true;
  }
  const host = request.headers.get("host");
  if (host === null) {
    return false;
  }
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

export async function GET(): Promise<Response> {
  await connection();
  return Response.json(
    { completed: readOnboardingCompleted() },
    { headers: { "cache-control": "no-store" } },
  );
}

export async function POST(request: Request): Promise<Response> {
  if (!isSameOrigin(request)) {
    return Response.json({ error: "forbidden" }, { status: 403 });
  }

  const contentType = request.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    return Response.json({ error: "unsupported_media_type" }, { status: 415 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid_body" }, { status: 422 });
  }

  if (
    typeof body !== "object" ||
    body === null ||
    (body as { completed?: unknown }).completed !== true
  ) {
    return Response.json({ error: "invalid_body" }, { status: 422 });
  }

  try {
    writeOnboardingCompleted();
  } catch (error) {
    console.warn("Unable to write onboarding state.", error);
    return Response.json({ error: "onboarding_write_failed" }, { status: 500 });
  }

  return Response.json(
    { completed: true },
    { headers: { "cache-control": "no-store" } },
  );
}
