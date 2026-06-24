const baseWeb = process.env.SMOKE_WEB_URL || "http://localhost:3000";
const baseApi = process.env.SMOKE_API_URL || "http://localhost:8000";

const pagePaths = ["/dashboard", "/feed", "/questions", "/memory", "/reports", "/graph", "/settings"];
const apiPaths = ["/api/health", "/api/diagnostics", "/api/documents", "/api/feed/recent?limit=5"];

async function fetchText(url) {
  const res = await fetch(url, { cache: "no-store" });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`${url} -> ${res.status}`);
  }
  return text;
}

for (const path of apiPaths) {
  await fetchText(`${baseApi}${path}`);
}

for (const path of pagePaths) {
  const html = await fetchText(`${baseWeb}${path}`);
  if (/Internal Server Error|hydration mismatch|API 500/i.test(html)) {
    throw new Error(`Smoke failure on ${path}: unexpected error text in HTML.`);
  }
}

const docs = JSON.parse(await fetchText(`${baseApi}/api/documents`));
if (Array.isArray(docs) && docs.length > 0) {
  const detail = await fetchText(`${baseWeb}/documents/${docs[0].id}`);
  if (/Internal Server Error|API 500/i.test(detail)) {
    throw new Error("Document detail page returned an error state.");
  }
}

console.log("Web smoke passed.");
