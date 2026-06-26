import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ErrorBoundary from "@/app/error";
import NotFound from "@/app/not-found";
import { Badge } from "@/components/ui/badge";

describe("error boundary", () => {
  it("shows the error message and calls reset when retried", () => {
    const reset = vi.fn();
    render(<ErrorBoundary error={new Error("boom happened")} reset={reset} />);

    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText(/boom happened/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(reset).toHaveBeenCalledOnce();
  });
});

describe("not-found page", () => {
  it("renders the 404 state with a link back to the dashboard", () => {
    render(<NotFound />);
    expect(screen.getByText(/404 — Not Found/i)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /back to dashboard/i });
    expect(link).toHaveAttribute("href", "/dashboard");
  });
});

describe("Badge", () => {
  it("applies the variant for a known category and falls back otherwise", () => {
    const { rerender } = render(<Badge variant="answered">answered</Badge>);
    expect(screen.getByText("answered").className).toContain("emerald");

    rerender(<Badge variant="totally-unknown">x</Badge>);
    expect(screen.getByText("x").className).toContain("text-sub");
  });
});
