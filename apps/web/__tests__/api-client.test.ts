import { afterEach, describe, expect, it, vi } from "vitest";

// lib/api reads NEXT_PUBLIC_API_KEY at module load, so each test sets the env
// first and then imports a fresh copy of the module.
async function freshApi(key: string | undefined) {
  vi.resetModules();
  if (key === undefined) delete process.env.NEXT_PUBLIC_API_KEY;
  else process.env.NEXT_PUBLIC_API_KEY = key;
  return import("@/lib/api");
}

describe("api client auth headers", () => {
  afterEach(() => {
    delete process.env.NEXT_PUBLIC_API_KEY;
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("attaches X-API-Key when NEXT_PUBLIC_API_KEY is set", async () => {
    const { api, authHeaders } = await freshApi("secret-key");
    expect(authHeaders()).toEqual({ "X-API-Key": "secret-key" });

    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api("/health");

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.headers).toMatchObject({ "X-API-Key": "secret-key" });
  });

  it("sends no auth header when NEXT_PUBLIC_API_KEY is unset", async () => {
    const { api, authHeaders } = await freshApi(undefined);
    expect(authHeaders()).toEqual({});

    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api("/health");

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.headers).not.toHaveProperty("X-API-Key");
  });

  it("lets per-call headers override the baked-in key", async () => {
    const { api } = await freshApi("secret-key");

    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api("/health", { headers: { "X-API-Key": "override" } });

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.headers).toMatchObject({ "X-API-Key": "override" });
  });
});
