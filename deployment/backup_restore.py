"""Offline-consistent Compose backups and restore into NEW project volumes only.

Run from the repository with ``python -m deployment.backup_restore --help``.
Backups contain private data, but never include .env or raw signing/chat keys.
Keep those keys separately in a password manager and encrypt/offsite the backup.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from deployment.volume_archive import validate_archive


ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ("database.sql", "media.tar.gz", "private_vault.tar.gz")
KEYS = ("SECRET_KEY", "CERT_SIGNING_KEY", "CHAT_MASTER_KEK")
STATE_VOLUMES = ("mysql_data", "redis_data", "media_data", "vault_data")
WRITERS = ("nginx", "scheduler", "web")
DUMP = 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysqldump --protocol=TCP -h 127.0.0.1 -u "$MYSQL_USER" --single-transaction --quick --skip-lock-tables --no-tablespaces --set-gtid-purged=OFF --triggers "$MYSQL_DATABASE"'
IMPORT = 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql --protocol=TCP -h 127.0.0.1 -u "$MYSQL_USER" "$MYSQL_DATABASE"'


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def key_fingerprints(environment):
    values = [str(environment.get(key) or "") for key in KEYS]
    if any(len(value) < 32 for value in values) or len(set(values)) != len(KEYS):
        raise ValueError("Configure three independent production keys of at least 32 characters")
    return {key: hashlib.sha256(value.encode()).hexdigest() for key, value in zip(KEYS, values)}


class Compose:
    def __init__(self, *, project, env_file):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
            raise ValueError("Invalid Compose project name")
        self.project = project
        env_file = Path(env_file).resolve(strict=True)
        self.environment = dict(os.environ, KMG_ENV_FILE=str(env_file))
        self.prefix = ["docker", "compose", "--project-name", project, "--env-file", str(env_file), "--file", str(ROOT / "compose.yaml")]

    def run(self, arguments, **kwargs):
        return subprocess.run(self.prefix + list(arguments), cwd=ROOT, env=self.environment, check=True, **kwargs)

    def capture(self, arguments):
        return self.run(arguments, stdout=subprocess.PIPE, text=True).stdout

    def config(self):
        # Effective configuration contains secrets: capture in memory, never print it.
        return json.loads(self.capture(["config", "--format", "json"]))


def validate_backup(directory):
    directory = Path(directory).resolve(strict=True)
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Manifest must be a regular file")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("format_version") != 1
        or not isinstance(manifest.get("artifacts"), dict)
        or set(manifest["artifacts"]) != set(ARTIFACTS)
    ):
        raise ValueError("Unsupported or incomplete backup manifest")
    for name in ARTIFACTS:
        path = directory / name
        expected = manifest["artifacts"][name]
        if not isinstance(expected, dict):
            raise ValueError(f"Invalid backup metadata: {name}")
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing or linked backup artifact: {name}")
        if path.stat().st_size != expected.get("bytes") or digest(path) != expected.get("sha256"):
            raise ValueError(f"Backup checksum mismatch: {name}")
    for name in ARTIFACTS[1:]:
        validate_archive(directory / name)
    return manifest


def require_fresh_target(compose, config, manifest, existing_volumes):
    if compose.project == manifest.get("source_project"):
        raise ValueError("Restore requires a different, fresh Compose project")
    if key_fingerprints(config["services"]["web"]["environment"]) != manifest.get("key_fingerprints"):
        raise ValueError("Restore keys differ from the backup; recover the original keys first")
    for key in STATE_VOLUMES:
        volume = config["volumes"][key]
        if volume.get("external") or volume.get("name") != f"{compose.project}_{key}":
            raise ValueError("Restore refuses external or non-project storage volumes")
        if volume["name"] in existing_volumes:
            raise ValueError("Restore target has existing volumes; choose a fresh project")
    if compose.capture(["ps", "--all", "--quiet"]).strip():
        raise ValueError("Restore target has existing containers; choose a fresh project")


def backup(compose, destination):
    config = compose.config()
    fingerprints = key_fingerprints(config["services"]["web"]["environment"])
    running = set(compose.capture(["ps", "--services", "--status", "running"]).splitlines())
    if "db" not in running:
        raise ValueError("Source database must be running")
    destination = Path(destination).absolute()
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    resume = [service for service in WRITERS if service in running]
    try:
        # Prevent DB/file divergence. Operator must stop any writers outside this stack too.
        compose.run(["stop", "--timeout", "60", *WRITERS])
        for name in ARTIFACTS:
            target = destination / name
            with target.open("xb") as output:
                target.chmod(0o600)
                if name == "database.sql":
                    compose.run(["exec", "-T", "db", "sh", "-c", DUMP], stdout=output)
                else:
                    storage = name.removesuffix(".tar.gz")
                    compose.run(["run", "--rm", "--no-deps", "-T", "web", "python", "-m", "deployment.volume_archive", "export", storage], stdout=output)
        for name in ARTIFACTS[1:]:
            validate_archive(destination / name)
        manifest = {
            "format_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_project": compose.project,
            "database_engine": "mysql:8.4",
            "source_image": config["services"]["web"].get("image"),
            "key_fingerprints": fingerprints,
            "artifacts": {name: {"bytes": (destination / name).stat().st_size, "sha256": digest(destination / name)} for name in ARTIFACTS},
        }
        # A missing manifest identifies an incomplete backup. Only write it at the end.
        manifest_path = destination / "manifest.json"
        pending_path = destination / "manifest.pending.json"
        with pending_path.open("x", encoding="utf-8") as output:
            pending_path.chmod(0o600)
            json.dump(manifest, output, indent=2)
        pending_path.replace(manifest_path)
        validate_backup(destination)
    finally:
        if resume:
            compose.run(["start", *resume])
    print(f"Verified backup: {destination}")


def restore(compose, source):
    source = Path(source).resolve(strict=True)
    manifest = validate_backup(source)
    config = compose.config()
    volumes = subprocess.run(["docker", "volume", "ls", "--format", "{{.Name}}"], check=True, stdout=subprocess.PIPE, text=True).stdout.splitlines()
    require_fresh_target(compose, config, manifest, set(volumes))
    # Never start app/scheduler before validation. Failed restores keep new target
    # volumes for diagnosis and cannot be retried over partially restored data.
    compose.run(["up", "-d", "--wait", "--wait-timeout", "180", "db", "redis"])
    with (source / "database.sql").open("rb") as sql:
        compose.run(["exec", "-T", "db", "sh", "-c", IMPORT], stdin=sql)
    for name in ARTIFACTS[1:]:
        storage = name.removesuffix(".tar.gz")
        with (source / name).open("rb") as archive:
            compose.run(["run", "--rm", "--no-deps", "-T", "web", "python", "-m", "deployment.volume_archive", "restore", storage], stdin=archive)
    print(f"Restored into new project {compose.project}. Web and scheduler remain stopped; validate data before starting them.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("backup", "restore"):
        command = subparsers.add_parser(action)
        command.add_argument("--project", required=True)
        command.add_argument("--env-file", required=True)
        if action == "backup":
            command.add_argument("--output", required=True, help="New directory inside an existing protected parent")
            command.add_argument("--maintenance", required=True, action="store_true", help="Acknowledge brief stop of nginx, web and scheduler")
        else:
            command.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        compose = Compose(project=args.project, env_file=args.env_file)
        if args.action == "backup":
            backup(compose, args.output)
        else:
            restore(compose, args.input)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        # Do not echo subprocess stdout/config/environment, which may contain secrets.
        print(f"{args.action} failed: {type(error).__name__}. No existing restore target is overwritten; inspect the command error above.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
