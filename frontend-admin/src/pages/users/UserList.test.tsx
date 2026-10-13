import { render, screen, waitFor } from "@testing-library/react";
import { Refine } from "@refinedev/core";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { dataProvider } from "@/providers/dataProvider";
import { UserList } from "./UserList";

type Call = { url: string; method: string; body: unknown };

const setupFetch = () => {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    return new Response(JSON.stringify({ data: [], total: 0 }), { status: 200 });
  });
  return calls;
};

const renderList = (entry = "/users") =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Refine dataProvider={dataProvider} resources={[{ name: "users", list: "/users" }]}>
        <UserList />
      </Refine>
    </MemoryRouter>,
  );

afterEach(() => {
  vi.restoreAllMocks();
});

describe("UserList · URL 预填", () => {
  it("URL ?q= 预填过滤", async () => {
    const calls = setupFetch();
    renderList("/users?q=预填词");
    expect(screen.getByDisplayValue("预填词")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        calls.some((c) => c.method === "GET" && decodeURIComponent(c.url).includes("q=预填词")),
      ).toBe(true),
    );
  });
});
