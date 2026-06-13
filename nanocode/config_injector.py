"""Config Injector - Migrate rules and modes from .nanocode/ directories.

Ported from kilo's kilocode/config-injector.ts, rules-migrator.ts, and modes-migrator.ts.
Migrates rules, custom modes/agents, and permissions into the system prompt.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InjectionResult:
    """Result of config injection."""

    rules: list[str] = field(default_factory=list)
    agents: dict[str, dict[str, Any]] = field(default_factory=dict)
    permissions: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def migrate_rules(
    project_dir: str | Path,
    include_global: bool = True,
) -> tuple[list[str], list[str]]:
    """Migrate rules from .nanocode/rules/ directories.

    Args:
        project_dir: Project directory
        include_global: Include global ~/.nanocode/rules/

    Returns:
        Tuple of (rules, warnings)
    """
    rules = []
    warnings = []
    project_dir = Path(project_dir)

    rule_dirs = [project_dir / ".nanocode" / "rules"]
    if include_global:
        rule_dirs.append(Path.home() / ".nanocode" / "rules")

    for rule_dir in rule_dirs:
        if not rule_dir.exists():
            continue

        for rule_file in sorted(rule_dir.glob("*.md")):
            try:
                content = rule_file.read_text(encoding="utf-8")
                if content.strip():
                    rules.append(content.strip())
                    logger.debug(f"Migrated rule from {rule_file}")
            except Exception as e:
                warnings.append(f"Failed to read {rule_file}: {e}")

        for rule_file in sorted(rule_dir.glob("*.txt")):
            try:
                content = rule_file.read_text(encoding="utf-8")
                if content.strip():
                    rules.append(content.strip())
                    logger.debug(f"Migrated rule from {rule_file}")
            except Exception as e:
                warnings.append(f"Failed to read {rule_file}: {e}")

    return rules, warnings


def migrate_modes(
    project_dir: str | Path,
    include_global: bool = True,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Migrate custom modes/agents from .nanocode/modes/ directories.

    Args:
        project_dir: Project directory
        include_global: Include global ~/.nanocode/modes/

    Returns:
        Tuple of (agents_dict, warnings)
    """
    agents = {}
    warnings = []
    project_dir = Path(project_dir)

    mode_dirs = [project_dir / ".nanocode" / "modes"]
    if include_global:
        mode_dirs.append(Path.home() / ".nanocode" / "modes")

    for mode_dir in mode_dirs:
        if not mode_dir.exists():
            continue

        for mode_file in sorted(mode_dir.glob("*.md")):
            try:
                content = mode_file.read_text(encoding="utf-8")
                name = mode_file.stem

                if content.strip():
                    agents[name] = {
                        "name": name,
                        "description": f"Custom mode: {name}",
                        "prompt": content.strip(),
                        "source": str(mode_file),
                    }
                    logger.debug(f"Migrated mode from {mode_file}")
            except Exception as e:
                warnings.append(f"Failed to read {mode_file}: {e}")

    return agents, warnings


def migrate_permissions(
    project_dir: str | Path,
    include_global: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Migrate permissions from .nanocode/permissions/ directories.

    Args:
        project_dir: Project directory
        include_global: Include global ~/.nanocode/permissions/

    Returns:
        Tuple of (permissions_dict, warnings)
    """
    permissions: dict[str, Any] = {}
    warnings = []
    project_dir = Path(project_dir)

    perm_dirs = [project_dir / ".nanocode" / "permissions"]
    if include_global:
        perm_dirs.append(Path.home() / ".nanocode" / "permissions")

    for perm_dir in perm_dirs:
        if not perm_dir.exists():
            continue

        for perm_file in sorted(perm_dir.glob("*.yaml")):
            try:
                import yaml
                content = perm_file.read_text(encoding="utf-8")
                data = yaml.safe_load(content)
                if isinstance(data, dict):
                    for key, value in data.items():
                        if key in permissions:
                            existing = permissions[key]
                            if isinstance(existing, dict) and isinstance(value, dict):
                                existing.update(value)
                            else:
                                permissions[key] = value
                        else:
                            permissions[key] = value
                    logger.debug(f"Migrated permissions from {perm_file}")
            except Exception as e:
                warnings.append(f"Failed to read {perm_file}: {e}")

        for perm_file in sorted(perm_dir.glob("*.json")):
            try:
                import json
                content = perm_file.read_text(encoding="utf-8")
                data = json.loads(content)
                if isinstance(data, dict):
                    for key, value in data.items():
                        if key in permissions:
                            existing = permissions[key]
                            if isinstance(existing, dict) and isinstance(value, dict):
                                existing.update(value)
                            else:
                                permissions[key] = value
                        else:
                            permissions[key] = value
                    logger.debug(f"Migrated permissions from {perm_file}")
            except Exception as e:
                warnings.append(f"Failed to read {perm_file}: {e}")

    return permissions, warnings


def inject_config(
    project_dir: str | Path,
    include_global: bool = True,
    include_rules: bool = True,
    include_modes: bool = True,
    include_permissions: bool = True,
) -> InjectionResult:
    """Migrate all config from .nanocode/ directories.

    Args:
        project_dir: Project directory
        include_global: Include global ~/.nanocode/
        include_rules: Migrate rules
        include_modes: Migrate modes
        include_permissions: Migrate permissions

    Returns:
        InjectionResult with all migrated config
    """
    result = InjectionResult()

    if include_rules:
        rules, warnings = migrate_rules(project_dir, include_global)
        result.rules.extend(rules)
        result.warnings.extend(warnings)

    if include_modes:
        agents, warnings = migrate_modes(project_dir, include_global)
        result.agents.update(agents)
        result.warnings.extend(warnings)

    if include_permissions:
        permissions, warnings = migrate_permissions(project_dir, include_global)
        result.permissions.update(permissions)
        result.warnings.extend(warnings)

    logger.info(
        f"Config injection complete: {len(result.rules)} rules, "
        f"{len(result.agents)} agents, "
        f"{len(result.permissions)} permission sets"
    )

    return result


def build_rules_section(rules: list[str]) -> str:
    """Build a rules section for the system prompt.

    Args:
        rules: List of rule content strings

    Returns:
        Formatted rules section
    """
    if not rules:
        return ""

    lines = ["# Project Rules", ""]
    for i, rule in enumerate(rules, 1):
        lines.append(f"## Rule {i}")
        lines.append(rule)
        lines.append("")

    return "\n".join(lines)


def build_modes_section(agents: dict[str, dict[str, Any]]) -> str:
    """Build a modes section for the system prompt.

    Args:
        agents: Dict of agent name to agent config

    Returns:
        Formatted modes section
    """
    if not agents:
        return ""

    lines = ["# Custom Modes", ""]
    for name, config in agents.items():
        desc = config.get("description", "")
        lines.append(f"- **{name}**: {desc}")

    lines.append("")
    return "\n".join(lines)
