import os
import time
import re
import socket
import ipaddress
import base64
import asyncio
import difflib
import fnmatch
from urllib.parse import urlparse, urljoin, quote_plus
from typing import Dict, Any, List, Optional, Callable
import httpx
from pydantic import BaseModel, Field

from app.config import settings

class ToolResult(BaseModel):
    tool_name: str
    status: str = Field(..., description="'succeeded', 'failed', 'needs_approval', 'cancelled'")
    output: Any
    latency_ms: int = 0
    error: Optional[str] = None

class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    permission_level: str = "SAFE_EXECUTE" # "READ_ONLY", "SAFE_EXECUTE", "NEEDS_APPROVAL"
    timeout_seconds: float = 15.0

# ----------------- SECURITY UTILITIES ----------------- #

FORBIDDEN_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata.google",
    "instance-data",
    "169.254.169.254",
    "0.0.0.0",
}

def validate_safe_url(url: str) -> str:
    """
    Validates user-supplied URLs to protect against Server-Side Request Forgery (SSRF).
    Blocks loopback (127.0.0.0/8, ::1), private IP blocks (RFC 1918), link-local addresses,
    cloud metadata endpoints (169.254.169.254), and unsupported schemes.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string.")

    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    if scheme not in ["http", "https"]:
        raise ValueError(f"SSRF protection: Scheme '{scheme}' is prohibited. Only HTTP and HTTPS are permitted.")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("SSRF protection: URL must include a valid hostname.")

    if hostname in FORBIDDEN_HOSTNAMES:
        raise ValueError(f"SSRF blocked: Destination '{hostname}' is an internal/cloud-metadata endpoint.")

    # DNS resolution and IP range validation
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise ValueError(f"SSRF protection: Failed to resolve hostname '{hostname}': {str(e)}")

    for item in addr_info:
        ip_str = item[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
            if (
                ip.is_loopback
                or ip.is_private
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise ValueError(
                    f"SSRF blocked: Hostname '{hostname}' resolves to restricted IP {ip_str}."
                )
        except ValueError as ve:
            if "SSRF blocked" in str(ve):
                raise
            raise ValueError(f"Invalid IP address format resolved for '{hostname}': {ip_str}")

    return url.strip()

def get_safe_workspace_path(subpath: str) -> str:
    """
    Canonical absolute path resolver with strict containment check via os.path.commonpath().
    Guarantees no traversal outside settings.WORKSPACE_ROOT.
    Protects against prefix bypasses (e.g. /workspace-evil), '../' traversals, and symlink escapes.
    """
    workspace_root = os.path.realpath(settings.WORKSPACE_ROOT)
    clean_subpath = (subpath or "").strip().lstrip("/\\")
    target_path = os.path.realpath(os.path.join(workspace_root, clean_subpath))

    try:
        common = os.path.commonpath([workspace_root, target_path])
        if common != workspace_root:
            raise ValueError(f"Directory traversal attempt blocked: Path traversal blocked: Access outside workspace root is prohibited. (Target: {subpath})")
    except ValueError as e:
        if "Directory traversal attempt blocked" in str(e):
            raise
        raise ValueError(f"Directory traversal attempt blocked: Path containment check failed: {str(e)}")

    return target_path

# ----------------- TOOL REGISTRY ----------------- #

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._handlers: Dict[str, Callable] = {}
        self._register_default_tools()

    def register(self, definition: ToolDefinition, handler: Callable):
        self._tools[definition.name] = definition
        self._handlers[definition.name] = handler

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        return list(self._tools.values())

    async def execute(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        if name not in self._handlers:
            return ToolResult(
                tool_name=name,
                status="failed",
                output=None,
                error=f"Tool '{name}' is not registered."
            )

        start_time = time.perf_counter()
        tool_def = self._tools[name]
        try:
            handler = self._handlers[name]
            output = await handler(arguments)
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool_name=name,
                status="succeeded",
                output=output,
                latency_ms=elapsed_ms
            )
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool_name=name,
                status="failed",
                output=None,
                latency_ms=elapsed_ms,
                error=str(e)
            )

    def _register_default_tools(self):
        # 1. GitHub Researcher
        self.register(
            ToolDefinition(
                name="github_researcher",
                description="Search public GitHub repositories or fetch README/license information via official GitHub REST API.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query for repositories"},
                        "action": {"type": "string", "enum": ["search", "readme"], "default": "search"},
                        "repo_full_name": {"type": "string", "description": "owner/repo name when action=readme"}
                    },
                    "required": ["query"]
                },
                permission_level="READ_ONLY",
                timeout_seconds=15.0
            ),
            self._handle_github_research
        )

        # 2. Project Inspector
        self.register(
            ToolDefinition(
                name="project_inspector",
                description="Inspect the local DOTMIND workspace files, stack metrics, and directory structure.",
                parameters={
                    "type": "object",
                    "properties": {
                        "subpath": {"type": "string", "default": "", "description": "Subdirectory to inspect"}
                    }
                },
                permission_level="READ_ONLY",
                timeout_seconds=5.0
            ),
            self._handle_project_inspect
        )

        # 3. File Reader
        self.register(
            ToolDefinition(
                name="file_reader",
                description="Safely read file contents within the project directory.",
                parameters={
                    "type": "object",
                    "properties": {
                        "relative_path": {"type": "string", "description": "Relative file path from project root"},
                        "max_lines": {"type": "integer", "default": 100}
                    },
                    "required": ["relative_path"]
                },
                permission_level="READ_ONLY",
                timeout_seconds=5.0
            ),
            self._handle_file_reader
        )

        # 4. SEO Analyzer
        self.register(
            ToolDefinition(
                name="seo_analyzer",
                description="Perform a comprehensive technical SEO audit of a website or HTML markup with SSRF protection.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target website URL"},
                        "html_content": {"type": "string", "description": "Raw HTML string if analyzing directly"}
                    }
                },
                permission_level="SAFE_EXECUTE",
                timeout_seconds=15.0
            ),
            self._handle_seo_analyzer
        )

        # 5. HTTP Tester
        self.register(
            ToolDefinition(
                name="http_tester",
                description="Safely test REST API endpoints, check status codes, headers, and response latency with SSRF protection.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target HTTP/HTTPS URL"},
                        "method": {"type": "string", "enum": ["GET", "POST", "HEAD"], "default": "GET"}
                    },
                    "required": ["url"]
                },
                permission_level="SAFE_EXECUTE",
                timeout_seconds=10.0
            ),
            self._handle_http_tester
        )

        # 6. File Searcher
        self.register(
            ToolDefinition(
                name="file_searcher",
                description="Search for keywords or regex patterns across workspace files with path containment.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Text query or regex pattern to search for"},
                        "file_pattern": {"type": "string", "description": "Optional glob filter, e.g. '*.py' or '*.kt'", "default": "*"},
                        "max_results": {"type": "integer", "description": "Max matching lines to return", "default": 25}
                    },
                    "required": ["query"]
                },
                permission_level="READ_ONLY",
                timeout_seconds=10.0
            ),
            self._handle_file_searcher
        )

        # 7. File Writer
        self.register(
            ToolDefinition(
                name="file_writer",
                description="Safely write or modify files within the workspace root with strict directory traversal prevention.",
                parameters={
                    "type": "object",
                    "properties": {
                        "relative_path": {"type": "string", "description": "Path relative to workspace root"},
                        "content": {"type": "string", "description": "Complete file content to write"},
                        "create_backup": {"type": "boolean", "description": "Whether to backup existing file before overwriting", "default": True}
                    },
                    "required": ["relative_path", "content"]
                },
                permission_level="SAFE_EXECUTE",
                timeout_seconds=10.0
            ),
            self._handle_file_writer
        )

        # 8. Diff Generator
        self.register(
            ToolDefinition(
                name="diff_generator",
                description="Generate unified diff comparison between an existing workspace file and proposed new content.",
                parameters={
                    "type": "object",
                    "properties": {
                        "relative_path": {"type": "string", "description": "Path relative to workspace root"},
                        "new_content": {"type": "string", "description": "New content to compare against"}
                    },
                    "required": ["relative_path", "new_content"]
                },
                permission_level="READ_ONLY",
                timeout_seconds=5.0
            ),
            self._handle_diff_generator
        )

        # 9. Test Runner
        self.register(
            ToolDefinition(
                name="test_runner",
                description="Execute real pytest test suites in the backend workspace and report actual exit code, passed/failed counts, and stdout.",
                parameters={
                    "type": "object",
                    "properties": {
                        "test_target": {"type": "string", "description": "Test file or directory to run", "default": "tests/test_phase2_security_and_tools.py"}
                    }
                },
                permission_level="SAFE_EXECUTE",
                timeout_seconds=60.0
            ),
            self._handle_test_runner
        )

        # 10. Log Inspector
        self.register(
            ToolDefinition(
                name="log_inspector",
                description="Inspect the latest execution and server logs from the workspace.",
                parameters={
                    "type": "object",
                    "properties": {
                        "log_file": {"type": "string", "description": "Log file path relative to workspace", "default": "backend/server.log"},
                        "max_lines": {"type": "integer", "description": "Number of trailing lines to inspect", "default": 50}
                    }
                },
                permission_level="READ_ONLY",
                timeout_seconds=5.0
            ),
            self._handle_log_inspector
        )

        # 11. Browser Navigator (Autonomous Web Browser)
        self.register(
            ToolDefinition(
                name="browser_navigator",
                description="Autonomous web browser: navigate web pages, extract reader-friendly text, search the web, and extract links with SSRF protection.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target webpage URL to visit"},
                        "action": {
                            "type": "string",
                            "enum": ["navigate", "extract_links", "search_web"],
                            "default": "navigate",
                            "description": "Browser action to perform"
                        },
                        "query": {"type": "string", "description": "Search query if action=search_web"}
                    }
                },
                permission_level="SAFE_EXECUTE",
                timeout_seconds=20.0
            ),
            self._handle_browser_navigator
        )

    # ---------------- HANDLER IMPLEMENTATIONS ---------------- #

    async def _handle_github_research(self, args: Dict[str, Any]) -> Dict[str, Any]:
        action = args.get("action", "search")
        query = args.get("query", "").strip()
        repo = args.get("repo_full_name", "").strip()

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "DotMind-Agent-Mobile/1.0"
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            if action == "readme" and repo:
                url = f"https://api.github.com/repos/{repo}/readme"
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("content", "")
                    decoded = base64.b64decode(content).decode('utf-8', errors='ignore')
                    return {
                        "repo": repo,
                        "readme_snippet": decoded[:1200] + ("..." if len(decoded) > 1200 else "")
                    }
                else:
                    return {"repo": repo, "error": f"GitHub API error {resp.status_code}: {resp.text[:200]}"}
            else:
                url = f"https://api.github.com/search/repositories?q={query}&per_page=5"
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    items = resp.json().get("items", [])
                    results = []
                    for item in items[:5]:
                        results.append({
                            "name": item.get("full_name"),
                            "description": item.get("description"),
                            "stars": item.get("stargazers_count"),
                            "forks": item.get("forks_count"),
                            "license": (item.get("license") or {}).get("name", "Unknown"),
                            "url": item.get("html_url")
                        })
                    return {"query": query, "total_found": len(items), "repositories": results}
                elif resp.status_code == 403:
                    return {"query": query, "error": "GitHub API rate limit exceeded. Using curated skill catalogue."}
                else:
                    return {"query": query, "error": f"GitHub API error {resp.status_code}"}

    async def _handle_project_inspect(self, args: Dict[str, Any]) -> Dict[str, Any]:
        subpath = args.get("subpath", "").strip()
        canonical_target = get_safe_workspace_path(subpath)
        canonical_root = os.path.realpath(settings.WORKSPACE_ROOT)

        if not os.path.exists(canonical_target):
            return {
                "exists": False,
                "workspace_root": canonical_root,
                "target": canonical_target,
                "error": f"Path '{subpath}' does not exist in workspace."
            }

        if os.path.isfile(canonical_target):
            file_size = os.path.getsize(canonical_target)
            return {
                "type": "file",
                "path": os.path.relpath(canonical_target, canonical_root),
                "size_bytes": file_size,
                "exists": True
            }

        entries = os.listdir(canonical_target)
        filtered = [e for e in entries if e not in [".git", ".venv", ".gradle", "build", "__pycache__", ".pytest_cache"]]
        
        # Identify key project files if at workspace root
        has_android = os.path.exists(os.path.join(canonical_root, "android", "build.gradle.kts"))
        has_backend = os.path.exists(os.path.join(canonical_root, "backend", "requirements.txt"))
        has_genai = os.path.exists(os.path.join(canonical_root, "genai-service", "package.json"))

        return {
            "type": "directory",
            "directory": os.path.relpath(canonical_target, canonical_root),
            "workspace_root": canonical_root,
            "total_items": len(filtered),
            "files_and_dirs": filtered[:30],
            "confirmed_stacks": {
                "android": "Jetpack Compose (Kotlin)" if has_android else "Not detected",
                "backend": "FastAPI (Python)" if has_backend else "Not detected",
                "genai_service": "@google/genai (Node.js)" if has_genai else "Not detected"
            }
        }

    async def _handle_file_reader(self, args: Dict[str, Any]) -> Dict[str, Any]:
        rel_path = args.get("relative_path", "").strip()
        if not rel_path:
            raise ValueError("relative_path parameter is required.")

        target_path = get_safe_workspace_path(rel_path)
        canonical_root = os.path.realpath(settings.WORKSPACE_ROOT)

        if not os.path.exists(target_path) or not os.path.isfile(target_path):
            raise FileNotFoundError(f"File '{rel_path}' does not exist in workspace.")

        max_lines = min(max(1, args.get("max_lines", 100)), 500)
        lines = []
        with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    lines.append(f"... [Truncated at {max_lines} lines]")
                    break
                lines.append(line)

        return {
            "file": os.path.relpath(target_path, canonical_root),
            "line_count": len(lines),
            "content": "".join(lines)
        }

    async def _handle_seo_analyzer(self, args: Dict[str, Any]) -> Dict[str, Any]:
        url = args.get("url")
        html = args.get("html_content")

        if url and not html:
            safe_url = validate_safe_url(url)
            # Safe HTTP fetch with SSRF redirect validation and 2MB limit
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                curr_url = safe_url
                resp = None
                for _ in range(3): # max 3 validated redirects
                    resp = await client.get(curr_url, headers={"User-Agent": "DotMind-SEO-Auditor/1.0"})
                    if resp.is_redirect and "location" in resp.headers:
                        curr_url = validate_safe_url(urljoin(curr_url, resp.headers["location"]))
                    else:
                        break
                if resp is None:
                    return {"status": "error", "message": "Failed to connect to target URL."}
                html = resp.text[:2 * 1024 * 1024]

        if not html:
            return {"status": "error", "message": "No URL or HTML content provided for SEO audit."}

        # Perform analysis on HTML
        title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else None

        desc_match = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE)
        description = desc_match.group(1).strip() if desc_match else None

        og_title = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE)
        og_image = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE)
        canonical = re.search(r'<link\s+rel=["\']canonical["\']\s+href=["\'](.*?)["\']', html, re.IGNORECASE)
        h1_tags = re.findall(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
        images = re.findall(r'<img[^>]*>', html, re.IGNORECASE)
        images_missing_alt = [img for img in images if 'alt=' not in img.lower()]

        findings = []
        score = 100
        if not title:
            score -= 20
            findings.append({"severity": "CRITICAL", "item": "Missing <title> tag."})
        elif len(title) < 30 or len(title) > 65:
            score -= 5
            findings.append({"severity": "WARNING", "item": f"Title length ({len(title)} chars) not in optimal 30-65 range."})

        if not description:
            score -= 20
            findings.append({"severity": "CRITICAL", "item": "Missing meta description."})
        elif len(description) < 70 or len(description) > 160:
            score -= 5
            findings.append({"severity": "WARNING", "item": f"Description length ({len(description)} chars) not in optimal 70-160 range."})

        if not canonical:
            score -= 10
            findings.append({"severity": "RECOMMENDATION", "item": "Missing rel=canonical link tag."})

        if len(h1_tags) == 0:
            score -= 15
            findings.append({"severity": "HIGH", "item": "No <h1> heading tag found."})
        elif len(h1_tags) > 1:
            score -= 5
            findings.append({"severity": "WARNING", "item": f"Multiple <h1> headings found ({len(h1_tags)}). Single <h1> is recommended."})

        if images_missing_alt:
            score -= 10
            findings.append({"severity": "WARNING", "item": f"{len(images_missing_alt)} image(s) missing alt attribute."})

        return {
            "seo_score": max(score, 0),
            "title": title,
            "description": description,
            "has_og_tags": bool(og_title and og_image),
            "h1_count": len(h1_tags),
            "total_images": len(images),
            "findings": findings
        }

    async def _handle_http_tester(self, args: Dict[str, Any]) -> Dict[str, Any]:
        url = args.get("url", "")
        method = args.get("method", "GET").upper()

        safe_url = validate_safe_url(url)

        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            curr_url = safe_url
            resp = None
            for _ in range(3):
                resp = await client.request(method, curr_url)
                if resp.is_redirect and "location" in resp.headers:
                    curr_url = validate_safe_url(urljoin(curr_url, resp.headers["location"]))
                else:
                    break

            elapsed_ms = int((time.perf_counter() - start) * 1000)

            return {
                "url": url,
                "status_code": resp.status_code if resp else 0,
                "latency_ms": elapsed_ms,
                "content_type": resp.headers.get("content-type", "") if resp else "",
                "response_preview": resp.text[:400] if resp else ""
            }

    async def _handle_file_searcher(self, args: Dict[str, Any]) -> Dict[str, Any]:
        query = args.get("query", "").strip()
        if not query:
            raise ValueError("query parameter is required.")

        file_pat = args.get("file_pattern", "*") or "*"
        max_results = min(max(1, args.get("max_results", 25)), 100)
        canonical_root = os.path.realpath(settings.WORKSPACE_ROOT)

        skip_dirs = {".git", ".venv", ".gradle", "node_modules", "build", "__pycache__", ".pytest_cache", ".idea"}
        matches = []

        is_regex = False
        pattern = None
        try:
            pattern = re.compile(query, re.IGNORECASE)
            is_regex = True
        except re.error:
            pass

        for root, dirs, files in os.walk(canonical_root):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                if not fnmatch.fnmatch(f, file_pat):
                    continue
                file_path = os.path.join(root, f)
                try:
                    if os.path.getsize(file_path) > 1024 * 1024:
                        continue
                except OSError:
                    continue

                rel_file = os.path.relpath(file_path, canonical_root)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
                        for line_no, line in enumerate(fh, 1):
                            matched = False
                            if is_regex and pattern:
                                matched = bool(pattern.search(line))
                            else:
                                matched = query.lower() in line.lower()
                            if matched:
                                matches.append({
                                    "file": rel_file,
                                    "line": line_no,
                                    "snippet": line.strip()[:160]
                                })
                                if len(matches) >= max_results:
                                    break
                except Exception:
                    continue
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break

        return {
            "query": query,
            "matches_count": len(matches),
            "matches": matches,
            "truncated": len(matches) >= max_results
        }

    async def _handle_file_writer(self, args: Dict[str, Any]) -> Dict[str, Any]:
        rel_path = args.get("relative_path", "").strip()
        content = args.get("content", "")
        create_backup = args.get("create_backup", True)

        if not rel_path:
            raise ValueError("relative_path parameter is required.")

        target_path = get_safe_workspace_path(rel_path)
        canonical_root = os.path.realpath(settings.WORKSPACE_ROOT)

        rel_clean = os.path.relpath(target_path, canonical_root)
        if rel_clean.startswith(".git") or rel_clean.startswith("backend/.venv"):
            raise ValueError(f"Writing to protected directory '{rel_clean}' is prohibited.")

        backup_file = None
        is_new = not os.path.exists(target_path)
        if not is_new and create_backup:
            backup_file = f"{target_path}.bak"
            try:
                with open(target_path, "r", encoding="utf-8", errors="ignore") as src, open(backup_file, "w", encoding="utf-8") as dst:
                    dst.write(src.read())
            except Exception:
                backup_file = None

        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)

        return {
            "file": rel_clean,
            "bytes_written": len(content.encode("utf-8")),
            "is_new": is_new,
            "backup_created": backup_file is not None
        }

    async def _handle_diff_generator(self, args: Dict[str, Any]) -> Dict[str, Any]:
        rel_path = args.get("relative_path", "").strip()
        new_content = args.get("new_content", "")
        if not rel_path:
            raise ValueError("relative_path parameter is required.")

        target_path = get_safe_workspace_path(rel_path)
        canonical_root = os.path.realpath(settings.WORKSPACE_ROOT)
        rel_clean = os.path.relpath(target_path, canonical_root)

        old_lines = []
        if os.path.exists(target_path) and os.path.isfile(target_path):
            with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
                old_lines = f.readlines()

        new_lines = [l + "\n" if not l.endswith("\n") else l for l in new_content.splitlines()]
        diff = list(difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{rel_clean}",
            tofile=f"b/{rel_clean}"
        ))

        return {
            "file": rel_clean,
            "diff": "".join(diff),
            "changes_count": len([d for d in diff if d.startswith(("+", "-")) and not d.startswith(("+++", "---"))])
        }

    async def _handle_test_runner(self, args: Dict[str, Any]) -> Dict[str, Any]:
        raw_target = args.get("test_target", "tests/test_health.py").strip()
        backend_dir = os.path.realpath(os.path.join(settings.WORKSPACE_ROOT, "backend"))
        pytest_bin = os.path.join(backend_dir, ".venv", "bin", "pytest")

        if not raw_target or raw_target in [".", "tests", "tests/"]:
            target_arg = "tests/"
        else:
            clean_target = raw_target.lstrip("/\\")
            if not clean_target.startswith("tests"):
                clean_target = f"tests/{clean_target}"
            target_path = os.path.realpath(os.path.join(backend_dir, clean_target))
            try:
                common = os.path.commonpath([backend_dir, target_path])
                if common != backend_dir:
                    raise ValueError(f"Directory traversal attempt blocked: Test target outside backend directory blocked: {raw_target}")
            except ValueError as e:
                raise ValueError(f"Directory traversal attempt blocked: {str(e)}")
            target_arg = os.path.relpath(target_path, backend_dir)

        if not os.path.exists(pytest_bin):
            return {
                "exit_code": 1,
                "status": "failed",
                "error": "Pytest executable not found in backend/.venv/bin/pytest",
                "passed": 0,
                "failed": 0
            }

        start_time = time.perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                pytest_bin, target_arg, "-q",
                cwd=backend_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=dict(os.environ, PYTHONPATH=".", DOTMIND_TESTING="1")
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45.0)
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)

            out_text = stdout.decode("utf-8", errors="ignore")
            err_text = stderr.decode("utf-8", errors="ignore")
            combined = (out_text + "\n" + err_text).strip()

            passed_match = re.search(r"(\d+)\s+passed", combined)
            failed_match = re.search(r"(\d+)\s+failed", combined)
            passed_cnt = int(passed_match.group(1)) if passed_match else 0
            failed_cnt = int(failed_match.group(1)) if failed_match else 0

            return {
                "target": target_arg,
                "exit_code": proc.returncode,
                "status": "succeeded" if proc.returncode == 0 else "failed",
                "passed": passed_cnt,
                "failed": failed_cnt,
                "latency_ms": elapsed_ms,
                "summary": f"{passed_cnt} passed, {failed_cnt} failed in {elapsed_ms}ms",
                "output_preview": combined[-1000:]
            }
        except asyncio.TimeoutError:
            return {
                "target": target_arg,
                "exit_code": -1,
                "status": "timed_out",
                "error": "Test execution exceeded 45.0s timeout."
            }

    async def _handle_log_inspector(self, args: Dict[str, Any]) -> Dict[str, Any]:
        log_file = args.get("log_file", "backend/server.log").strip()
        max_lines = min(max(5, args.get("max_lines", 50)), 200)

        target_path = get_safe_workspace_path(log_file)
        canonical_root = os.path.realpath(settings.WORKSPACE_ROOT)

        if not os.path.exists(target_path) or not os.path.isfile(target_path):
            alt_path = os.path.join(canonical_root, "server.log")
            if os.path.exists(alt_path):
                target_path = alt_path
            else:
                return {
                    "file": log_file,
                    "exists": False,
                    "lines_read": 0,
                    "content": "No server log file found in workspace."
                }

        lines = []
        with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        tail_lines = lines[-max_lines:]
        return {
            "file": os.path.relpath(target_path, canonical_root),
            "lines_read": len(tail_lines),
            "total_lines": len(lines),
            "content": "".join(tail_lines)
        }

    async def _handle_browser_navigator(self, args: Dict[str, Any]) -> Dict[str, Any]:
        action = args.get("action", "navigate").lower().strip()
        url = (args.get("url") or "").strip()
        query = (args.get("query") or "").strip()

        # Web search action
        if action == "search_web" or (not url and query):
            search_query = query or url
            encoded_q = quote_plus(search_query)
            search_url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                resp = await client.get(search_url, headers=headers)
                results = []
                if resp.status_code == 200:
                    snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', resp.text, re.DOTALL | re.IGNORECASE)
                    titles = re.findall(r'<a class="result__url[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text, re.DOTALL | re.IGNORECASE)
                    for i in range(min(len(titles), 5)):
                        raw_href, raw_title = titles[i]
                        raw_snip = snippets[i] if i < len(snippets) else ""
                        clean_title = re.sub(r"<[^>]+>", "", raw_title).strip()
                        clean_snip = re.sub(r"<[^>]+>", "", raw_snip).strip()
                        results.append({
                            "title": clean_title,
                            "url": raw_href,
                            "snippet": clean_snip
                        })
                return {
                    "action": "search_web",
                    "query": search_query,
                    "status_code": resp.status_code,
                    "results_count": len(results),
                    "results": results
                }

        # URL Navigation & Extraction Actions
        if not url:
            raise ValueError("Parameter 'url' is required for browser navigation.")

        safe_url = validate_safe_url(url)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

        start_time = time.time()
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(safe_url, headers=headers)
            elapsed_ms = int((time.time() - start_time) * 1000)

        html = resp.text
        title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        page_title = title_m.group(1).strip() if title_m else ""

        if action == "extract_links":
            links = []
            for href_m, text_m in re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
                c_text = re.sub(r"<[^>]+>", "", text_m).strip()
                if href_m.startswith("http") or href_m.startswith("/"):
                    links.append({"href": href_m, "text": c_text[:100]})
                if len(links) >= 30:
                    break
            return {
                "action": "extract_links",
                "url": safe_url,
                "status_code": resp.status_code,
                "title": page_title,
                "links_found": len(links),
                "links": links
            }

        # Default action: navigate & extract reader view text
        clean_html = re.sub(r"<(script|style|noscript|svg|iframe)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        headings = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r'<h[1-3][^>]*>(.*?)</h[1-3]>', clean_html, re.DOTALL | re.IGNORECASE)]
        raw_text = re.sub(r"<[^>]+>", " ", clean_html)
        clean_text = " ".join(raw_text.split())

        return {
            "action": "navigate",
            "url": safe_url,
            "status_code": resp.status_code,
            "latency_ms": elapsed_ms,
            "title": page_title,
            "headings": [h for h in headings[:8] if h],
            "text_content": clean_text[:4000],
            "text_length": len(clean_text)
        }

tool_registry = ToolRegistry()

