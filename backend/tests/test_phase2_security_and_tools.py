import os
import pytest
from app.config import settings
from app.services.tools.tool_registry import (
    get_safe_workspace_path,
    validate_safe_url,
    tool_registry
)

# ----------------- 1. WORKSPACE PATH SECURITY TESTS ----------------- #

def test_workspace_path_valid_in_root():
    """Valid path within workspace root resolves successfully."""
    valid_subpath = "backend/requirements.txt"
    resolved = get_safe_workspace_path(valid_subpath)
    canonical_root = os.path.realpath(settings.WORKSPACE_ROOT)
    assert resolved.startswith(canonical_root)
    assert resolved == os.path.realpath(os.path.join(canonical_root, valid_subpath))

def test_workspace_path_traversal_blocked():
    """Traversing outside workspace root using '../' is strictly blocked."""
    with pytest.raises(ValueError) as exc:
        get_safe_workspace_path("../../../etc/passwd")
    assert "Path traversal blocked" in str(exc.value)

def test_workspace_path_sibling_prefix_bypass_blocked():
    """Sibling directory sharing the same prefix name (e.g. dotmind-evil) is strictly blocked."""
    sibling_path = os.path.realpath(settings.WORKSPACE_ROOT) + "-evil/secret.txt"
    with pytest.raises(ValueError) as exc:
        # Pass path that attempts to escape via relative navigation to sibling
        get_safe_workspace_path("../dotmind-evil/secret.txt")
    assert "Path traversal blocked" in str(exc.value)

def test_workspace_path_absolute_escape_blocked():
    """Absolute path pointing outside workspace is stripped or rejected."""
    # When passed with leading slash, get_safe_workspace_path strips it and joins to root
    res = get_safe_workspace_path("/backend/app/main.py")
    assert os.path.commonpath([os.path.realpath(settings.WORKSPACE_ROOT), res]) == os.path.realpath(settings.WORKSPACE_ROOT)

@pytest.mark.asyncio
async def test_file_reader_tool_blocks_traversal():
    """file_reader tool rejects directory traversal attempts."""
    result = await tool_registry.execute("file_reader", {"relative_path": "../../../etc/shadow"})
    assert result.status == "failed"
    assert "Path traversal blocked" in (result.error or "")

@pytest.mark.asyncio
async def test_file_reader_tool_valid_file():
    """file_reader reads valid file within workspace accurately."""
    result = await tool_registry.execute("file_reader", {"relative_path": "backend/requirements.txt"})
    assert result.status == "succeeded"
    assert "fastapi" in result.output["content"]
    assert result.output["file"] == "backend/requirements.txt"

# ----------------- 2. SSRF PROTECTION TESTS ----------------- #

def test_ssrf_blocks_loopback_ipv4():
    """Blocks loopback 127.0.0.1 and variants."""
    with pytest.raises(ValueError) as exc:
        validate_safe_url("http://127.0.0.1:8000/api")
    assert "SSRF blocked" in str(exc.value)

def test_ssrf_blocks_localhost():
    """Blocks localhost hostname."""
    with pytest.raises(ValueError) as exc:
        validate_safe_url("http://localhost:8000/api")
    assert "SSRF blocked" in str(exc.value)

def test_ssrf_blocks_private_rfc1918():
    """Blocks private Class A, B, C network ranges."""
    with pytest.raises(ValueError) as exc:
        validate_safe_url("http://192.168.1.1/admin")
    assert "SSRF blocked" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        validate_safe_url("http://10.0.0.1/internal")
    assert "SSRF blocked" in str(exc.value)

def test_ssrf_blocks_cloud_metadata():
    """Blocks AWS/GCP/Azure link-local metadata endpoints."""
    with pytest.raises(ValueError) as exc:
        validate_safe_url("http://169.254.169.254/latest/meta-data/")
    assert "SSRF blocked" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        validate_safe_url("http://metadata.google.internal/computeMetadata/v1/")
    assert "SSRF blocked" in str(exc.value)

def test_ssrf_blocks_forbidden_schemes():
    """Rejects non-HTTP(S) schemes like file://, ftp://, gopher://."""
    with pytest.raises(ValueError) as exc:
        validate_safe_url("file:///etc/passwd")
    assert "Scheme 'file' is prohibited" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        validate_safe_url("ftp://ftp.example.com/data")
    assert "Scheme 'ftp' is prohibited" in str(exc.value)

@pytest.mark.asyncio
async def test_http_tester_tool_blocks_ssrf():
    """http_tester tool blocks malicious internal SSRF target."""
    result = await tool_registry.execute("http_tester", {"url": "http://127.0.0.1:8000/secret"})
    assert result.status == "failed"
    assert "SSRF blocked" in (result.error or "")

# ----------------- 3. TRUTHFUL PROJECT INSPECTION TESTS ----------------- #

@pytest.mark.asyncio
async def test_project_inspector_nonexistent_directory():
    """project_inspector truthfully reports when directory does not exist."""
    result = await tool_registry.execute("project_inspector", {"subpath": "nonexistent_subfolder_xyz"})
    assert result.status == "succeeded"
    assert result.output["exists"] is False
    assert "does not exist in workspace" in result.output["error"]

@pytest.mark.asyncio
async def test_project_inspector_real_workspace_root():
    """project_inspector detects real stacks and files truthfully."""
    result = await tool_registry.execute("project_inspector", {"subpath": ""})
    assert result.status == "succeeded"
    assert result.output["type"] == "directory"
    assert result.output["confirmed_stacks"]["android"] == "Jetpack Compose (Kotlin)"
    assert result.output["confirmed_stacks"]["backend"] == "FastAPI (Python)"

# ----------------- 4. PRODUCTION SECURITY CONFIGURATION TESTS ----------------- #

def test_production_secret_key_validation():
    """Settings raises ValueError if insecure default key is used in production environment."""
    from app.config import Settings
    with pytest.raises(ValueError) as exc:
        Settings(
            DOTMIND_ENV="production",
            SECRET_KEY="dotmind_super_secure_secret_key_change_in_production_991827"
        )
    assert "Insecure default SECRET_KEY cannot be used in production" in str(exc.value)

def test_production_short_secret_key_validation():
    """Settings raises ValueError if production key is too short (<32 chars)."""
    from app.config import Settings
    with pytest.raises(ValueError) as exc:
        Settings(
            DOTMIND_ENV="production",
            SECRET_KEY="too_short_key"
        )
    assert "min 32 chars" in str(exc.value)

# ----------------- 5. PHASE 3 WORKSPACE REAL TOOLS TESTS ----------------- #

@pytest.mark.asyncio
async def test_file_searcher_finds_real_keyword():
    """file_searcher finds real keywords across workspace files."""
    result = await tool_registry.execute("file_searcher", {"query": "FastAPI", "file_pattern": "*.py"})
    assert result.status == "succeeded"
    assert result.output["matches_count"] > 0
    assert any("main.py" in m["file"] or "fastapi" in m["snippet"].lower() for m in result.output["matches"])

@pytest.mark.asyncio
async def test_file_writer_blocks_path_traversal():
    """file_writer strictly blocks directory traversal attempts outside workspace."""
    result = await tool_registry.execute("file_writer", {"relative_path": "../../evil.txt", "content": "malicious"})
    assert result.status == "failed"
    assert "Directory traversal attempt blocked" in result.error or "Path traversal blocked" in result.error

@pytest.mark.asyncio
async def test_file_writer_and_diff_generator():
    """file_writer writes file in workspace and diff_generator computes changes."""
    test_file = "test_scratch.txt"
    try:
        write_res = await tool_registry.execute("file_writer", {"relative_path": test_file, "content": "Line 1\nLine 2\n", "create_backup": False})
        assert write_res.status == "succeeded"
        assert write_res.output["bytes_written"] > 0

        diff_res = await tool_registry.execute("diff_generator", {"relative_path": test_file, "new_content": "Line 1\nLine 2 modified\nLine 3\n"})
        assert diff_res.status == "succeeded"
        assert "Line 2 modified" in diff_res.output["diff"]
        assert diff_res.output["changes_count"] > 0
    finally:
        full_p = os.path.join(os.path.realpath(settings.WORKSPACE_ROOT), test_file)
        if os.path.exists(full_p):
            os.remove(full_p)

@pytest.mark.asyncio
async def test_test_runner_executes_real_tests():
    """test_runner executes real pytest tests and parses returncode, passed/failed."""
    result = await tool_registry.execute("test_runner", {"test_target": "tests/test_health.py"})
    assert result.status == "succeeded"
    assert result.output["exit_code"] == 0
    assert result.output["passed"] >= 2
    assert result.output["failed"] == 0

@pytest.mark.asyncio
async def test_log_inspector_reads_server_log():
    """log_inspector reads lines from existing log file."""
    result = await tool_registry.execute("log_inspector", {"log_file": "backend/server.log", "max_lines": 10})
    assert result.status == "succeeded"
    assert "lines_read" in result.output
    assert "content" in result.output

@pytest.mark.asyncio
async def test_project_inspect_valid_directory():
    """project_inspector lists valid workspace directory contents."""
    result = await tool_registry.execute("project_inspector", {"subpath": "backend"})
    assert result.status == "succeeded"
    assert result.output["type"] == "directory"
    assert "requirements.txt" in result.output["files_and_dirs"]

@pytest.mark.asyncio
async def test_project_inspect_nonexistent_path():
    """project_inspector gracefully returns exists=False for nonexistent path."""
    result = await tool_registry.execute("project_inspector", {"subpath": "non_existent_folder_xyz"})
    assert result.status == "succeeded"
    assert result.output["exists"] is False
    assert "does not exist in workspace" in result.output["error"]

def test_symlink_pointing_outside_workspace_blocked(tmp_path):
    """Symlinks resolving outside workspace root are blocked by commonpath check."""
    outside_file = tmp_path / "outside_secret.txt"
    outside_file.write_text("secret outside")

    symlink_path = os.path.join(os.path.realpath(settings.WORKSPACE_ROOT), "test_symlink_escape")
    try:
        os.symlink(str(outside_file), symlink_path)
        with pytest.raises(ValueError) as exc:
            get_safe_workspace_path("test_symlink_escape")
        assert "Path traversal blocked" in str(exc.value)
    finally:
        if os.path.islink(symlink_path) or os.path.exists(symlink_path):
            os.unlink(symlink_path)
