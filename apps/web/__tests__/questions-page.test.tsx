import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// Mock the HTTP client so the page renders without a backend. apiOr returns
// the fallback we hand it; api is unused on initial render.
vi.mock("@/lib/api", () => ({
  api: vi.fn(),
  apiOr: vi.fn(async (_path: string, fallback: unknown) => fallback),
  apiUrl: (p: string) => p,
}));

import QuestionsPage from "@/app/questions/page";

describe("Questions page", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the header and the empty state when no questions exist", async () => {
    render(<QuestionsPage />);
    expect(screen.getByText("Question Tree")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/No questions yet/i)).toBeInTheDocument(),
    );
  });
});
