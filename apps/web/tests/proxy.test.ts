// @vitest-environment node
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ONBOARDING_SESSION_COOKIE } from "../lib/onboarding-cookie";
import { config, proxy, readApiToken } from "../proxy";

describe("proxy token injection", () => {
  let directory: string;
  let tokenFile: string;
  let previousTokenFile: string | undefined;
  let previousDataDir: string | undefined;

  beforeEach(() => {
    directory = fs.mkdtempSync(path.join(os.tmpdir(), "frame-proxy-test-"));
    tokenFile = path.join(directory, "api-token");
    previousTokenFile = process.env.FRAME_API_TOKEN_FILE;
    previousDataDir = process.env.FRAME_DATA_DIR;
    process.env.FRAME_API_TOKEN_FILE = tokenFile;
    delete process.env.FRAME_DATA_DIR;
  });

  afterEach(() => {
    fs.rmSync(directory, { recursive: true, force: true });
    if (previousTokenFile === undefined) {
      delete process.env.FRAME_API_TOKEN_FILE;
    } else {
      process.env.FRAME_API_TOKEN_FILE = previousTokenFile;
    }
    if (previousDataDir === undefined) {
      delete process.env.FRAME_DATA_DIR;
    } else {
      process.env.FRAME_DATA_DIR = previousDataDir;
    }
  });

  it("reads the token file on every call so a rotation is picked up", () => {
    fs.writeFileSync(tokenFile, "first-token\n", "utf8");
    expect(readApiToken()).toBe("first-token");

    fs.writeFileSync(tokenFile, "second-token", "utf8");
    expect(readApiToken()).toBe("second-token");
  });

  it("falls back to FRAME_DATA_DIR/api-token", () => {
    delete process.env.FRAME_API_TOKEN_FILE;
    process.env.FRAME_DATA_DIR = directory;
    fs.writeFileSync(tokenFile, "dir-token", "utf8");

    expect(readApiToken()).toBe("dir-token");
  });

  it("returns null when the token file is missing or empty", () => {
    expect(readApiToken()).toBeNull();
    fs.writeFileSync(tokenFile, "   \n", "utf8");
    expect(readApiToken()).toBeNull();
  });

  it("forwards the current token once through request header overrides", () => {
    fs.writeFileSync(tokenFile, "runtime-token", "utf8");
    const request = new NextRequest("http://localhost:3000/api/v1/config");

    const response = proxy(request);

    expect(response.headers.get("x-middleware-request-x-frame-token")).toBe("runtime-token");
    expect(response.headers.get("x-middleware-override-headers")).toContain("x-frame-token");
  });

  it("strips a client-supplied token when no token file is available", () => {
    const request = new NextRequest("http://localhost:3000/api/v1/config", {
      headers: {
        "X-FRAME-Token": "forged-by-client",
        Accept: "application/json",
      },
    });

    const response = proxy(request);

    const overrides = response.headers.get("x-middleware-override-headers") ?? "";
    expect(response.headers.get("x-middleware-request-x-frame-token")).toBeNull();
    expect(overrides).toContain("accept");
    expect(overrides).not.toContain("x-frame-token");
    expect(response.headers.get("x-middleware-request-accept")).toBe("application/json");
  });

  it("passes through unchanged when no token is available and none was supplied", () => {
    const request = new NextRequest("http://localhost:3000/api/v1/config");

    const response = proxy(request);

    expect(response.headers.get("x-middleware-override-headers")).toBeNull();
  });

  it("overwrites a client-supplied token with the file token", () => {
    fs.writeFileSync(tokenFile, "runtime-token", "utf8");
    const request = new NextRequest("http://localhost:3000/api/v1/config", {
      headers: { "X-FRAME-Token": "forged-by-client" },
    });

    const response = proxy(request);

    expect(response.headers.get("x-middleware-request-x-frame-token")).toBe("runtime-token");
  });

  it("redirects the root to onboarding when no completion marker exists", () => {
    process.env.FRAME_DATA_DIR = directory;
    const request = new NextRequest("http://localhost:3000/");

    const response = proxy(request);

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/welcome");
  });

  it("serves the root once onboarding is complete", () => {
    process.env.FRAME_DATA_DIR = directory;
    fs.writeFileSync(
      path.join(directory, "onboarding.json"),
      JSON.stringify({ version: 1, completed: true }),
      "utf8",
    );
    const request = new NextRequest("http://localhost:3000/");

    const response = proxy(request);

    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("x-middleware-next")).toBe("1");
    expect(response.headers.get("x-middleware-request-x-frame-token")).toBeNull();
  });

  it("allows the root with a session-only fallback cookie", () => {
    process.env.FRAME_DATA_DIR = directory;
    const request = new NextRequest("http://localhost:3000/", {
      headers: { cookie: `${ONBOARDING_SESSION_COOKIE}=1` },
    });

    const response = proxy(request);

    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("does not accept a forged fallback cookie value", () => {
    process.env.FRAME_DATA_DIR = directory;
    const request = new NextRequest("http://localhost:3000/", {
      headers: { cookie: `${ONBOARDING_SESSION_COOKIE}=yes` },
    });

    const response = proxy(request);

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/welcome");
  });

  it("treats a corrupt completion marker as incomplete", () => {
    process.env.FRAME_DATA_DIR = directory;
    fs.writeFileSync(path.join(directory, "onboarding.json"), "{", "utf8");
    const request = new NextRequest("http://localhost:3000/");

    const response = proxy(request);

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/welcome");
  });

  it("does not gate API requests", () => {
    process.env.FRAME_DATA_DIR = directory;
    const request = new NextRequest("http://localhost:3000/api/v1/config");

    const response = proxy(request);

    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("matches the root and /api/v1 paths", () => {
    expect(config.matcher).toEqual(["/", "/api/v1/:path*", "/api/v1"]);
  });
});
