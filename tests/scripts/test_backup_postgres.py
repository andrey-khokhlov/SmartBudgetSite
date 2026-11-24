from contextlib import nullcontext
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from scripts import backup_postgres as job


def old_name(day):
    return f"smartbudget-auto-202610{day:02d}T030000000000Z.dump"


class FakeTools:
    def __init__(self):
        self.archive = b"synthetic custom archive"
        self.remote = {}
        self.commands = []
        self.failure = None
        self.inventory = None
        self.deleted = []

    def run(self, args, *, stdin, stdout, stderr, check):
        operation = args[2] if args[0] == "rclone" else args[len(job.DB_EXEC)]
        self.commands.append(operation)
        assert stderr == subprocess.DEVNULL
        assert not check
        if operation == "pg_dump":
            assert "--username=smartbudget" in args
            assert "--no-password" in args
            assert "--format=custom" in args
            stdout.write(self.archive)
        elif operation == "pg_restore":
            assert args[-1] == "--file=/dev/null"
            assert stdin.read() == self.archive
        elif operation == "copyto":
            assert args[-1].endswith(".pending")
            self.remote[args[-1]] = Path(args[-2]).read_bytes()
        elif operation == "moveto" and self.failure != "moveto":
            self.remote[args[-1]] = self.remote.pop(args[-2])
        elif operation == "lsjson":
            names = self.inventory
            if names is None:
                names = [
                    {"Path": name.rsplit("/", 1)[-1], "IsDir": False}
                    for name in self.remote
                ]
            return subprocess.CompletedProcess(
                args, int(self.failure == operation), json.dumps(names).encode()
            )
        elif operation == "deletefile":
            assert "--drive-use-trash=false" in args
            self.deleted.append(args[-1])
            if self.failure != operation:
                self.remote.pop(args[-1])
        return subprocess.CompletedProcess(args, int(self.failure == operation))

    def digest(self, name):
        self.commands.append("cat")
        assert name.endswith(".pending")
        data = self.remote[name] if self.failure != "hash" else b"incorrect bytes"
        return hashlib.sha256(data).digest()


@pytest.fixture
def tools(monkeypatch):
    fake = FakeTools()
    clock = Mock()
    clock.now.return_value = datetime(2026, 11, 24, 3, tzinfo=UTC)
    monkeypatch.setattr(job, "datetime", clock)
    monkeypatch.setattr(job.subprocess, "run", fake.run)
    monkeypatch.setattr(job, "remote_digest", fake.digest)
    return fake


def seed_backups(directory, tools):
    # Seed in reverse order to verify retention uses filenames, not listing order.
    for day in range(18, 0, -1):
        name = old_name(day)
        (directory / name).write_bytes(b"older dump")
        tools.remote[f"{job.REMOTE}/{name}"] = b"older dump"


def test_success_verifies_before_publication_and_retains_only_automated_files(
    tmp_path, tools, capsys
):
    seed_backups(tmp_path, tools)
    excluded = [
        "manual.dump",
        "pre-migration.dump",
        "post-migration.dump",
        old_name(1) + ".notes",
        "." + old_name(1) + ".pending",
    ]
    for name in excluded:
        (tmp_path / name).write_bytes(b"keep")
        tools.remote[f"{job.REMOTE}/{name}"] = b"keep"
    (tmp_path / old_name(20)).mkdir()
    job.backup(tmp_path)

    local = sorted(
        p.name
        for p in tmp_path.iterdir()
        if p.is_file() and job.BACKUP_NAME.fullmatch(p.name)
    )
    remote = sorted(
        key.rsplit("/", 1)[-1]
        for key in tools.remote
        if job.BACKUP_NAME.fullmatch(key.rsplit("/", 1)[-1])
    )
    assert local == [old_name(day) for day in range(13, 19)] + [local[-1]]
    assert remote == [old_name(day) for day in range(5, 19)] + [local[-1]]
    assert (tmp_path / local[-1]).read_bytes() == tools.remote[
        f"{job.REMOTE}/{local[-1]}"
    ]
    assert (tmp_path / old_name(20)).is_dir()
    assert all((tmp_path / name).read_bytes() == b"keep" for name in excluded)
    assert all(tools.remote[f"{job.REMOTE}/{name}"] == b"keep" for name in excluded)
    assert tools.commands[:6] == [
        "pg_dump",
        "pg_restore",
        "copyto",
        "cat",
        "moveto",
        "lsjson",
    ]
    assert tools.deleted == [f"{job.REMOTE}/{old_name(day)}" for day in range(1, 5)]
    assert not list(tmp_path.glob(".postgresql-backup-*"))
    assert "status=completed" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("failure", "reason", "pending_cleanup"),
    [
        ("pg_dump", "pg_dump", False),
        ("pg_restore", "archive validation", False),
        ("copyto", "encrypted upload", True),
        ("hash", "SHA-256 mismatch", True),
        ("moveto", "remote publication", True),
        ("lsjson", "remote inventory", False),
    ],
)
def test_failure_leaves_previous_backups_and_cleans_attempt(
    tmp_path, tools, capsys, failure, reason, pending_cleanup
):
    seed_backups(tmp_path, tools)
    tools.failure = failure
    original_remote = tools.remote.copy()
    with pytest.raises(job.BackupError, match=reason):
        job.backup(tmp_path)

    assert all((tmp_path / old_name(day)).is_file() for day in range(1, 19))
    assert all(tools.remote[name] == data for name, data in original_remote.items())
    assert len(tools.deleted) == int(pending_cleanup)
    assert all(name.endswith(".pending") for name in tools.deleted)
    assert all(not name.endswith(".pending") for name in tools.remote)
    assert len(tools.remote) == len(original_remote) + (failure == "lsjson")
    assert not list(tmp_path.glob(".postgresql-backup-*"))
    assert "status=completed" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("inventory", "reason"),
    [
        ([], "new backup missing"),
        ([{"Path": "unrelated", "IsDir": True}], "invalid remote inventory"),
        ([{"Path": old_name(1), "IsDir": False}] * 2, "duplicate automated names"),
    ],
)
def test_ambiguity_in_remote_inventory_blocks_all_retention(
    tmp_path, tools, inventory, reason
):
    seed_backups(tmp_path, tools)
    tools.inventory = inventory
    with pytest.raises(job.BackupError, match=reason):
        job.backup(tmp_path)
    assert not tools.deleted
    assert len(list(tmp_path.glob("*.dump"))) == 19


def test_remote_delete_failure_stops_retention_before_local_deletion(tmp_path, tools):
    seed_backups(tmp_path, tools)
    tools.failure = "deletefile"
    with pytest.raises(job.BackupError, match="remote retention"):
        job.backup(tmp_path)
    assert tools.deleted == [f"{job.REMOTE}/{old_name(1)}"]
    assert len(list(tmp_path.glob("*.dump"))) == len(tools.remote) == 19


@pytest.mark.skipif(os.name != "posix", reason="host backup uses Linux flock")
def test_busy_lock_blocks_second_invocation_and_is_reusable(tmp_path):
    tmp_path.chmod(0o700)
    with job.backup_lock(tmp_path):
        with pytest.raises(job.BackupBusy), job.backup_lock(tmp_path):
            pytest.fail("second invocation reached backup work")
    with job.backup_lock(tmp_path):
        assert (tmp_path / ".postgresql-backup.lock").stat().st_mode & 0o777 == 0o600


def test_main_reports_overlap_as_non_success(monkeypatch, capsys):
    def busy(_):
        raise job.BackupBusy

    monkeypatch.setattr(job, "backup_lock", busy)
    monkeypatch.setattr(job, "backup", lambda _: pytest.fail("backup ran without lock"))
    monkeypatch.setattr(job.signal, "signal", lambda *_: None)
    monkeypatch.setattr(job.os, "umask", lambda _: None)
    assert job.main() == 75
    assert "status=blocked reason=overlap" in capsys.readouterr().err


def test_main_reports_operational_failure_without_success(monkeypatch, capsys):
    def fail(_):
        raise job.BackupError("remote SHA-256 mismatch")

    monkeypatch.setattr(job, "backup_lock", lambda _: nullcontext())
    monkeypatch.setattr(job, "backup", fail)
    monkeypatch.setattr(job.signal, "signal", lambda *_: None)
    monkeypatch.setattr(job.os, "umask", lambda _: None)
    assert job.main() == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert "status=failed reason=remote SHA-256 mismatch" in captured.err
