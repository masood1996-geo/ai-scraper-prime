from __future__ import annotations

from ai_scraper.command_safety import CommandSafety, PermissionMode


def test_command_safety_is_a_denying_standalone_validator(tmp_path):
    read_only = CommandSafety(
        workspace=str(tmp_path),
        mode=PermissionMode.READ_ONLY,
    )
    assert read_only.validate("git status").allowed
    assert read_only.validate("touch result.txt").blocked
    assert read_only.validate("git commit -m test").blocked
    assert read_only.validate("rm -rf /").blocked


def test_workspace_mode_blocks_traversal_and_home_targets(tmp_path):
    safety = CommandSafety(
        workspace=str(tmp_path),
        mode=PermissionMode.WORKSPACE_WRITE,
    )
    assert safety.validate("touch ../outside.txt").blocked
    assert safety.validate("touch ~/outside.txt").blocked
    assert safety.stats()["total_validations"] == 2
