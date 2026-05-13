"""Phase 6 — Dashboard memory stats tests.

Two layers:

* Pure-ish tests on :func:`get_project_memory_stats` using a temp dir
  to stand in for the wraps storage root. Reuses
  :class:`WrapFlaskTestCase` for the user + project fixtures.

* HTTP tests through the Flask test client for the two new routes:
  ``GET /projects/:pid/wraps/stats`` and ``GET /wraps/stats``.

We also re-exercise :func:`format_bytes` (Phase 1) at the boundaries
that the dashboard cares about — B / KB / MB rounding — because the
frontend treats the byte count as a raw int and renders it via a
JS-side mirror of the same function.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from tests.test_wrap_phase3 import WrapFlaskTestCase  # noqa: E402

from app.models import Project  # noqa: E402
from app.extensions import db  # noqa: E402
from app.services.wrap_memory import (  # noqa: E402
    WrapServiceError,
    format_bytes,
    get_all_project_memory_stats,
    get_project_memory_stats,
)
from app.services.wrap_memory.storage import (  # noqa: E402
    PROJECT_MEMORY_DIRNAME,
    WRAPS_DIRNAME,
)


def _wraps_dir(base_dir: str, project_id: int) -> Path:
    return (
        Path(base_dir)
        / PROJECT_MEMORY_DIRNAME
        / WRAPS_DIRNAME
        / str(project_id)
    )


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ===========================================================================
# Service tests.


class GetProjectMemoryStatsTest(WrapFlaskTestCase):
    def test_missing_directory_returns_zeros(self) -> None:
        stats = get_project_memory_stats(
            user=self.alice, project=self.project, base_dir=self.tmp.name
        )
        self.assertEqual(stats.wrap_count, 0)
        self.assertEqual(stats.memory_size_bytes, 0)
        self.assertIsNone(stats.last_wrapped_at)
        # Identity fields survive even when there's nothing on disk.
        self.assertEqual(stats.project_id, self.project.id)
        self.assertEqual(stats.project_name, "Auth Service")

    def test_empty_directory_returns_zeros(self) -> None:
        # Create the wraps dir but put nothing inside it.
        _wraps_dir(self.tmp.name, self.project.id).mkdir(
            parents=True, exist_ok=True
        )
        stats = get_project_memory_stats(
            user=self.alice, project=self.project, base_dir=self.tmp.name
        )
        self.assertEqual(stats.wrap_count, 0)
        self.assertEqual(stats.memory_size_bytes, 0)
        self.assertIsNone(stats.last_wrapped_at)

    def test_counts_markdown_files_and_sums_bytes(self) -> None:
        wd = _wraps_dir(self.tmp.name, self.project.id)
        _write(wd / "a.md", "x" * 100)
        _write(wd / "b.md", "y" * 250)
        _write(wd / "c.md", "z" * 50)
        stats = get_project_memory_stats(
            user=self.alice, project=self.project, base_dir=self.tmp.name
        )
        self.assertEqual(stats.wrap_count, 3)
        self.assertEqual(stats.memory_size_bytes, 400)

    def test_ignores_non_markdown_files(self) -> None:
        wd = _wraps_dir(self.tmp.name, self.project.id)
        _write(wd / "wrap.md", "x" * 100)
        _write(wd / "readme.txt", "ignore me")
        _write(wd / "sidecar.json", '{"ignored": true}')
        stats = get_project_memory_stats(
            user=self.alice, project=self.project, base_dir=self.tmp.name
        )
        self.assertEqual(stats.wrap_count, 1)
        self.assertEqual(stats.memory_size_bytes, 100)

    def test_ignores_subdirectories(self) -> None:
        wd = _wraps_dir(self.tmp.name, self.project.id)
        _write(wd / "wrap.md", "x" * 100)
        (wd / "archive").mkdir()
        _write(wd / "archive" / "old.md", "y" * 999)
        stats = get_project_memory_stats(
            user=self.alice, project=self.project, base_dir=self.tmp.name
        )
        self.assertEqual(stats.wrap_count, 1)
        self.assertEqual(stats.memory_size_bytes, 100)

    def test_last_wrapped_at_picks_newest_mtime(self) -> None:
        wd = _wraps_dir(self.tmp.name, self.project.id)
        oldest = _write(wd / "oldest.md", "a" * 10)
        middle = _write(wd / "middle.md", "b" * 10)
        newest = _write(wd / "newest.md", "c" * 10)
        # Use distinct, monotonically increasing mtimes so we don't
        # depend on the writer's clock resolution.
        os.utime(oldest, (1_000_000, 1_000_000))
        os.utime(middle, (2_000_000, 2_000_000))
        os.utime(newest, (3_000_000, 3_000_000))

        stats = get_project_memory_stats(
            user=self.alice, project=self.project, base_dir=self.tmp.name
        )
        self.assertEqual(stats.wrap_count, 3)
        self.assertIsNotNone(stats.last_wrapped_at)
        # We picked the largest of the three mtimes — exactly 3_000_000.
        self.assertEqual(int(stats.last_wrapped_at.timestamp()), 3_000_000)

    def test_cross_user_project_raises_404(self) -> None:
        with self.assertRaises(WrapServiceError) as ctx:
            get_project_memory_stats(
                user=self.bob, project=self.project, base_dir=self.tmp.name
            )
        self.assertEqual(ctx.exception.status, 404)


class GetAllProjectMemoryStatsTest(WrapFlaskTestCase):
    def test_batch_returns_one_entry_per_project(self) -> None:
        # Add a second project owned by alice.
        other = Project(user_id=self.alice.id, name="Web App", description="")
        db.session.add(other)
        db.session.commit()

        # Project 1 has 2 wraps, project 2 has 1.
        wd1 = _wraps_dir(self.tmp.name, self.project.id)
        _write(wd1 / "a.md", "x" * 100)
        _write(wd1 / "b.md", "y" * 200)
        wd2 = _wraps_dir(self.tmp.name, other.id)
        _write(wd2 / "first.md", "z" * 50)

        stats_list = get_all_project_memory_stats(
            user=self.alice,
            projects=[self.project, other],
            base_dir=self.tmp.name,
        )
        self.assertEqual(len(stats_list), 2)
        by_id = {s.project_id: s for s in stats_list}
        self.assertEqual(by_id[self.project.id].wrap_count, 2)
        self.assertEqual(by_id[self.project.id].memory_size_bytes, 300)
        self.assertEqual(by_id[other.id].wrap_count, 1)
        self.assertEqual(by_id[other.id].memory_size_bytes, 50)

    def test_batch_skips_projects_not_owned_by_user(self) -> None:
        bobs = Project(user_id=self.bob.id, name="Spy")
        db.session.add(bobs)
        db.session.commit()
        # Even with foreign rows in the list, only alice's projects
        # come back — defense in depth against route-layer slips.
        stats_list = get_all_project_memory_stats(
            user=self.alice,
            projects=[self.project, bobs],
            base_dir=self.tmp.name,
        )
        self.assertEqual(len(stats_list), 1)
        self.assertEqual(stats_list[0].project_id, self.project.id)


# ===========================================================================
# format_bytes — sanity check the rendering buckets the dashboard uses.


class FormatBytesTest(unittest.TestCase):
    def test_zero(self) -> None:
        self.assertEqual(format_bytes(0), "0 B")

    def test_bytes(self) -> None:
        self.assertEqual(format_bytes(900), "900 B")

    def test_kilobytes(self) -> None:
        # 1024 → 1 KB (we don't need to commit to a specific decimal
        # precision; assert the unit + the leading digits).
        out = format_bytes(1024)
        self.assertTrue(out.endswith("KB"))
        self.assertTrue(out.startswith("1"))

    def test_megabytes(self) -> None:
        out = format_bytes(5 * 1024 * 1024)
        self.assertTrue(out.endswith("MB"))
        self.assertTrue(out.startswith("5"))


# ===========================================================================
# HTTP routes.


class MemoryStatsRoutesTest(WrapFlaskTestCase):
    def _auth(self, user=None):
        return self.auth_headers(user or self.alice)

    def test_per_project_route_returns_zeros_when_empty(self) -> None:
        resp = self.client.get(
            f"/api/projects/{self.project.id}/wraps/stats",
            headers=self._auth(),
        )
        self.assertEqual(resp.status_code, 200)
        s = resp.get_json()["stats"]
        self.assertEqual(s["wrapCount"], 0)
        self.assertEqual(s["memorySizeBytes"], 0)
        self.assertIsNone(s["lastWrappedAt"])
        self.assertEqual(s["projectId"], self.project.id)
        self.assertEqual(s["projectName"], "Auth Service")

    def test_per_project_route_picks_up_files_written_by_save(self) -> None:
        # Drive the actual save endpoint to make sure the stats route
        # observes the exact filesystem layout the writer uses.
        from app.services.wrap_memory import save_wrap_draft

        save_wrap_draft(
            user=self.alice,
            project=self.project,
            markdown="# Hello\n",
            filename="2026-05-13_22-30_hello.md",
            base_dir=self.tmp.name,
        )

        resp = self.client.get(
            f"/api/projects/{self.project.id}/wraps/stats",
            headers=self._auth(),
        )
        s = resp.get_json()["stats"]
        self.assertEqual(s["wrapCount"], 1)
        self.assertGreater(s["memorySizeBytes"], 0)
        self.assertIsNotNone(s["lastWrappedAt"])

    def test_per_project_route_other_user_gets_404(self) -> None:
        resp = self.client.get(
            f"/api/projects/{self.project.id}/wraps/stats",
            headers=self._auth(self.bob),
        )
        self.assertEqual(resp.status_code, 404)

    def test_per_project_route_requires_auth(self) -> None:
        resp = self.client.get(
            f"/api/projects/{self.project.id}/wraps/stats"
        )
        self.assertEqual(resp.status_code, 401)

    def test_batch_route_returns_one_entry_per_owned_project(self) -> None:
        other = Project(user_id=self.alice.id, name="Other")
        db.session.add(other)
        db.session.commit()

        wd = _wraps_dir(self.tmp.name, other.id)
        _write(wd / "x.md", "abc" * 10)

        resp = self.client.get(
            "/api/wraps/stats", headers=self._auth()
        )
        self.assertEqual(resp.status_code, 200)
        rows = resp.get_json()["stats"]
        self.assertEqual(len(rows), 2)
        ids = {r["projectId"] for r in rows}
        self.assertEqual(ids, {self.project.id, other.id})
        other_row = next(r for r in rows if r["projectId"] == other.id)
        self.assertEqual(other_row["wrapCount"], 1)

    def test_batch_route_only_shows_calling_users_projects(self) -> None:
        bobs = Project(user_id=self.bob.id, name="Bobs", description="")
        db.session.add(bobs)
        db.session.commit()
        resp = self.client.get(
            "/api/wraps/stats", headers=self._auth(self.alice)
        )
        rows = resp.get_json()["stats"]
        self.assertNotIn(bobs.id, {r["projectId"] for r in rows})


if __name__ == "__main__":
    unittest.main()
