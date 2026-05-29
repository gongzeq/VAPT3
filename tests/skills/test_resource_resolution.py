"""Resource resolution tests for skill handlers."""

from __future__ import annotations

from secbot.skills._shared.resource import resolve_resource


def test_resolve_resource_prefers_workspace_resource(make_ctx):
    ctx = make_ctx()
    workspace_resource = (
        ctx.scan_dir.parent
        / "secbot"
        / "resource"
        / "poc"
        / "upload"
        / "pikachu_upload.yaml"
    )
    workspace_resource.parent.mkdir(parents=True)
    workspace_resource.write_text("id: workspace-pikachu\n", encoding="utf-8")

    resolved = resolve_resource(ctx, "poc", "upload", "pikachu_upload.yaml")

    assert resolved == workspace_resource


def test_resolve_resource_falls_back_to_bundled_resource(make_ctx):
    resolved = resolve_resource(make_ctx(), "poc", "upload", "pikachu_upload.yaml")

    assert resolved is not None
    assert resolved.name == "pikachu_upload.yaml"
    assert "secbot/resource/poc/upload" in resolved.as_posix()


def test_resolve_resource_rejects_traversal(make_ctx):
    assert resolve_resource(make_ctx(), "..", "pyproject.toml") is None
