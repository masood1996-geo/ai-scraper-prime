"""Public package surface for AI Scraper Prime."""

from ai_scraper.command_safety import CommandSafety, PermissionMode
from ai_scraper.core import AIScraper
from ai_scraper.learner import Learner
from ai_scraper.memory import Memory
from ai_scraper.recovery import (
    FailureScenario,
    RecoveryEngine,
    RecoveryStepResult,
    RecoveryStepStatus,
)
from ai_scraper.schemas import Schema

__version__ = "2.0.0"
__author__ = "masood1996-geo"

__all__ = [
    "AIScraper",
    "Schema",
    "Memory",
    "Learner",
    "RecoveryEngine",
    "FailureScenario",
    "RecoveryStepResult",
    "RecoveryStepStatus",
    "CommandSafety",
    "PermissionMode",
]
