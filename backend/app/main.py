from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.core.database import init_db
from app.api.v1 import auth, chat, agent, health, memory, gateway, task, integrations
from app.services.task_worker import task_worker

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="DOTMIND — Mobile-First Personal AI Agent API inspired by OpenAI Dots.",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS Middleware for mobile apps & web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if settings.CORS_ORIGINS else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    await init_db()
    await task_worker.start()

@app.on_event("shutdown")
async def on_shutdown():
    await task_worker.stop()

# Mount API Routers
app.include_router(health.router)
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(chat.router, prefix=settings.API_V1_STR)
app.include_router(agent.router, prefix=settings.API_V1_STR)
app.include_router(memory.router, prefix=settings.API_V1_STR)
app.include_router(gateway.router, prefix=settings.API_V1_STR)
app.include_router(task.router, prefix=settings.API_V1_STR)
app.include_router(integrations.router, prefix=settings.API_V1_STR)

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse

@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /docs\n"
        "Allow: /redoc\n"
        "Allow: /llms.txt\n"
        "Allow: /sitemap.xml\n"
        "Disallow: /api/v1/auth/\n"
        "Sitemap: http://localhost:8000/sitemap.xml\n"
    )

@app.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt():
    return """# DOTMIND — Always-On Personal AI Agent
> Mobile-First, Context-Aware Personal AI Agent inspired by OpenAI Dots.

## Core Capabilities
- **Always-On Autonomous Engine**: Decomposes user goals into actionable plans and runs steps in the background.
- **Task Center**: Visual tracking of In Progress, Scheduled, Waiting for Approval, Completed, and Paused tasks.
- **Human Approvals**: Consequential file and workspace actions pause at approval gates for explicit human authorization.
- **Stream Isolation**: Real-time SSE streaming enriched with conversation_id to prevent cross-chat data leakage.
- **Persistent Memory**: Structured long-term knowledge store across conversations with user-scoped isolation.
- **Multimodal Gateway**: Google Gemini Flash, Pro, and Live inference with error sanitization and quota backoff.
- **Connected Workspace**: Scoped filesystem sandbox, Node.js GenAI microservice, web researcher, and GitHub VCS.

## Key Endpoints
- `/docs`: OpenAPI Swagger Documentation
- `/api/v1/tasks`: Task planning, execution, and approval management
- `/api/v1/integrations`: Connected tools and workspace status
- `/api/v1/memory`: Long-term memory storage
- `/api/v1/chat/stream`: Real-time streaming conversation
- `/download/dotmind-debug.apk`: Android client APK download
- `/download/dotmind-project.zip`: Project source archive
"""

@app.get("/sitemap.xml")
async def sitemap_xml():
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>http://localhost:8000/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>http://localhost:8000/docs</loc>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>http://localhost:8000/redoc</loc>
    <changefreq>weekly</changefreq>
    <priority>0.7</priority>
  </url>
  <url>
    <loc>http://localhost:8000/llms.txt</loc>
    <changefreq>weekly</changefreq>
    <priority>0.9</priority>
  </url>
</urlset>"""
    return Response(content=xml_content, media_type="application/xml")

@app.get("/")
async def root(request: Request):
    accept_header = request.headers.get("accept", "")
    if "text/html" in accept_header:
        html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="DOTMIND is an always-on mobile personal AI agent inspired by OpenAI Dots, featuring autonomous background tasks, human approval gates, multimodal vision, and persistent memory.">
    <meta name="robots" content="index, follow">
    <link rel="canonical" href="http://localhost:8000/">
    
    <!-- Open Graph / Facebook -->
    <meta property="og:type" content="website">
    <meta property="og:url" content="http://localhost:8000/">
    <meta property="og:title" content="DOTMIND — Mobile Always-On Personal AI Agent">
    <meta property="og:description" content="Autonomous background task engine, human-in-the-loop approval gates, multimodal vision, and persistent long-term memory.">
    <meta property="og:site_name" content="DOTMIND">
    
    <!-- Twitter -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="DOTMIND — Mobile Always-On Personal AI Agent">
    <meta name="twitter:description" content="Autonomous background task engine, human-in-the-loop approval gates, multimodal vision, and persistent long-term memory.">

    <!-- Schema.org JSON-LD Structured Data -->
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "SoftwareApplication",
      "name": "DOTMIND",
      "applicationCategory": "BusinessApplication",
      "operatingSystem": "Android, Linux",
      "offers": {
        "@type": "Offer",
        "price": "0",
        "priceCurrency": "USD"
      },
      "description": "Mobile-first, context-aware always-on personal AI agent inspired by OpenAI Dots.",
      "softwareVersion": "1.0.0",
      "creator": {
        "@type": "Organization",
        "name": "DotMind Team"
      }
    }
    </script>

    <title>DOTMIND — Always-On Personal AI Agent</title>
    <style>
        :root {
            --bg: #090A0F;
            --surface: #131722;
            --card: #1B202E;
            --border: #282F44;
            --primary: #6366F1;
            --cyan: #06B6D4;
            --text-primary: #F1F5F9;
            --text-secondary: #94A3B8;
            --success: #10B981;
            --warning: #F59E0B;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text-primary);
            line-height: 1.6;
            padding: 2rem 1rem;
        }
        .container { max-width: 860px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 2.5rem; }
        .badge {
            display: inline-block;
            background: rgba(99, 102, 241, 0.15);
            color: var(--primary);
            font-size: 0.85rem;
            font-weight: 600;
            padding: 0.35rem 0.85rem;
            border-radius: 9999px;
            margin-bottom: 1rem;
            border: 1px solid rgba(99, 102, 241, 0.3);
        }
        h1 { font-size: 2.4rem; font-weight: 800; margin-bottom: 0.75rem; letter-spacing: -0.02em; }
        p.subtitle { color: var(--text-secondary); font-size: 1.15rem; max-width: 650px; margin: 0 auto; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1.25rem; margin: 2.5rem 0; }
        .card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 1.5rem;
            transition: border-color 0.2s;
        }
        .card:hover { border-color: var(--primary); }
        .card h2 { font-size: 1.2rem; margin-bottom: 0.5rem; color: var(--cyan); }
        .card p { color: var(--text-secondary); font-size: 0.95rem; }
        .actions { text-align: center; margin: 2.5rem 0; display: flex; justify-content: center; gap: 1rem; flex-wrap: wrap; }
        .btn {
            display: inline-flex;
            align-items: center;
            padding: 0.8rem 1.5rem;
            border-radius: 10px;
            font-weight: 600;
            text-decoration: none;
            font-size: 0.95rem;
            transition: opacity 0.2s;
        }
        .btn-primary { background: var(--primary); color: #fff; }
        .btn-secondary { background: var(--surface); color: var(--text-primary); border: 1px solid var(--border); }
        .btn:hover { opacity: 0.9; }
        footer { text-align: center; color: var(--text-secondary); font-size: 0.85rem; border-top: 1px solid var(--border); padding-top: 2rem; margin-top: 3rem; }
        footer a { color: var(--primary); text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <span class="badge">OpenAI Dots Architecture Parity</span>
            <h1>DOTMIND Personal AI Agent</h1>
            <p class="subtitle">Mobile-first, context-aware always-on AI agent with autonomous background planning, human-in-the-loop approval gates, multimodal vision, and persistent memory.</p>
        </header>

        <main>
            <div class="actions">
                <a href="/download/dotmind-debug.apk" class="btn btn-primary">📱 Download Android APK</a>
                <a href="/download/dotmind-cloud-server.zip" class="btn btn-secondary">☁️ Download 24/7 Cloud Server ZIP</a>
                <a href="/download/dotmind-project.zip" class="btn btn-secondary">📦 Download Source ZIP</a>
                <a href="/docs" class="btn btn-secondary">⚡ Interactive API Docs</a>
            </div>


            <section class="grid">
                <article class="card">
                    <h2>Always-On Task Center</h2>
                    <p>Decomposes user objectives into multi-step execution plans. Runs in background loops across active and closed chat sessions.</p>
                </article>
                <article class="card">
                    <h2>Human Approval Gates</h2>
                    <p>Consequential actions like file writes, code executions, and workspace alterations pause for explicit user authorization before execution.</p>
                </article>
                <article class="card">
                    <h2>Stream & Tenant Isolation</h2>
                    <p>SSE streams enriched with conversation IDs protect against cross-chat data leakage. Multi-tenant database tenancy prevents cross-user exposure.</p>
                </article>
                <article class="card">
                    <h2>Multimodal Vision & Files</h2>
                    <p>Direct camera capture, gallery selection, document uploads, and code analysis powered by @google/genai inline multimodal parts.</p>
                </article>
                <article class="card">
                    <h2>Persistent Memory Store</h2>
                    <p>Remembers user preferences, project context, facts, and decisions across all conversations with category indexing and semantic search.</p>
                </article>
                <article class="card">
                    <h2>Connected Workspace Sandbox</h2>
                    <p>Path-traversal defended filesystem sandbox, Node.js GenAI microservice, web researcher, and GitHub VCS integration.</p>
                </article>
            </section>
        </main>

        <footer>
            <p>DOTMIND Engine v1.0.0 • Verified Credentials & Open APIs • <a href="/llms.txt">AI Search Citation (llms.txt)</a> • <a href="/sitemap.xml">XML Sitemap</a> • <a href="/redoc">ReDoc</a></p>
        </footer>
    </div>
</body>
</html>"""
        return HTMLResponse(content=html_content)

    return {
        "message": "Welcome to DOTMIND Mobile Personal AI Agent Backend",
        "docs": "/docs",
        "health": "/health",
        "llms_txt": "/llms.txt",
        "robots_txt": "/robots.txt",
        "sitemap_xml": "/sitemap.xml",
        "download_apk": "/download/dotmind-debug.apk",
        "download_project": "/download/dotmind-project.zip",
        "version": settings.VERSION
    }

@app.api_route("/download/dotmind-project.zip", methods=["GET", "HEAD"])
async def download_project_zip():
    from fastapi.responses import FileResponse
    import os
    candidates = [
        "/sdcard/Download/antigem/dotmind-project.zip",
        "/sdcard/Download/dotmind-project.zip"
    ]
    for zip_path in candidates:
        if os.path.exists(zip_path):
            return FileResponse(
                path=zip_path,
                filename="dotmind-project.zip",
                media_type="application/zip"
            )
    return {"error": "Project archive not found."}

@app.api_route("/download/dotmind-debug.apk", methods=["GET", "HEAD"])
async def download_debug_apk():
    from fastapi.responses import FileResponse
    import os
    candidates = [
        "/sdcard/Download/antigem/dotmind-debug.apk",
        "/sdcard/Download/dotmind-debug.apk",
        os.path.join(settings.WORKSPACE_ROOT, "android", "app", "build", "outputs", "apk", "debug", "app-debug.apk")
    ]
    for apk_path in candidates:
        if os.path.exists(apk_path):
            return FileResponse(
                path=apk_path,
                filename="dotmind-debug.apk",
                media_type="application/vnd.android.package-archive"
            )
    return {"error": "APK build artifact not found."}

@app.api_route("/download/dotmind-cloud-server.zip", methods=["GET", "HEAD"])
async def download_cloud_server_zip():
    from fastapi.responses import FileResponse
    import os
    candidates = [
        "/sdcard/Download/antigem/dotmind-cloud-server.zip",
        "/sdcard/Download/dotmind-cloud-server.zip"
    ]
    for zip_path in candidates:
        if os.path.exists(zip_path):
            return FileResponse(
                path=zip_path,
                filename="dotmind-cloud-server.zip",
                media_type="application/zip"
            )
    return {"error": "Cloud server archive not found."}



