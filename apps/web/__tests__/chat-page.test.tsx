import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const apiMock = vi.fn();
vi.mock("@/lib/api", () => ({
  api: (...args: unknown[]) => apiMock(...args),
  apiOr: vi.fn(async (_p: string, fallback: unknown) => fallback),
  apiUrl: (p: string) => p,
}));

import ChatPage from "@/app/chat/page";

describe("Chat page", () => {
  beforeEach(() => apiMock.mockReset());

  it("shows suggestions before any conversation starts", () => {
    render(<ChatPage />);
    expect(screen.getByText("Ask EvoMind")).toBeInTheDocument();
    expect(screen.getByText(/Start a conversation/i)).toBeInTheDocument();
  });

  it("sends a message and renders the grounded reply with a citation link", async () => {
    apiMock.mockResolvedValueOnce({
      conversation_id: "conv-1",
      message_id: "m-1",
      answer: "The corpus is about testing.",
      confidence: 0.77,
      citations: [{ document_id: "doc-9", title: "Doc Nine", page: 3, snippet: "evidence" }],
    });

    render(<ChatPage />);
    const box = screen.getByLabelText("Message");
    fireEvent.change(box, { target: { value: "What is the corpus about?" } });
    fireEvent.submit(box.closest("form")!);

    // user message shows immediately
    expect(screen.getByText("What is the corpus about?")).toBeInTheDocument();

    // assistant reply + citation link render after the mocked API resolves
    await waitFor(() =>
      expect(screen.getByText("The corpus is about testing.")).toBeInTheDocument(),
    );
    const cite = screen.getByRole("link", { name: /Doc Nine · p\.3/i });
    expect(cite).toHaveAttribute("href", "/documents/doc-9");
    expect(screen.getByText(/confidence 77%/i)).toBeInTheDocument();

    // the second turn would reuse the conversation id from the first reply
    expect(apiMock).toHaveBeenCalledWith(
      "/chat",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
