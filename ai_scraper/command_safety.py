"""
Command safety — classify and gate shell commands before execution.

Adapted from claw-code-parity's bash_validation.rs pipeline.
Provides a comprehensive command validation framework:

1. Classify command intent (ReadOnly, Write, Destructive, Network, etc.)
2. Validate against permission modes (ReadOnly, WorkspaceWrite, Full)
3. Detect destructive patterns (rm -rf /, fork bombs, disk writes)
4. Validate paths for traversal attacks (../, ~/, $HOME)
5. Validate sed expressions for in-place editing safety
6. Special handling for git, sudo, and piped commands

Usage:
    from ai_scraper.command_safety import CommandSafety, PermissionMode

    safety = CommandSafety(workspace="/path/to/project")
    result = safety.validate("rm -rf /tmp/data")

    if result.allowed:
        os.system(command)
    else:
        print(f"Blocked: {result.reason}")
"""

import logging
import shlex
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Set

logger = logging.getLogger(__name__)


# ─── Permission Modes ────────────────────────────────────────────────


class PermissionMode(Enum):
    """Permission levels for command execution, matching claw-code-parity."""

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    FULL = "full"


# ─── Command Intent ──────────────────────────────────────────────────


class CommandIntent(Enum):
    """Semantic classification of a command's intent."""

    READ_ONLY = "read_only"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    NETWORK = "network"
    PROCESS_MANAGEMENT = "process_management"
    PACKAGE_MANAGEMENT = "package_management"
    SYSTEM_ADMIN = "system_admin"
    UNKNOWN = "unknown"


# ─── Validation Result ───────────────────────────────────────────────


class ValidationAction(Enum):
    """What to do with a validated command."""

    ALLOW = "allow"
    BLOCK = "block"
    WARN = "warn"


@dataclass
class ValidationResult:
    """
    Result of validating a command through the safety pipeline.

    Attributes:
        action: Whether to allow, block, or warn about the command.
        intent: The classified semantic intent of the command.
        reason: Human-readable explanation (for blocks and warnings).
        command: The original command that was validated.
        checks_passed: List of validation checks that passed.
        checks_failed: List of validation checks that failed.
    """

    action: ValidationAction
    intent: CommandIntent
    reason: str = ""
    command: str = ""
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        """Whether the command is safe to execute."""
        return self.action == ValidationAction.ALLOW

    @property
    def blocked(self) -> bool:
        """Whether the command was blocked."""
        return self.action == ValidationAction.BLOCK

    @property
    def warning(self) -> bool:
        """Whether the command has a warning but is allowed."""
        return self.action == ValidationAction.WARN

    def __repr__(self) -> str:
        status = "✅" if self.allowed else ("🚫" if self.blocked else "⚠️")
        return (
            f"ValidationResult({status} {self.action.value}, "
            f"intent={self.intent.value}, reason='{self.reason}')"
        )


# ─── Command Classification Lists ───────────────────────────────────
# Ported directly from claw-code-parity/bash_validation.rs

# Commands that perform write operations
WRITE_COMMANDS: Set[str] = {
    "cp",
    "mv",
    "rm",
    "mkdir",
    "rmdir",
    "touch",
    "chmod",
    "chown",
    "chgrp",
    "ln",
    "install",
    "tee",
    "truncate",
    "shred",
    "mkfifo",
    "mknod",
    "dd",
}

# Commands that modify system state
STATE_MODIFYING_COMMANDS: Set[str] = {
    "apt",
    "apt-get",
    "yum",
    "dnf",
    "pacman",
    "brew",
    "pip",
    "pip3",
    "npm",
    "yarn",
    "pnpm",
    "bun",
    "cargo",
    "gem",
    "go",
    "rustup",
    "docker",
    "systemctl",
    "service",
    "mount",
    "umount",
    "kill",
    "pkill",
    "killall",
    "reboot",
    "shutdown",
    "halt",
    "poweroff",
    "useradd",
    "userdel",
    "usermod",
    "groupadd",
    "groupdel",
    "crontab",
    "at",
}

# Read-only commands (no filesystem or state modification)
READ_ONLY_COMMANDS: Set[str] = {
    "ls",
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "wc",
    "sort",
    "uniq",
    "grep",
    "egrep",
    "fgrep",
    "find",
    "which",
    "whereis",
    "whatis",
    "man",
    "info",
    "file",
    "stat",
    "du",
    "df",
    "free",
    "uptime",
    "uname",
    "hostname",
    "whoami",
    "id",
    "groups",
    "env",
    "printenv",
    "echo",
    "printf",
    "date",
    "cal",
    "bc",
    "expr",
    "test",
    "true",
    "false",
    "pwd",
    "tree",
    "diff",
    "cmp",
    "md5sum",
    "sha256sum",
    "sha1sum",
    "xxd",
    "od",
    "hexdump",
    "strings",
    "readlink",
    "realpath",
    "basename",
    "dirname",
    "seq",
    "yes",
    "tput",
    "column",
    "jq",
    "yq",
    "xargs",
    "tr",
    "cut",
    "paste",
    "awk",
    "sed",
    # Windows equivalents
    "dir",
    "type",
    "where",
    "findstr",
    "Get-Content",
    "Get-ChildItem",
    "Get-Location",
    "Get-Date",
    "Get-Process",
    "Get-Service",
}

# Network operations
NETWORK_COMMANDS: Set[str] = {
    "curl",
    "wget",
    "ssh",
    "scp",
    "rsync",
    "ftp",
    "sftp",
    "nc",
    "ncat",
    "telnet",
    "ping",
    "traceroute",
    "tracert",
    "dig",
    "nslookup",
    "host",
    "whois",
    "ifconfig",
    "ip",
    "netstat",
    "ss",
    "nmap",
    # Windows equivalents
    "Invoke-WebRequest",
    "Invoke-RestMethod",
    "Test-Connection",
}

# Process management commands
PROCESS_COMMANDS: Set[str] = {
    "kill",
    "pkill",
    "killall",
    "ps",
    "top",
    "htop",
    "bg",
    "fg",
    "jobs",
    "nohup",
    "disown",
    "wait",
    "nice",
    "renice",
    # Windows equivalents
    "Stop-Process",
    "Start-Process",
    "taskkill",
    "tasklist",
}

# Package management commands
PACKAGE_COMMANDS: Set[str] = {
    "apt",
    "apt-get",
    "yum",
    "dnf",
    "pacman",
    "brew",
    "pip",
    "pip3",
    "npm",
    "yarn",
    "pnpm",
    "bun",
    "cargo",
    "gem",
    "go",
    "rustup",
    "snap",
    "flatpak",
    # Windows equivalents
    "choco",
    "winget",
    "scoop",
}

# System administration commands
SYSTEM_ADMIN_COMMANDS: Set[str] = {
    "sudo",
    "su",
    "chroot",
    "mount",
    "umount",
    "fdisk",
    "parted",
    "lsblk",
    "blkid",
    "systemctl",
    "service",
    "journalctl",
    "dmesg",
    "modprobe",
    "insmod",
    "rmmod",
    "iptables",
    "ufw",
    "firewall-cmd",
    "sysctl",
    "crontab",
    "at",
    "useradd",
    "userdel",
    "usermod",
    "groupadd",
    "groupdel",
    "passwd",
    "visudo",
    # Windows equivalents
    "runas",
    "Set-ExecutionPolicy",
    "New-NetFirewallRule",
}

# Always-destructive commands
ALWAYS_DESTRUCTIVE: Set[str] = {"shred", "wipefs"}

# Git subcommands that are read-only safe
GIT_READ_ONLY_SUBCOMMANDS: Set[str] = {
    "status",
    "log",
    "diff",
    "show",
    "branch",
    "tag",
    "stash",
    "remote",
    "fetch",
    "ls-files",
    "ls-tree",
    "cat-file",
    "rev-parse",
    "describe",
    "shortlog",
    "blame",
    "bisect",
    "reflog",
    "config",
}

# Shell redirection operators that indicate writes
WRITE_REDIRECTIONS: List[str] = [">", ">>", ">&"]

# Destructive patterns with explanations
DESTRUCTIVE_PATTERNS: List[tuple] = [
    ("rm -rf /", "Recursive forced deletion at root — will destroy the system"),
    ("rm -rf ~", "Recursive forced deletion of home directory"),
    ("rm -rf *", "Recursive forced deletion of all files in current directory"),
    ("rm -rf .", "Recursive forced deletion of current directory"),
    ("mkfs", "Filesystem creation will destroy existing data on the device"),
    ("dd if=", "Direct disk write — can overwrite partitions or devices"),
    ("> /dev/sd", "Writing to raw disk device"),
    ("chmod -R 777", "Recursively setting world-writable permissions"),
    ("chmod -R 000", "Recursively removing all permissions"),
    (":(){ :|:& };:", "Fork bomb — will crash the system"),
    # Windows destructive patterns
    ("Format-Volume", "Volume formatting will destroy all data"),
    ("Remove-Item -Recurse -Force C:\\", "Recursive forced deletion of system drive"),
    ("del /s /q C:\\", "Recursive deletion of system drive"),
    ("rd /s /q C:\\", "Recursive deletion of system drive"),
]

# System paths that indicate out-of-workspace targeting
SYSTEM_PATHS: List[str] = [
    "/etc/",
    "/usr/",
    "/var/",
    "/boot/",
    "/sys/",
    "/proc/",
    "/dev/",
    "/sbin/",
    "/lib/",
    "/opt/",
    # Windows system paths
    "C:\\Windows\\",
    "C:\\Program Files\\",
    "C:\\System32\\",
]


# ─── Helper Functions ────────────────────────────────────────────────


def _extract_first_command(command: str) -> str:
    """Extract the first command from a potentially piped/chained command."""
    # Strip leading whitespace and env prefix
    stripped = command.strip()

    # Handle env prefix: env VAR=val command
    if stripped.startswith("env "):
        parts = stripped.split()
        for part in parts[1:]:
            if "=" not in part and not part.startswith("-"):
                return part
        return ""

    # Split on pipes, semicolons, and &&
    for sep in ["|", "&&", "||", ";"]:
        if sep in stripped:
            stripped = stripped.split(sep)[0].strip()

    # Get the first token
    try:
        tokens = shlex.split(stripped)
    except ValueError:
        tokens = stripped.split()

    return tokens[0] if tokens else ""


def _extract_sudo_inner(command: str) -> str:
    """Extract the command being run under sudo."""
    parts = command.strip().split()
    if not parts or parts[0] != "sudo":
        return ""

    # Skip sudo and its flags
    for i, part in enumerate(parts[1:], 1):
        if not part.startswith("-") and part != "sudo":
            return " ".join(parts[i:])

    return ""


# ─── Command Safety Engine ──────────────────────────────────────────


class CommandSafety:
    """
    Command safety validation engine.

    Classifies commands and validates them against a permission mode,
    checking for destructive patterns, path traversal, and workspace
    boundary violations.

    Adapted from claw-code-parity's bash_validation.rs pipeline.

    Usage:
        safety = CommandSafety(
            workspace="/path/to/project",
            mode=PermissionMode.WORKSPACE_WRITE,
        )
        result = safety.validate("rm -rf /tmp/data")

        if result.allowed:
            subprocess.run(command, shell=True)
        elif result.warning:
            print(f"Warning: {result.reason}")
            # proceed with caution
        else:
            print(f"Blocked: {result.reason}")
    """

    def __init__(
        self,
        workspace: Optional[str] = None,
        mode: PermissionMode = PermissionMode.WORKSPACE_WRITE,
        custom_blocklist: Optional[Set[str]] = None,
        custom_allowlist: Optional[Set[str]] = None,
    ):
        """
        Initialize the command safety engine.

        Args:
            workspace: Root workspace directory. Commands targeting
                       paths outside this directory will be flagged.
            mode: Permission mode governing what commands are allowed.
            custom_blocklist: Additional commands to block.
            custom_allowlist: Commands to explicitly allow (overrides blocks).
        """
        self.workspace = Path(workspace).resolve() if workspace else Path.cwd()
        self.mode = mode
        self._custom_blocklist = custom_blocklist or set()
        self._custom_allowlist = custom_allowlist or set()
        self._validation_count = 0
        self._block_count = 0
        self._warn_count = 0

        logger.info(
            "CommandSafety initialized (workspace=%s, mode=%s)",
            self.workspace,
            self.mode.value,
        )

    # ── Public API ──

    def validate(self, command: str) -> ValidationResult:
        """
        Run the full validation pipeline on a command.

        Pipeline order (matching claw-code-parity):
        1. Custom blocklist/allowlist check
        2. Destructive command warning
        3. Read-only mode validation
        4. Permission mode validation
        5. Sed expression validation
        6. Path traversal validation

        Args:
            command: The shell command to validate.

        Returns:
            ValidationResult with action, intent, and reason.
        """
        self._validation_count += 1
        command = command.strip()

        if not command:
            return ValidationResult(
                action=ValidationAction.ALLOW,
                intent=CommandIntent.READ_ONLY,
                command=command,
                reason="Empty command",
            )

        first_cmd = _extract_first_command(command)
        intent = self.classify(command)
        checks_passed = []
        checks_failed = []

        # ── Check 1: Custom allowlist (bypass all other checks) ──
        if first_cmd in self._custom_allowlist:
            checks_passed.append("custom_allowlist")
            return ValidationResult(
                action=ValidationAction.ALLOW,
                intent=intent,
                command=command,
                checks_passed=checks_passed,
            )

        # ── Check 2: Custom blocklist ──
        if first_cmd in self._custom_blocklist:
            checks_failed.append("custom_blocklist")
            self._block_count += 1
            return ValidationResult(
                action=ValidationAction.BLOCK,
                intent=intent,
                command=command,
                reason=f"Command '{first_cmd}' is in the custom blocklist",
                checks_passed=checks_passed,
                checks_failed=checks_failed,
            )
        checks_passed.append("custom_blocklist")

        # ── Check 3: Destructive command warning ──
        destructive_result = self._check_destructive(command, first_cmd)
        if destructive_result:
            checks_failed.append("destructive_check")
            action = (
                ValidationAction.WARN
                if self.mode is PermissionMode.FULL
                else ValidationAction.BLOCK
            )
            if action is ValidationAction.BLOCK:
                self._block_count += 1
            else:
                self._warn_count += 1
            return ValidationResult(
                action=action,
                intent=CommandIntent.DESTRUCTIVE,
                command=command,
                reason=destructive_result,
                checks_passed=checks_passed,
                checks_failed=checks_failed,
            )
        checks_passed.append("destructive_check")

        # ── Check 4: Read-only mode validation ──
        if self.mode == PermissionMode.READ_ONLY:
            readonly_result = self._validate_read_only(command, first_cmd)
            if readonly_result:
                checks_failed.append("read_only_check")
                self._block_count += 1
                return ValidationResult(
                    action=ValidationAction.BLOCK,
                    intent=intent,
                    command=command,
                    reason=readonly_result,
                    checks_passed=checks_passed,
                    checks_failed=checks_failed,
                )
        checks_passed.append("read_only_check")

        # ── Check 5: Workspace boundary validation ──
        if self.mode == PermissionMode.WORKSPACE_WRITE:
            boundary_result = self._check_workspace_boundary(command, first_cmd)
            if boundary_result:
                checks_failed.append("workspace_boundary")
                self._block_count += 1
                return ValidationResult(
                    action=ValidationAction.BLOCK,
                    intent=intent,
                    command=command,
                    reason=boundary_result,
                    checks_passed=checks_passed,
                    checks_failed=checks_failed,
                )
        checks_passed.append("workspace_boundary")

        # ── Check 6: Sed validation ──
        sed_result = self._validate_sed(command, first_cmd)
        if sed_result:
            checks_failed.append("sed_validation")
            action = (
                ValidationAction.BLOCK
                if self.mode == PermissionMode.READ_ONLY
                else ValidationAction.WARN
            )
            return ValidationResult(
                action=action,
                intent=intent,
                command=command,
                reason=sed_result,
                checks_passed=checks_passed,
                checks_failed=checks_failed,
            )
        checks_passed.append("sed_validation")

        # ── Check 7: Path traversal validation ──
        path_result = self._validate_paths(command)
        if path_result:
            checks_failed.append("path_validation")
            action = (
                ValidationAction.WARN
                if self.mode is PermissionMode.FULL
                else ValidationAction.BLOCK
            )
            if action is ValidationAction.BLOCK:
                self._block_count += 1
            else:
                self._warn_count += 1
            return ValidationResult(
                action=action,
                intent=intent,
                command=command,
                reason=path_result,
                checks_passed=checks_passed,
                checks_failed=checks_failed,
            )
        checks_passed.append("path_validation")

        # ── All checks passed ──
        return ValidationResult(
            action=ValidationAction.ALLOW,
            intent=intent,
            command=command,
            checks_passed=checks_passed,
        )

    def classify(self, command: str) -> CommandIntent:
        """
        Classify the semantic intent of a command.

        Matches the command against known categories to determine
        whether it's read-only, write, destructive, network, etc.

        Args:
            command: The shell command to classify.

        Returns:
            CommandIntent enum value.
        """
        first = _extract_first_command(command)

        # Handle sudo — classify the inner command
        if first == "sudo":
            inner = _extract_sudo_inner(command)
            if inner:
                return self.classify(inner)
            return CommandIntent.SYSTEM_ADMIN

        # Check read-only first (most common)
        if first in READ_ONLY_COMMANDS:
            # Special case: sed -i is a write operation
            if first == "sed" and " -i" in command:
                return CommandIntent.WRITE
            return CommandIntent.READ_ONLY

        # Check destructive
        if first in ALWAYS_DESTRUCTIVE or first == "rm":
            return CommandIntent.DESTRUCTIVE

        # Check write
        if first in WRITE_COMMANDS:
            return CommandIntent.WRITE

        # Check network
        if first in NETWORK_COMMANDS:
            return CommandIntent.NETWORK

        # Check process management
        if first in PROCESS_COMMANDS:
            return CommandIntent.PROCESS_MANAGEMENT

        # Check package management
        if first in PACKAGE_COMMANDS:
            return CommandIntent.PACKAGE_MANAGEMENT

        # Check system admin
        if first in SYSTEM_ADMIN_COMMANDS:
            return CommandIntent.SYSTEM_ADMIN

        # Check git subcommands
        if first == "git":
            return self._classify_git(command)

        # Check Python/Node as potentially anything
        if first in ("python", "python3", "node", "ruby", "perl"):
            return CommandIntent.UNKNOWN

        return CommandIntent.UNKNOWN

    def is_safe(self, command: str) -> bool:
        """Quick check — is this command safe to execute?"""
        return self.validate(command).allowed

    def stats(self) -> dict:
        """Return validation statistics."""
        return {
            "total_validations": self._validation_count,
            "blocked": self._block_count,
            "warnings": self._warn_count,
            "allowed": self._validation_count - self._block_count - self._warn_count,
            "mode": self.mode.value,
            "workspace": str(self.workspace),
        }

    # ── Internal Validation Checks ──

    def _check_destructive(self, command: str, first_cmd: str) -> Optional[str]:
        """Check for destructive command patterns."""
        # Check known destructive patterns
        for pattern, warning in DESTRUCTIVE_PATTERNS:
            if pattern in command:
                return f"Destructive command detected: {warning}"

        # Check always-destructive commands
        if first_cmd in ALWAYS_DESTRUCTIVE:
            return (
                f"Command '{first_cmd}' is inherently destructive "
                f"and may cause data loss"
            )

        # Check for rm -rf with broad targets
        if "rm " in command and "-r" in command and "-f" in command:
            return (
                "Recursive forced deletion detected — verify the target path is correct"
            )

        return None

    def _validate_read_only(self, command: str, first_cmd: str) -> Optional[str]:
        """Validate command is allowed in read-only mode."""
        # Check write commands
        if first_cmd in WRITE_COMMANDS:
            return (
                f"Command '{first_cmd}' modifies the filesystem "
                f"and is not allowed in read-only mode"
            )

        # Check state-modifying commands
        if first_cmd in STATE_MODIFYING_COMMANDS:
            return (
                f"Command '{first_cmd}' modifies system state "
                f"and is not allowed in read-only mode"
            )

        # Check sudo wrapping write commands
        if first_cmd == "sudo":
            inner = _extract_sudo_inner(command)
            if inner:
                inner_first = _extract_first_command(inner)
                return self._validate_read_only(inner, inner_first)

        # Check write redirections
        for redir in WRITE_REDIRECTIONS:
            if redir in command:
                return (
                    f"Command contains write redirection '{redir}' "
                    f"which is not allowed in read-only mode"
                )

        # Check git for modifying subcommands
        if first_cmd == "git":
            return self._validate_git_read_only(command)

        return None

    def _validate_git_read_only(self, command: str) -> Optional[str]:
        """Validate git command is read-only safe."""
        parts = command.split()
        # Skip past "git" and any flags
        subcommand = None
        for part in parts[1:]:
            if not part.startswith("-"):
                subcommand = part
                break

        if subcommand is None:
            return None  # bare "git" is fine

        if subcommand in GIT_READ_ONLY_SUBCOMMANDS:
            return None

        return (
            f"Git subcommand '{subcommand}' modifies repository state "
            f"and is not allowed in read-only mode"
        )

    def _classify_git(self, command: str) -> CommandIntent:
        """Classify a git command's intent."""
        parts = command.split()
        subcommand = None
        for part in parts[1:]:
            if not part.startswith("-"):
                subcommand = part
                break

        if subcommand is None:
            return CommandIntent.READ_ONLY

        if subcommand in GIT_READ_ONLY_SUBCOMMANDS:
            return CommandIntent.READ_ONLY

        if subcommand in ("push", "force-push"):
            return CommandIntent.NETWORK

        # git add, commit, merge, rebase, reset, clean, etc.
        return CommandIntent.WRITE

    def _check_workspace_boundary(self, command: str, first_cmd: str) -> Optional[str]:
        """Check if command targets paths outside the workspace."""
        is_write_cmd = (
            first_cmd in WRITE_COMMANDS or first_cmd in STATE_MODIFYING_COMMANDS
        )

        if not is_write_cmd:
            return None

        for sys_path in SYSTEM_PATHS:
            if sys_path in command:
                return (
                    f"Command targets system path '{sys_path}' outside the "
                    f"workspace — requires elevated permission"
                )

        return None

    def _validate_sed(self, command: str, first_cmd: str) -> Optional[str]:
        """Validate sed expressions for safety."""
        if first_cmd != "sed":
            return None

        if " -i" in command and self.mode == PermissionMode.READ_ONLY:
            return "sed -i (in-place editing) is not allowed in read-only mode"

        return None

    def _validate_paths(self, command: str) -> Optional[str]:
        """Validate paths for traversal attacks."""
        # Check for directory traversal
        if "../" in command:
            workspace_str = str(self.workspace)
            if workspace_str not in command:
                return (
                    "Command contains directory traversal pattern '../' — "
                    "verify the target path resolves within the workspace"
                )

        # Check for home directory references
        if "~/" in command or "$HOME" in command:
            return (
                "Command references home directory — "
                "verify it stays within the workspace scope"
            )

        return None
