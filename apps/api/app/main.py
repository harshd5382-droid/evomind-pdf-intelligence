from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_oauth2_redirect_html
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from loguru import logger

from app.api.routes import router as api_router
from app.core.config import get_settings
from app.core.diagnostics import collect_runtime_diagnostics
from app.core.logging import configure_logging
from app.db import postgres
from app.modules import autopilot, folder_watcher


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    try:
        postgres.init_db()
    except Exception as e:
        logger.error("DB init failed: {}", e)

    # Recover any ingest jobs left orphaned by a previous process restart.
    # Without this, a restart mid-ingest would permanently strand pending PDFs:
    # the in-memory queue resets, but their pre-registered Documents (with
    # content_hash) would block re-ingestion via dedup.
    try:
        from app.workers.inproc_queue import recover_orphaned_jobs
        recover_orphaned_jobs()
    except Exception as e:
        logger.warning("Orphan recovery skipped: {}", e)

    # Engage the in-process autopilot — continuous research without manual triggers.
    try:
        autopilot.start()
    except Exception as e:
        logger.error("Autopilot failed to start: {}", e)

    # Engage the folder watcher — auto-ingest any PDF dropped into auto_ingest_dir.
    try:
        folder_watcher.start()
    except Exception as e:
        logger.error("Folder watcher failed to start: {}", e)

    try:
        diag = collect_runtime_diagnostics()
        logger.info(
            "EvoMind API ready (runtime={}, db={}, feed={}, vectors={}, graph={}, provider={})",
            diag["runtime_mode"],
            diag["dependencies"]["database"]["backend"],
            diag["dependencies"]["feed"]["mode"],
            diag["dependencies"]["vector_store"]["mode"],
            diag["dependencies"]["graph"]["mode"],
            settings.primary_provider,
        )
        for issue in diag["issues"]:
            logger.info("startup issue [{}]: {}", issue["level"], issue["message"])
    except Exception as e:
        logger.warning("Diagnostics snapshot failed at startup: {}", e)
    yield

    # Graceful shutdown — let the autopilot finish its current phase
    try:
        autopilot.stop()
    except Exception:
        pass
    try:
        folder_watcher.stop()
    except Exception:
        pass
    logger.info("EvoMind API shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    oauth2_redirect_url = "/docs/oauth2-redirect"
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=oauth2_redirect_url,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api")

    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        title = f"{settings.app_name} Docs"
        openapi_url = app.openapi_url or "/openapi.json"
        favicon = (
            "data:image/svg+xml;utf8,"
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
            "<rect width='64' height='64' rx='14' fill='%23030913'/>"
            "<rect x='12' y='12' width='40' height='40' rx='6' fill='none' stroke='%23C9A227' stroke-width='2' transform='rotate(45 32 32)'/>"
            "<rect x='18' y='18' width='28' height='28' rx='4' fill='rgba(201,162,39,0.18)' stroke='%232C4E7B' stroke-width='1.5'/>"
            "</svg>"
        )
        html = f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
    <link rel="icon" href="{favicon}" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Spectral:wght@400;600;700&display=swap" rel="stylesheet" />
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
    <style>
      :root {{
        color-scheme: dark;
        --bg: #030913;
        --panel: rgba(7, 18, 32, 0.9);
        --panel-2: rgba(11, 25, 43, 0.92);
        --border: #1b3257;
        --border-soft: rgba(27, 50, 87, 0.42);
        --ink: #dce8f5;
        --sub: #91aac7;
        --dim: #5c7696;
        --accent: #c9a227;
        --accent-2: #5cc9f5;
        --ok: #34d399;
      }}

      * {{
        box-sizing: border-box;
      }}

      html, body {{
        margin: 0;
        min-height: 100%;
        background-color: var(--bg);
        background-image:
          linear-gradient(rgba(27, 50, 87, 0.28) 1px, transparent 1px),
          linear-gradient(90deg, rgba(27, 50, 87, 0.28) 1px, transparent 1px),
          radial-gradient(circle at top right, rgba(92, 201, 245, 0.12), transparent 28%),
          radial-gradient(circle at top left, rgba(201, 162, 39, 0.12), transparent 24%);
        background-size: 48px 48px, 48px 48px, auto, auto;
        color: var(--ink);
        font-family: "JetBrains Mono", monospace;
      }}

      body {{
        position: relative;
      }}

      body::before {{
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        background:
          linear-gradient(180deg, rgba(3, 9, 19, 0.22) 0%, rgba(3, 9, 19, 0.6) 100%),
          radial-gradient(circle at 20% 0%, rgba(201, 162, 39, 0.1), transparent 30%);
      }}

      .docs-shell {{
        position: relative;
        z-index: 1;
        min-height: 100vh;
      }}

      .docs-topbar {{
        display: grid;
        grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
        gap: 20px;
        padding: 28px 28px 16px;
      }}

      .brand-card,
      .meta-card {{
        background: var(--panel);
        border: 1px solid var(--border);
        backdrop-filter: blur(16px);
        box-shadow: 0 24px 80px rgba(0, 0, 0, 0.32);
      }}

      .brand-card {{
        padding: 24px 26px;
        position: relative;
        overflow: hidden;
      }}

      .brand-card::after {{
        content: "";
        position: absolute;
        inset: auto -10% -60% auto;
        width: 280px;
        height: 280px;
        background: radial-gradient(circle, rgba(201, 162, 39, 0.22), transparent 60%);
        filter: blur(12px);
        pointer-events: none;
      }}

      .brand-mark {{
        width: 44px;
        height: 44px;
        position: relative;
        flex-shrink: 0;
      }}

      .brand-mark::before,
      .brand-mark::after {{
        content: "";
        position: absolute;
        inset: 0;
      }}

      .brand-mark::before {{
        border: 1px solid rgba(201, 162, 39, 0.72);
        transform: rotate(45deg);
      }}

      .brand-mark::after {{
        inset: 7px;
        border: 1px solid rgba(92, 201, 245, 0.34);
        background: rgba(201, 162, 39, 0.14);
      }}

      .brand-row {{
        display: flex;
        align-items: center;
        gap: 16px;
      }}

      .brand-title {{
        margin: 0;
        font-family: "Spectral", serif;
        font-size: 2.35rem;
        font-weight: 600;
        letter-spacing: -0.03em;
        color: #f7fbff;
      }}

      .brand-subtitle {{
        margin: 8px 0 0;
        color: var(--sub);
        font-size: 0.78rem;
        line-height: 1.7;
        max-width: 68ch;
      }}

      .eyebrow,
      .meta-label {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        text-transform: uppercase;
        letter-spacing: 0.22em;
        font-size: 0.62rem;
        color: var(--accent);
      }}

      .eyebrow::before,
      .meta-label::before {{
        content: "";
        width: 8px;
        height: 8px;
        border-radius: 999px;
        background: var(--ok);
        box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.55);
        animation: pulse 2.4s ease-in-out infinite;
      }}

      .meta-card {{
        padding: 18px 20px;
        display: grid;
        align-content: start;
        gap: 14px;
      }}

      .meta-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 14px 16px;
      }}

      .meta-value {{
        color: var(--ink);
        font-size: 0.92rem;
      }}

      .meta-small {{
        color: var(--dim);
        font-size: 0.72rem;
        line-height: 1.6;
      }}

      .quick-links {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 14px;
      }}

      .quick-link {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 14px;
        border: 1px solid rgba(27, 50, 87, 0.72);
        background: rgba(3, 9, 19, 0.58);
        color: var(--ink);
        text-decoration: none;
        font-size: 0.73rem;
        transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
      }}

      .quick-link:hover {{
        transform: translateY(-1px);
        border-color: rgba(201, 162, 39, 0.48);
        background: rgba(201, 162, 39, 0.08);
      }}

      #swagger-ui {{
        position: relative;
        z-index: 1;
        padding: 0 28px 28px;
      }}

      .swagger-ui {{
        color: var(--ink);
        font-family: "JetBrains Mono", monospace;
      }}

      .swagger-ui .topbar {{
        display: none;
      }}

      .swagger-ui .info {{
        margin: 0 0 24px;
        padding: 22px 24px 10px;
        background: var(--panel);
        border: 1px solid var(--border);
        box-shadow: 0 24px 80px rgba(0, 0, 0, 0.22);
      }}

      .swagger-ui .info .title {{
        font-family: "Spectral", serif;
        color: #f7fbff;
        font-size: 2rem;
        font-weight: 600;
      }}

      .swagger-ui .info p,
      .swagger-ui .info li,
      .swagger-ui .info a {{
        color: var(--sub);
      }}

      .swagger-ui .scheme-container {{
        background: transparent;
        box-shadow: none;
        padding: 0;
        margin: 0 0 18px;
      }}

      .swagger-ui .opblock-tag {{
        background: rgba(7, 18, 32, 0.92);
        border: 1px solid var(--border);
        margin: 0 0 12px;
        padding: 14px 18px;
      }}

      .swagger-ui .opblock-tag:hover {{
        background: rgba(11, 25, 43, 0.94);
      }}

      .swagger-ui .opblock {{
        border-width: 1px;
        border-radius: 0;
        box-shadow: none;
        background: rgba(7, 18, 32, 0.94);
      }}

      .swagger-ui .opblock .opblock-summary {{
        border-color: rgba(27, 50, 87, 0.45);
      }}

      .swagger-ui .opblock-description-wrapper p,
      .swagger-ui .opblock-external-docs-wrapper p,
      .swagger-ui .opblock-title_normal p,
      .swagger-ui .response-col_description__inner p,
      .swagger-ui .response-col_description__inner div,
      .swagger-ui .tab li,
      .swagger-ui label,
      .swagger-ui .parameter__name,
      .swagger-ui .parameter__type,
      .swagger-ui .response-col_status,
      .swagger-ui .responses-inner h4,
      .swagger-ui table thead tr td,
      .swagger-ui table thead tr th {{
        color: var(--ink);
      }}

      .swagger-ui .btn {{
        border-radius: 0;
        box-shadow: none;
        font-family: "JetBrains Mono", monospace;
        text-transform: uppercase;
        letter-spacing: 0.14em;
        font-size: 0.66rem;
      }}

      .swagger-ui .btn.execute {{
        background: linear-gradient(90deg, rgba(92, 201, 245, 0.16), rgba(201, 162, 39, 0.18));
        border-color: rgba(92, 201, 245, 0.48);
        color: #f7fbff;
      }}

      .swagger-ui .btn.authorize {{
        border-color: rgba(201, 162, 39, 0.54);
        color: var(--accent);
      }}

      .swagger-ui input,
      .swagger-ui textarea,
      .swagger-ui select {{
        background: rgba(3, 9, 19, 0.72);
        border: 1px solid rgba(27, 50, 87, 0.72);
        color: var(--ink);
        border-radius: 0;
      }}

      .swagger-ui .model-box,
      .swagger-ui section.models {{
        background: rgba(7, 18, 32, 0.94);
        border: 1px solid var(--border);
      }}

      .swagger-ui .model-title,
      .swagger-ui section.models h4 {{
        color: #f7fbff;
      }}

      .swagger-ui .response-control-media-type__accept-message {{
        color: var(--dim);
      }}

      .swagger-ui .markdown code,
      .swagger-ui code,
      .swagger-ui pre {{
        background: rgba(3, 9, 19, 0.78);
        color: #c6dcf2;
      }}

      .footer-note {{
        padding: 0 28px 24px;
        color: var(--dim);
        font-size: 0.7rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }}

      @keyframes pulse {{
        0%, 100% {{ box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.55); }}
        50% {{ box-shadow: 0 0 0 6px rgba(52, 211, 153, 0); }}
      }}

      @media (max-width: 980px) {{
        .docs-topbar {{
          grid-template-columns: 1fr;
          padding: 20px 20px 12px;
        }}

        #swagger-ui {{
          padding: 0 20px 20px;
        }}

        .brand-title {{
          font-size: 1.85rem;
        }}

        .meta-grid {{
          grid-template-columns: 1fr;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="docs-shell">
      <div class="docs-topbar">
        <section class="brand-card">
          <div class="eyebrow">Live API Surface</div>
          <div class="brand-row" style="margin-top: 14px;">
            <div class="brand-mark"></div>
            <div>
              <h1 class="brand-title">EvoMind API Docs</h1>
              <p class="brand-subtitle">
                Research-loop infrastructure, ingestion pipelines, autonomous orchestration, memory, graph,
                diagnostics, and live feed endpoints in one operator-friendly surface.
              </p>
            </div>
          </div>
          <div class="quick-links">
            <a class="quick-link" href="/api/health" target="_blank" rel="noreferrer">Health</a>
            <a class="quick-link" href="/api/diagnostics" target="_blank" rel="noreferrer">Diagnostics</a>
            <a class="quick-link" href="/api/feed/recent?limit=10" target="_blank" rel="noreferrer">Recent Feed</a>
            <a class="quick-link" href="/api/autopilot/status" target="_blank" rel="noreferrer">Autopilot</a>
          </div>
        </section>
        <aside class="meta-card">
          <div class="meta-label">Runtime Notes</div>
          <div class="meta-grid">
            <div>
              <div class="meta-small">OpenAPI</div>
              <div class="meta-value">{openapi_url}</div>
            </div>
            <div>
              <div class="meta-small">Version</div>
              <div class="meta-value">{app.version}</div>
            </div>
            <div>
              <div class="meta-small">Auth Flow</div>
              <div class="meta-value">Swagger UI</div>
            </div>
            <div>
              <div class="meta-small">Theme</div>
              <div class="meta-value">EvoMind Operator Dark</div>
            </div>
          </div>
          <div class="meta-small">
            Use the schema explorer below for live request testing. The custom shell only changes presentation;
            your routes, payloads, and OpenAPI output remain untouched.
          </div>
        </aside>
      </div>
      <div id="swagger-ui"></div>
      <div class="footer-note">EvoMind PDF Intelligence · autonomous research loop documentation</div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
    <script>
      window.ui = SwaggerUIBundle({{
        url: "{openapi_url}",
        dom_id: "#swagger-ui",
        deepLinking: true,
        docExpansion: "list",
        defaultModelsExpandDepth: 2,
        defaultModelExpandDepth: 2,
        displayRequestDuration: true,
        filter: true,
        persistAuthorization: true,
        showExtensions: true,
        showCommonExtensions: true,
        syntaxHighlight: {{
          activate: true,
          theme: "nord"
        }},
        oauth2RedirectUrl: window.location.origin + "{oauth2_redirect_url}",
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIStandalonePreset
        ],
        layout: "BaseLayout"
      }});
    </script>
  </body>
</html>"""
        return HTMLResponse(html)

    @app.get(oauth2_redirect_url, include_in_schema=False)
    async def swagger_ui_redirect():
        return get_swagger_ui_oauth2_redirect_html()

    return app


app = create_app()
