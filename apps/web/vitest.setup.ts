import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement scrollTo; the chat view calls it on its scroll
// container. Stub it so components that auto-scroll don't throw under test.
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => {};
}
