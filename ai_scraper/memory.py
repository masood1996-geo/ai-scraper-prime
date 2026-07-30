"""SQLite persistence for measured domain strategies and their evidence."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(
    os.path.expanduser("~"),
    ".ai_scraper",
    "memory.db",
)


class Memory:
    """Persist domain-scoped extraction observations and accepted strategies."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._conn: sqlite3.Connection = sqlite3.connect(db_path)
        self._closed = False
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        self._migrate_tables()
        logger.info("Strategy memory initialized at %s", db_path)

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS domain_profiles (
                domain          TEXT PRIMARY KEY,
                wait_seconds    REAL DEFAULT 2.0,
                clean_strategy  TEXT DEFAULT 'standard',
                avg_quality     REAL DEFAULT 0.0,
                total_scrapes   INTEGER DEFAULT 0,
                total_successes INTEGER DEFAULT 0,
                total_failures  INTEGER DEFAULT 0,
                last_scraped    REAL DEFAULT 0,
                notes           TEXT DEFAULT '',
                created_at      REAL DEFAULT 0,
                updated_at      REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS extraction_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                url             TEXT NOT NULL,
                domain          TEXT NOT NULL,
                schema_name     TEXT NOT NULL,
                results_count   INTEGER DEFAULT 0,
                quality_score   REAL DEFAULT 0.0,
                confidence      REAL DEFAULT 0.0,
                uncertainty     REAL DEFAULT 1.0,
                fill_rate       REAL DEFAULT 0.0,
                duration_secs   REAL DEFAULT 0.0,
                prompt_version  INTEGER DEFAULT 0,
                model_used      TEXT DEFAULT '',
                error           TEXT DEFAULT '',
                timestamp       REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS prompt_refinements (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                domain             TEXT NOT NULL,
                schema_name        TEXT NOT NULL,
                version            INTEGER DEFAULT 1,
                extra_instructions TEXT DEFAULT '',
                status             TEXT DEFAULT 'candidate',
                baseline_quality   REAL DEFAULT 0.0,
                candidate_quality  REAL,
                minimum_improvement REAL DEFAULT 0.05,
                latency_ms         REAL DEFAULT 0.0,
                input_tokens       INTEGER DEFAULT 0,
                output_tokens      INTEGER DEFAULT 0,
                times_used         INTEGER DEFAULT 0,
                created_at         REAL DEFAULT 0,
                evaluated_at       REAL DEFAULT 0,
                UNIQUE(domain, schema_name, version)
            );

            CREATE TABLE IF NOT EXISTS cleaning_rules (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                domain              TEXT NOT NULL,
                rule_type           TEXT NOT NULL,
                selector            TEXT NOT NULL,
                action              TEXT DEFAULT 'remove',
                reason              TEXT DEFAULT '',
                confidence          REAL DEFAULT 0.0,
                evidence_count      INTEGER DEFAULT 0,
                supporting_evidence TEXT DEFAULT '[]',
                status              TEXT DEFAULT 'candidate',
                times_applied       INTEGER DEFAULT 0,
                positive_outcomes   INTEGER DEFAULT 0,
                negative_outcomes   INTEGER DEFAULT 0,
                last_quality        REAL,
                created_at          REAL DEFAULT 0,
                updated_at          REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                url             TEXT NOT NULL,
                domain          TEXT NOT NULL,
                schema_name     TEXT NOT NULL,
                feedback_type   TEXT NOT NULL,
                details         TEXT DEFAULT '',
                timestamp       REAL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_history_domain
                ON extraction_history(domain);
            CREATE INDEX IF NOT EXISTS idx_history_url
                ON extraction_history(url);
            CREATE INDEX IF NOT EXISTS idx_prompts_domain_schema
                ON prompt_refinements(domain, schema_name);
            """
        )
        self._conn.commit()

    def _columns(self, table: str) -> set[str]:
        return {
            row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")
        }

    def _ensure_column(
        self,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        if column not in self._columns(table):
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _migrate_tables(self) -> None:
        """Add evidence fields to databases created by versions before Prime."""

        for column, definition in {
            "confidence": "REAL DEFAULT 0.0",
            "uncertainty": "REAL DEFAULT 1.0",
        }.items():
            self._ensure_column("extraction_history", column, definition)

        for column, definition in {
            "status": "TEXT DEFAULT 'candidate'",
            "baseline_quality": "REAL DEFAULT 0.0",
            "candidate_quality": "REAL",
            "minimum_improvement": "REAL DEFAULT 0.05",
            "latency_ms": "REAL DEFAULT 0.0",
            "input_tokens": "INTEGER DEFAULT 0",
            "output_tokens": "INTEGER DEFAULT 0",
            "evaluated_at": "REAL DEFAULT 0",
        }.items():
            self._ensure_column("prompt_refinements", column, definition)

        for column, definition in {
            "reason": "TEXT DEFAULT ''",
            "evidence_count": "INTEGER DEFAULT 0",
            "supporting_evidence": "TEXT DEFAULT '[]'",
            "status": "TEXT DEFAULT 'candidate'",
            "positive_outcomes": "INTEGER DEFAULT 0",
            "negative_outcomes": "INTEGER DEFAULT 0",
            "last_quality": "REAL",
            "updated_at": "REAL DEFAULT 0",
        }.items():
            self._ensure_column("cleaning_rules", column, definition)
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cleaning_domain
            ON cleaning_rules(domain, status)
            """
        )
        self._conn.commit()

    def get_domain_profile(self, domain: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM domain_profiles WHERE domain = ?",
            (domain,),
        ).fetchone()
        return dict(row) if row else None

    def update_domain_profile(
        self,
        domain: str,
        success: bool,
        quality_score: float,
        wait_seconds: float | None = None,
    ) -> None:
        now = time.time()
        existing = self.get_domain_profile(domain)
        if existing:
            alpha = 0.3
            new_avg = alpha * quality_score + (1 - alpha) * existing["avg_quality"]
            values: dict[str, Any] = {
                "total_scrapes": existing["total_scrapes"] + 1,
                "total_successes": (existing["total_successes"] + int(success)),
                "total_failures": (existing["total_failures"] + int(not success)),
                "avg_quality": round(new_avg, 3),
                "last_scraped": now,
                "updated_at": now,
            }
            if wait_seconds is not None:
                values["wait_seconds"] = wait_seconds
            assignments = ", ".join(f"{key} = ?" for key in values)
            self._conn.execute(
                f"UPDATE domain_profiles SET {assignments} WHERE domain = ?",
                (*values.values(), domain),
            )
        else:
            self._conn.execute(
                """
                INSERT INTO domain_profiles (
                    domain, wait_seconds, avg_quality, total_scrapes,
                    total_successes, total_failures, last_scraped,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    domain,
                    2.0 if wait_seconds is None else wait_seconds,
                    quality_score,
                    int(success),
                    int(not success),
                    now,
                    now,
                    now,
                ),
            )
        self._conn.commit()

    def get_learned_wait_seconds(self, domain: str) -> float:
        profile = self.get_domain_profile(domain)
        return float(profile["wait_seconds"]) if profile else 2.0

    def set_domain_wait_seconds(self, domain: str, wait_seconds: float) -> None:
        """Update an existing domain's timing without counting another scrape."""

        self._conn.execute(
            """
            UPDATE domain_profiles
            SET wait_seconds = ?, updated_at = ?
            WHERE domain = ?
            """,
            (wait_seconds, time.time(), domain),
        )
        self._conn.commit()

    def log_extraction(
        self,
        url: str,
        schema_name: str,
        results_count: int,
        quality_score: float,
        fill_rate: float,
        duration_secs: float,
        model_used: str = "",
        prompt_version: int = 0,
        error: str = "",
        confidence: float = 0.0,
        uncertainty: float = 1.0,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO extraction_history (
                url, domain, schema_name, results_count, quality_score,
                confidence, uncertainty, fill_rate, duration_secs,
                model_used, prompt_version, error, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                urlparse(url).netloc,
                schema_name,
                results_count,
                quality_score,
                confidence,
                uncertainty,
                fill_rate,
                duration_secs,
                model_used,
                prompt_version,
                error,
                time.time(),
            ),
        )
        self._conn.commit()

    def get_domain_history(
        self,
        domain: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM extraction_history
            WHERE domain = ? ORDER BY timestamp DESC LIMIT ?
            """,
            (domain, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_success_rate(self, domain: str) -> float:
        profile = self.get_domain_profile(domain)
        if not profile or profile["total_scrapes"] == 0:
            return 0.0
        return profile["total_successes"] / profile["total_scrapes"]

    def get_best_prompt_record(
        self,
        domain: str,
        schema_name: str,
    ) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT * FROM prompt_refinements
            WHERE domain = ? AND schema_name = ? AND status = 'accepted'
            ORDER BY candidate_quality DESC, version DESC LIMIT 1
            """,
            (domain, schema_name),
        ).fetchone()
        return dict(row) if row else None

    def get_best_prompt(
        self,
        domain: str,
        schema_name: str,
    ) -> str | None:
        record = self.get_best_prompt_record(domain, schema_name)
        return record["extra_instructions"] if record else None

    def save_prompt_candidate(
        self,
        domain: str,
        schema_name: str,
        extra_instructions: str,
        baseline_quality: float,
        *,
        minimum_improvement: float = 0.05,
        latency_ms: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> int:
        row = self._conn.execute(
            """
            SELECT MAX(version) AS max_v FROM prompt_refinements
            WHERE domain = ? AND schema_name = ?
            """,
            (domain, schema_name),
        ).fetchone()
        version = int(row["max_v"] or 0) + 1
        cursor = self._conn.execute(
            """
            INSERT INTO prompt_refinements (
                domain, schema_name, version, extra_instructions, status,
                baseline_quality, minimum_improvement, latency_ms,
                input_tokens, output_tokens, created_at
            ) VALUES (?, ?, ?, ?, 'candidate', ?, ?, ?, ?, ?, ?)
            """,
            (
                domain,
                schema_name,
                version,
                extra_instructions,
                baseline_quality,
                minimum_improvement,
                latency_ms,
                input_tokens,
                output_tokens,
                time.time(),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid or 0)

    def evaluate_prompt_candidate(
        self,
        candidate_id: int,
        candidate_quality: float,
    ) -> bool:
        row = self._conn.execute(
            "SELECT * FROM prompt_refinements WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown prompt candidate: {candidate_id}")
        if row["status"] != "candidate":
            return row["status"] == "accepted"
        improvement = candidate_quality - row["baseline_quality"]
        accepted = improvement >= row["minimum_improvement"]
        self._conn.execute(
            """
            UPDATE prompt_refinements
            SET status = ?, candidate_quality = ?, evaluated_at = ?
            WHERE id = ?
            """,
            (
                "accepted" if accepted else "rejected",
                candidate_quality,
                time.time(),
                candidate_id,
            ),
        )
        self._conn.commit()
        return accepted

    def save_prompt_refinement(
        self,
        domain: str,
        schema_name: str,
        extra_instructions: str,
        quality_score: float,
    ) -> int:
        """Compatibility import for an explicitly trusted refinement."""

        candidate_id = self.save_prompt_candidate(
            domain,
            schema_name,
            extra_instructions,
            baseline_quality=quality_score,
            minimum_improvement=0.0,
        )
        self.evaluate_prompt_candidate(candidate_id, quality_score)
        return candidate_id

    def rollback_prompt(self, prompt_id: int) -> bool:
        cursor = self._conn.execute(
            """
            UPDATE prompt_refinements
            SET status = 'rolled_back', evaluated_at = ?
            WHERE id = ? AND status = 'accepted'
            """,
            (time.time(), prompt_id),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def increment_prompt_usage(
        self,
        domain: str,
        schema_name: str,
    ) -> None:
        record = self.get_best_prompt_record(domain, schema_name)
        if record:
            self._conn.execute(
                """
                UPDATE prompt_refinements
                SET times_used = times_used + 1 WHERE id = ?
                """,
                (record["id"],),
            )
            self._conn.commit()

    def record_cleaning_rule_evidence(
        self,
        domain: str,
        rule_type: str,
        selector: str,
        *,
        reason: str,
        evidence: str,
        confidence: float = 0.55,
        activation_threshold: int = 2,
    ) -> dict[str, Any]:
        """Store bounded evidence and activate only after repeated support."""

        if rule_type not in {"class", "id", "tag"}:
            raise ValueError(f"Unsupported cleaning rule type: {rule_type}")
        now = time.time()
        row = self._conn.execute(
            """
            SELECT * FROM cleaning_rules
            WHERE domain = ? AND rule_type = ? AND selector = ?
            ORDER BY id DESC LIMIT 1
            """,
            (domain, rule_type, selector),
        ).fetchone()
        confidence = min(max(float(confidence), 0.0), 1.0)
        if row is None:
            evidence_items = [evidence]
            combined_confidence = confidence
            evidence_count = 1
            status = "candidate"
            cursor = self._conn.execute(
                """
                INSERT INTO cleaning_rules (
                    domain, rule_type, selector, action, reason, confidence,
                    evidence_count, supporting_evidence, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'remove', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    domain,
                    rule_type,
                    selector,
                    reason,
                    combined_confidence,
                    evidence_count,
                    json.dumps(evidence_items),
                    status,
                    now,
                    now,
                ),
            )
            rule_id = int(cursor.lastrowid or 0)
        else:
            rule_id = int(row["id"])
            evidence_items = json.loads(row["supporting_evidence"] or "[]")
            if evidence not in evidence_items:
                evidence_items.append(evidence)
            evidence_items = evidence_items[-10:]
            evidence_count = int(row["evidence_count"]) + 1
            combined_confidence = 1 - (
                (1 - float(row["confidence"])) * (1 - confidence)
            )
            status = row["status"]
            if (
                status == "candidate"
                and evidence_count >= activation_threshold
                and combined_confidence >= 0.7
            ):
                status = "active"
            self._conn.execute(
                """
                UPDATE cleaning_rules
                SET reason = ?, confidence = ?, evidence_count = ?,
                    supporting_evidence = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    reason,
                    combined_confidence,
                    evidence_count,
                    json.dumps(evidence_items),
                    status,
                    now,
                    rule_id,
                ),
            )

        self._conn.commit()
        return self.get_cleaning_rule(rule_id)

    def save_cleaning_rule(
        self,
        domain: str,
        rule_type: str,
        selector: str,
        action: str = "remove",
    ) -> int:
        """Save an explicit-feedback rule as active and reversible."""

        rule = self.record_cleaning_rule_evidence(
            domain,
            rule_type,
            selector,
            reason="Explicit user feedback",
            evidence="explicit-feedback",
            confidence=1.0,
            activation_threshold=1,
        )
        self._conn.execute(
            """
            UPDATE cleaning_rules
            SET action = ?, status = 'active', evidence_count = MAX(2, evidence_count)
            WHERE id = ?
            """,
            (action, rule["id"]),
        )
        self._conn.commit()
        return int(rule["id"])

    def get_cleaning_rule(self, rule_id: int) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM cleaning_rules WHERE id = ?",
            (rule_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown cleaning rule: {rule_id}")
        return dict(row)

    def get_cleaning_rules(
        self,
        domain: str,
        *,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM cleaning_rules WHERE domain = ?"
        params: tuple[Any, ...] = (domain,)
        if active_only:
            query += " AND status = 'active'"
        query += " ORDER BY id"
        rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def disable_cleaning_rule(self, rule_id: int) -> bool:
        cursor = self._conn.execute(
            """
            UPDATE cleaning_rules
            SET status = 'disabled', updated_at = ?
            WHERE id = ? AND status IN ('active', 'candidate')
            """,
            (time.time(), rule_id),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def rollback_cleaning_rule(self, rule_id: int) -> bool:
        return self.disable_cleaning_rule(rule_id)

    def record_cleaning_rule_outcome(
        self,
        rule_id: int,
        *,
        quality: float,
        baseline_quality: float,
    ) -> str:
        """Track performance and disable a repeatedly regressive rule."""

        row = self.get_cleaning_rule(rule_id)
        improved = quality >= baseline_quality + 0.02
        negative = quality < baseline_quality - 0.05
        positive_outcomes = int(row["positive_outcomes"]) + int(improved)
        negative_outcomes = int(row["negative_outcomes"]) + int(negative)
        times_applied = int(row["times_applied"]) + 1
        status = row["status"]
        if (
            status == "active"
            and times_applied >= 2
            and positive_outcomes == 0
            and negative_outcomes >= 2
        ):
            status = "disabled"
        self._conn.execute(
            """
            UPDATE cleaning_rules
            SET times_applied = ?, positive_outcomes = ?,
                negative_outcomes = ?, last_quality = ?,
                status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                times_applied,
                positive_outcomes,
                negative_outcomes,
                quality,
                status,
                time.time(),
                rule_id,
            ),
        )
        self._conn.commit()
        return status

    def record_feedback(
        self,
        url: str,
        schema_name: str,
        feedback_type: str,
        details: str = "",
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO feedback (
                url, domain, schema_name, feedback_type, details, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                urlparse(url).netloc,
                schema_name,
                feedback_type,
                details,
                time.time(),
            ),
        )
        self._conn.commit()

    def get_stats(self) -> dict[str, Any]:
        scalar_queries = {
            "total_scrapes": "SELECT COUNT(*) FROM extraction_history",
            "unique_domains": ("SELECT COUNT(DISTINCT domain) FROM extraction_history"),
            "avg_quality": "SELECT AVG(quality_score) FROM extraction_history",
            "total_refinements": (
                "SELECT COUNT(*) FROM prompt_refinements WHERE status = 'accepted'"
            ),
            "candidate_refinements": (
                "SELECT COUNT(*) FROM prompt_refinements WHERE status = 'candidate'"
            ),
            "active_cleaning_rules": (
                "SELECT COUNT(*) FROM cleaning_rules WHERE status = 'active'"
            ),
            "total_feedback": "SELECT COUNT(*) FROM feedback",
        }
        stats = {
            key: self._conn.execute(query).fetchone()[0] or 0
            for key, query in scalar_queries.items()
        }
        top = self._conn.execute(
            """
            SELECT domain, total_scrapes, avg_quality,
                   total_successes, total_failures
            FROM domain_profiles
            ORDER BY total_scrapes DESC LIMIT 10
            """
        ).fetchall()
        stats["top_domains"] = [dict(row) for row in top]
        return stats

    def close(self) -> None:
        if not self._closed:
            self._conn.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        if hasattr(self, "_closed"):
            self.close()
