"""Explicit UI lifecycle for one durable generation-and-review session."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GenerationStage(str, Enum):
    CONFIGURING = "configuring"
    RUNNING = "running"
    PARTIAL = "partial"
    REVIEW_PENDING = "review_pending"
    SAVED = "saved"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class GenerationSessionState:
    """Constrain visible generation states without owning questions or workers."""

    stage: GenerationStage = GenerationStage.CONFIGURING

    def start(self) -> None:
        self.stage = GenerationStage.RUNNING

    def keep_partial_results(self) -> None:
        if self.stage is GenerationStage.RUNNING:
            self.stage = GenerationStage.PARTIAL

    def request_review(self) -> None:
        if self.stage in {GenerationStage.RUNNING, GenerationStage.PARTIAL}:
            self.stage = GenerationStage.REVIEW_PENDING

    def recover_for_review(self) -> None:
        """Make retained questions reviewable after an otherwise failed run."""
        if self.stage is GenerationStage.FAILED:
            self.stage = GenerationStage.REVIEW_PENDING

    def restore_review(self) -> None:
        """Restore a persisted review draft without pretending a run started."""
        if self.stage is GenerationStage.CONFIGURING:
            self.stage = GenerationStage.REVIEW_PENDING

    def save(self) -> None:
        if self.stage is GenerationStage.REVIEW_PENDING:
            self.stage = GenerationStage.SAVED

    def fail(self) -> None:
        if self.stage is GenerationStage.RUNNING:
            self.stage = GenerationStage.FAILED

    def cancel(self) -> None:
        if self.stage is GenerationStage.RUNNING:
            self.stage = GenerationStage.CANCELLED
