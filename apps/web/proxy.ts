import fs from "node:fs";
import path from "node:path";

import { NextResponse, type NextRequest } from "next/server";

import {
  ONBOARDING_SESSION_COOKIE,
  ONBOARDING_SESSION_VALUE,
} from "./lib/onboarding-cookie";
import {
  readOnboardingCompleted,
  resolveFrameDataDir,
} from "./lib/onboarding-state";

const TOKEN_FILENAME = "api-token";

function tokenFile(): string {
  const explicit = process.env.FRAME_API_TOKEN_FILE?.trim();
  if (explicit) {
    return explicit;
  }
  return path.join(resolveFrameDataDir(), TOKEN_FILENAME);
}

/**
 * Reads the current token on every request so an API restart (which rotates it)
 * is picked up without restarting Next.js. Proxy always runs on the Node runtime.
 */
export function readApiToken(): string | null {
  try {
    const token = fs.readFileSync(tokenFile(), "utf8").trim();
    return token.length > 0 ? token : null;
  } catch {
    return null;
  }
}

export function proxy(request: NextRequest): NextResponse {
  const sessionBypass =
    request.cookies.get(ONBOARDING_SESSION_COOKIE)?.value === ONBOARDING_SESSION_VALUE;

  if (
    request.nextUrl.pathname === "/" &&
    !sessionBypass &&
    !readOnboardingCompleted()
  ) {
    return NextResponse.redirect(new URL("/welcome", request.url));
  }

  if (!request.nextUrl.pathname.startsWith("/api/v1")) {
    return NextResponse.next();
  }

  const token = readApiToken();
  if (token === null) {
    if (!request.headers.has("X-FRAME-Token")) {
      return NextResponse.next();
    }
    const headers = new Headers(request.headers);
    headers.delete("X-FRAME-Token");
    return NextResponse.next({ request: { headers } });
  }
  const headers = new Headers(request.headers);
  headers.set("X-FRAME-Token", token);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: ["/", "/api/v1/:path*", "/api/v1"],
};
