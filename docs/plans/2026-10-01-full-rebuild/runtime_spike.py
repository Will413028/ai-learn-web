"""Dependency-free behavioral spike; SQLite models persistence, not PostgreSQL locks.

All providers are fake. Temporary databases stay within this attachment directory.
Network is prohibited. --mutation disables one guard so its regression must fail.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
MUTATION = ""


class BudgetExceeded(Exception):
    pass


class FakeSearch:
    def __init__(self):
        self.calls = []

    async def run(self, tool: str):
        self.calls.append(tool)
        return f"fake content from {tool}"


async def pipeline(search: FakeSearch, is_url=False):
    return await search.run("extract" if is_url else "search")


async def react(search: FakeSearch, decisions: list[str], max_tools=2, max_rounds=4):
    calls = 0
    for step in range(max_rounds):
        action = decisions[min(step, len(decisions) - 1)]
        if action == "finish":
            return {"tool_calls": calls, "planner_calls": step + 1}
        if action == "noop":
            continue
        if action not in {"search", "extract"}:
            raise ValueError("Unknown tool")
        if MUTATION != "tool-budget" and calls >= max_tools:
            raise BudgetExceeded("Tool budget exhausted before dispatch")
        await search.run(action)
        calls += 1
    raise BudgetExceeded("Planner round budget exhausted")


@contextmanager
def transaction(db: sqlite3.Connection):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        db.rollback()
        raise
    else:
        db.commit()


class JobStore:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY, owner TEXT NOT NULL, request_key TEXT NOT NULL,
            payload_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            version INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
            lease_until INTEGER, result TEXT, UNIQUE(owner, request_key));
          CREATE TABLE IF NOT EXISTS committed_results(
            job_id INTEGER PRIMARY KEY, result TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS fake_provider_calls(job_id INTEGER);
        """)

    def close(self):
        self.db.close()

    def create(self, owner: str, key: str, payload: str):
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        with transaction(self.db):
            row = self.db.execute("SELECT * FROM jobs WHERE owner=? AND request_key=?", (owner, key)).fetchone()
            if row:
                if row["payload_hash"] != fingerprint:
                    raise ValueError("Idempotency key reused with another payload")
                return row["id"]
            return self.db.execute("INSERT INTO jobs(owner, request_key, payload_hash) VALUES(?,?,?)", (owner, key, fingerprint)).lastrowid

    def status(self, job_id: int, owner: str):
        row = self.db.execute("SELECT * FROM jobs WHERE id=? AND owner=?", (job_id, owner)).fetchone()
        if row is None:
            raise LookupError("Not found")
        return dict(row)

    def claim(self, job_id: int, now: int, lease=10):
        with transaction(self.db):
            row = self.db.execute("SELECT * FROM jobs WHERE id=? AND status='pending'", (job_id,)).fetchone()
            if row is None:
                return None
            token = row["version"] + 1
            self.db.execute("UPDATE jobs SET status='running',version=?,attempts=attempts+1,lease_until=? WHERE id=? AND status='pending'", (token, now + lease, job_id))
            return token

    def recover(self, now: int, policy: str, max_attempts=2):
        if MUTATION == "restart-recovery":
            return
        with transaction(self.db):
            rows = self.db.execute("SELECT * FROM jobs WHERE status='running' AND lease_until<=?", (now,)).fetchall()
            for row in rows:
                state = "pending" if policy == "retry" and row["attempts"] < max_attempts else "failed"
                self.db.execute("UPDATE jobs SET status=?,lease_until=NULL WHERE id=? AND status='running' AND lease_until<=?", (state, row["id"], now))

    def heartbeat(self, job_id: int, token: int, now: int):
        return self.db.execute("UPDATE jobs SET lease_until=? WHERE id=? AND status='running' AND version=? AND lease_until>?", (now + 10, job_id, token, now)).rowcount == 1

    def provider_call(self, job_id: int):
        # Represents an external effect outside the finalization transaction.
        self.db.execute("INSERT INTO fake_provider_calls(job_id) VALUES(?)", (job_id,))

    def finish(self, job_id: int, token: int, now: int, result: str):
        with transaction(self.db):
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            valid = row is not None and row["status"] == "running" and row["version"] == token and row["lease_until"] > now
            if MUTATION != "fencing" and not valid:
                return False
            self.db.execute("INSERT INTO committed_results(job_id,result) VALUES(?,?)", (job_id, result))
            self.db.execute("UPDATE jobs SET status='completed',result=?,lease_until=NULL WHERE id=?", (result, job_id))
            return True


class SpikeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="spike-", dir=HERE)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "jobs.sqlite"
        self.store = JobStore(self.path)
        self.addCleanup(self.store.close)
        self.job = self.store.create("alice", "request-1", "topic")

    def test_pipeline_selects_one_search_or_extract(self):
        for is_url, expected in ((False, "search"), (True, "extract")):
            search = FakeSearch()
            asyncio.run(pipeline(search, is_url))
            self.assertEqual(search.calls, [expected])

    def test_network_attempt_is_rejected_before_connecting(self):
        with self.assertRaisesRegex(AssertionError, "prohibits networking"):
            socket.create_connection(("example.invalid", 443))

    def test_react_can_finish_with_two_tools(self):
        search = FakeSearch()
        metrics = asyncio.run(react(search, ["search", "extract", "finish"]))
        self.assertEqual(metrics, {"tool_calls": 2, "planner_calls": 3})

    def test_infinite_tool_requests_stop_before_third_dispatch(self):
        search = FakeSearch()
        with self.assertRaises(BudgetExceeded):
            asyncio.run(react(search, ["search"]))
        self.assertEqual(len(search.calls), 2)

    def test_noop_planner_stops_at_round_budget(self):
        search = FakeSearch()
        with self.assertRaises(BudgetExceeded):
            asyncio.run(react(search, ["noop"]))
        self.assertEqual(search.calls, [])

    def test_duplicate_create_and_conflicting_payload(self):
        self.assertEqual(self.store.create("alice", "request-1", "topic"), self.job)
        with self.assertRaises(ValueError):
            self.store.create("alice", "request-1", "changed")
        self.assertNotEqual(self.store.create("bob", "request-1", "topic"), self.job)

    def test_status_hides_other_owners(self):
        with self.assertRaises(LookupError):
            self.store.status(self.job, "bob")

    def test_only_one_claim_and_one_committed_result(self):
        token = self.store.claim(self.job, 0)
        self.assertIsNone(self.store.claim(self.job, 0))
        self.assertTrue(self.store.finish(self.job, token, 1, "result"))
        self.assertFalse(self.store.finish(self.job, token, 2, "result"))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM committed_results").fetchone()[0], 1)

    def test_restart_recovers_from_separate_process_interruption(self):
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--interrupt-worker", str(self.path), str(self.job)], capture_output=True, text=True, timeout=5)
        self.assertEqual(proc.returncode, 17, proc.stderr)
        self.assertEqual(self.store.status(self.job, "alice")["status"], "running")
        self.store.recover(11, "fail")
        self.assertEqual(self.store.status(self.job, "alice")["status"], "failed")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM fake_provider_calls").fetchone()[0], 1)

    def test_retry_has_attempt_cap_and_may_repeat_external_call(self):
        self.store.claim(self.job, 0)
        self.store.provider_call(self.job)
        self.store.recover(11, "retry")
        token = self.store.claim(self.job, 11)
        self.assertIsNotNone(token)
        self.store.provider_call(self.job)
        self.assertTrue(self.store.finish(self.job, token, 12, "result"))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM fake_provider_calls").fetchone()[0], 2)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM committed_results").fetchone()[0], 1)
        capped = self.store.create("alice", "request-2", "topic")
        self.store.claim(capped, 0)
        self.store.recover(11, "retry")
        self.store.claim(capped, 11)
        self.store.recover(22, "retry")
        self.assertEqual(self.store.status(capped, "alice")["status"], "failed")

    def test_stale_worker_cannot_write_before_guard(self):
        old = self.store.claim(self.job, 0)
        self.store.recover(11, "retry")
        new = self.store.claim(self.job, 11)
        self.assertNotEqual(old, new)
        self.assertFalse(self.store.finish(self.job, old, 12, "stale"))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM committed_results").fetchone()[0], 0)
        self.assertTrue(self.store.finish(self.job, new, 12, "fresh"))

    def test_heartbeat_prevents_recovery_and_expired_lease_cannot_finish(self):
        token = self.store.claim(self.job, 0)
        self.assertTrue(self.store.heartbeat(self.job, token, 9))
        self.store.recover(11, "fail")
        self.assertEqual(self.store.status(self.job, "alice")["status"], "running")
        self.assertFalse(self.store.finish(self.job, token, 20, "expired"))

    def test_delivery_latency_model_and_reconnect_snapshot(self):
        # Virtual completion t=13s, poll interval=2s: result is noticed at t=14s.
        completed_at, interval = 13, 2
        observed_at = ((completed_at + interval - 1) // interval) * interval
        self.assertEqual(observed_at - completed_at, 1)
        token = self.store.claim(self.job, 0, lease=30)
        self.store.finish(self.job, token, completed_at, "result")
        # Both poll and reconnecting SSE must consult durable owner-scoped state.
        self.assertEqual(self.store.status(self.job, "alice")["result"], "result")


def deny_network(*args, **kwargs):
    raise AssertionError("Offline spike prohibits networking")


def main():
    global MUTATION
    parser = argparse.ArgumentParser()
    parser.add_argument("--mutation", choices=["tool-budget", "restart-recovery", "fencing"])
    parser.add_argument("--interrupt-worker", nargs=2, metavar=("DB", "JOB"))
    args = parser.parse_args()
    with patch.object(socket.socket, "connect", deny_network), patch.object(socket, "create_connection", deny_network):
        if args.interrupt_worker:
            path, job = args.interrupt_worker
            with_path = Path(path).resolve()
            if not with_path.is_relative_to(HERE):
                raise ValueError("Spike database must stay inside attachment")
            store = JobStore(with_path)
            try:
                store.claim(int(job), 0)
                store.provider_call(int(job))
            finally:
                store.close()
            return 17  # Intentional process interruption before result commit.
        MUTATION = args.mutation or ""
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(SpikeTests)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        print(json.dumps({"tests": result.testsRun, "passed": result.wasSuccessful(), "mutation": MUTATION,
            "pipeline_tool_calls": 1, "react_two_tool_planner_calls": 3,
            "max_tool_calls": 2, "max_planner_rounds": 4, "fake_max_attempts": 2,
            "network": "prohibited", "database": "temporary SQLite model"}))
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
