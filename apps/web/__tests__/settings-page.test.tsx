import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const apiMock = vi.fn();
const CFG = {
  primary_provider: "nvidia",
  embedding_provider: "local",
  questions_per_doc: 10,
  recursion_depth: 2,
  autonomy_level: "balanced",
  creativity: 0.6,
  confidence_threshold: 0.55,
  autopilot_enabled: true,
};

vi.mock("@/lib/api", () => ({
  api: (...args: unknown[]) => apiMock(...args),
  apiOr: vi.fn(async (path: string, fallback: unknown) =>
    path === "/config" ? CFG : fallback,
  ),
  apiUrl: (p: string) => p,
}));

import SettingsPage from "@/app/settings/page";

describe("Settings page (writable)", () => {
  beforeEach(() => apiMock.mockReset());

  it("loads config into editable fields and saves via POST /config", async () => {
    apiMock.mockResolvedValueOnce({ config: { ...CFG, creativity: 0.9 } });
    render(<SettingsPage />);

    // the loaded creativity value appears in an editable number input
    const creativity = await screen.findByDisplayValue("0.6");
    fireEvent.change(creativity, { target: { value: "0.9" } });

    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() =>
      expect(apiMock).toHaveBeenCalledWith(
        "/config",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    // the POST body carries the edited value
    const body = JSON.parse(apiMock.mock.calls[0][1].body);
    expect(body.creativity).toBe(0.9);
    await waitFor(() => expect(screen.getByText(/applied/i)).toBeInTheDocument());
  });
});
