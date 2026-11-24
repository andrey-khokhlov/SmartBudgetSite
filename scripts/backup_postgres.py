"""Create, verify and retain one SmartBudgetSite PostgreSQL backup on Linux."""

import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

BACKUP_DIR = Path("/var/backups/smartbudget")
REMOTE = "gdrive_crypt:postgresql-automated"
BACKUP_NAME = re.compile(r"smartbudget-auto-[0-9]{8}T[0-9]{12}Z\.dump")
LOCAL_KEEP = 7
REMOTE_KEEP = 15
DB_EXEC = (
    "docker",
    "compose",
    "--env-file",
    "/etc/smartbudget/compose.env",
    "-f",
    "compose.prod.yml",
    "exec",
    "-T",
    "db",
)
RCLONE = ("rclone", "--stats=0")
PERMANENT_DELETE = "--drive-use-trash=false"


class BackupError(Exception):
    """An operational failure with a message safe for the journal."""


class BackupBusy(BackupError):
    """Another invocation holds the host backup lock."""


@contextmanager
def backup_lock(directory):
    import fcntl

    info = directory.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
    ):
        raise BackupError("backup directory must be owned by the job user and private")
    lock = os.open(
        directory / ".postgresql-backup.lock",
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
        0o600,
    )
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackupBusy("backup already running") from None
        yield
    finally:
        os.close(lock)


def run_command(
    stage, args, *, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, allowed=(0,)
):
    # Tool diagnostics can contain configuration details. Report the stage and
    # exit status without forwarding child stderr or printing its arguments.
    result = subprocess.run(
        args, stdin=stdin, stdout=stdout, stderr=subprocess.DEVNULL, check=False
    )
    if result.returncode not in allowed:
        raise BackupError(f"{stage} failed (exit={result.returncode})")
    return result.stdout


def remote_digest(path):
    with subprocess.Popen(
        (*RCLONE, "cat", path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process:
        try:
            digest = hashlib.file_digest(process.stdout, "sha256").digest()
        except BaseException:
            process.kill()
            raise
        status = process.wait()
    if status:
        raise BackupError(f"remote download failed (exit={status})")
    return digest


def remote_inventory(remote):
    data = run_command(
        "remote inventory",
        (*RCLONE, "lsjson", "--files-only", remote),
        stdout=subprocess.PIPE,
    )
    try:
        entries = json.loads(data)
    except ValueError:
        raise BackupError("invalid remote inventory") from None
    if not isinstance(entries, list):
        raise BackupError("invalid remote inventory")
    names = []
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("Path"), str)
            or entry.get("IsDir") is not False
        ):
            raise BackupError("invalid remote inventory")
        if BACKUP_NAME.fullmatch(entry["Path"]):
            names.append(entry["Path"])
    if len(names) != len(set(names)):
        raise BackupError("duplicate automated names in remote inventory")
    return names


def expired_names(names, keep, current):
    ordered = sorted(names)
    if current not in ordered[-keep:]:
        raise BackupError("new backup missing or too old to retain")
    return ordered[:-keep]


def delete_remote(path, *, pending=False):
    run_command(
        "pending cleanup" if pending else "remote retention",
        (*RCLONE, "deletefile", PERMANENT_DELETE, path),
        allowed=(0, 3, 4) if pending else (0,),
    )


def backup(directory, remote=REMOTE):
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    name = f"smartbudget-auto-{stamp}.dump"
    pending = f"{remote}/.{name}.pending"
    published = f"{remote}/{name}"
    with TemporaryDirectory(prefix=".postgresql-backup-", dir=directory) as temp:
        archive = Path(temp) / "archive.dump"
        with archive.open("xb") as stream:
            run_command(
                "pg_dump",
                (
                    *DB_EXEC,
                    "pg_dump",
                    "--host=/var/run/postgresql",
                    "--username=smartbudget",
                    "--dbname=smartbudget",
                    "--no-password",
                    "--format=custom",
                ),
                stdout=stream,
            )
            stream.flush()
            os.fsync(stream.fileno())
        with archive.open("rb") as stream:
            # Emit SQL to /dev/null to read and decompress the archive without
            # opening a database session or running a restore.
            run_command(
                "archive validation",
                (*DB_EXEC, "pg_restore", "--file=/dev/null"),
                stdin=stream,
            )
        with archive.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").digest()

        try:
            run_command(
                "encrypted upload", (*RCLONE, "copyto", "--immutable", archive, pending)
            )
            if remote_digest(pending) != digest:
                raise BackupError("remote SHA-256 mismatch")
            # Crypt and Drive support a server-side move within this remote.
            run_command(
                "remote publication",
                (
                    *RCLONE,
                    "moveto",
                    "--immutable",
                    PERMANENT_DELETE,
                    pending,
                    published,
                ),
            )
        except (BackupError, OSError):
            try:
                delete_remote(pending, pending=True)
            except (BackupError, OSError):
                print("status=warning stage=pending_cleanup", file=sys.stderr)
            raise

        # Link in the same filesystem to publish atomically without overwriting
        # a previously completed archive even if its name collides.
        os.link(archive, directory / name)

    remote_expired = expired_names(remote_inventory(remote), REMOTE_KEEP, name)
    local_names = [
        path.name
        for path in directory.iterdir()
        if BACKUP_NAME.fullmatch(path.name) and stat.S_ISREG(path.lstat().st_mode)
    ]
    local_expired = expired_names(local_names, LOCAL_KEEP, name)
    for old in remote_expired:
        delete_remote(f"{remote}/{old}")
    for old in local_expired:
        (directory / old).unlink()
    print(
        f"status=completed backup={name} local_pruned={len(local_expired)} remote_pruned={len(remote_expired)}"
    )


def interrupted(signum, frame):
    raise BackupError("backup interrupted")


def main():
    os.umask(0o077)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        with backup_lock(BACKUP_DIR):
            backup(BACKUP_DIR)
    except BackupBusy:
        print("status=blocked reason=overlap", file=sys.stderr)
        return 75
    except BackupError as exc:
        print(f"status=failed reason={exc}", file=sys.stderr)
        return 1
    except OSError:
        print("status=failed reason=local I/O or command launch", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
