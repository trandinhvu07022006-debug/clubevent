"""Backup integrity, safe extraction and refusal to overwrite existing deployments."""
from copy import deepcopy
from io import BytesIO, StringIO
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from deployment import backup_restore as backups
from deployment import volume_archive


def archive_bytes(entries):
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, value in entries:
            info = tarfile.TarInfo(name)
            if isinstance(value, bytes):
                info.size = len(value)
                archive.addfile(info, BytesIO(value))
            else:
                info.type = value[1]
                info.linkname = "../../outside" if info.type in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ""
                archive.addfile(info)
    return output.getvalue()


def configuration(project):
    return {
        "services": {"web": {"image": "kmg-app:local", "environment": {
            key: key + "-test-only-" + "x" * 40 for key in backups.KEYS
        }}},
        "volumes": {key: {"name": f"{project}_{key}"} for key in backups.STATE_VOLUMES},
    }


class FakeCompose:
    def __init__(self, project="pilot", *, fail_dump=False, running="db\nweb\nnginx\nscheduler\n"):
        self.project = project
        self.fail_dump = fail_dump
        self.running = running
        self.calls = []
        self.containers = ""
        self.effective = configuration(project)

    def config(self):
        return self.effective

    def capture(self, arguments):
        self.calls.append(list(arguments))
        return self.running if "--services" in arguments else self.containers

    def run(self, arguments, **kwargs):
        self.calls.append(list(arguments))
        if "stdout" in kwargs:
            if "exec" in arguments:
                if self.fail_dump:
                    raise subprocess.CalledProcessError(1, ["fake-dump"])
                kwargs["stdout"].write(b"CREATE TABLE restore_check (id int);\n")
            else:
                kwargs["stdout"].write(archive_bytes([("nested/file.bin", b"sample\x00data")]))
        if "stdin" in kwargs:
            self.last_input = kwargs["stdin"].read()


class StorageArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="kmg-archive-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / "storage.tar.gz"
        self.destination = self.root / "target"
        self.destination.mkdir()

    def test_roundtrip_preserves_binary_files_and_empty_directories(self):
        source = self.root / "source"
        (source / "empty").mkdir(parents=True)
        (source / "nested").mkdir()
        (source / "nested" / "file.bin").write_bytes(b"\x00\xff\x01content")
        with self.archive.open("wb") as output:
            volume_archive.export_archive(source, output, public=True)
        volume_archive.restore_archive(self.archive, self.destination, public=True)
        self.assertEqual((self.destination / "nested" / "file.bin").read_bytes(), b"\x00\xff\x01content")
        self.assertTrue((self.destination / "empty").is_dir())
        with tarfile.open(self.archive) as archive:
            self.assertEqual(archive.getmember("nested/file.bin").mode, 0o644)
            self.assertEqual(archive.getmember("nested").mode, 0o755)
            self.assertEqual(archive.getmember("nested/file.bin").uname, "")

    def test_public_and_private_permissions_are_explicit(self):
        self.archive.write_bytes(archive_bytes([("nested/deeper/file", b"content")]))
        for public, directory_mode, file_mode in ((True, 0o755, 0o644), (False, 0o700, 0o600)):
            target = self.root / str(public)
            target.mkdir()
            with patch.object(Path, "chmod", autospec=True) as chmod:
                volume_archive.restore_archive(self.archive, target, public=public)
                calls = [(call.args[0], call.args[1]) for call in chmod.call_args_list]
                self.assertIn((target, directory_mode), calls)
                self.assertIn((target / "nested", directory_mode), calls)
                self.assertIn((target / "nested/deeper", directory_mode), calls)
                self.assertIn((target / "nested/deeper/file", file_mode), calls)

    def test_unsafe_archive_rejected_before_any_extraction(self):
        invalid_entries = [
            [("../outside", b"bad")], [("/absolute", b"bad")],
            [("C:/outside", b"bad")], [("file:stream", b"bad")],
            [("folder\\outside", b"bad")], [("folder//file", b"bad")],
            [("folder/./file", b"bad")], [("folder/../file", b"bad")],
            [("same", b"one"), ("same", b"two")],
            [("parent", b"file"), ("parent/child", b"bad")],
            [("link", ("type", tarfile.SYMTYPE))], [("link", ("type", tarfile.LNKTYPE))],
            [("device", ("type", tarfile.CHRTYPE))],
        ]
        for entries in invalid_entries:
            with self.subTest(entries=entries):
                self.archive.write_bytes(archive_bytes(entries))
                with self.assertRaises(ValueError):
                    volume_archive.restore_archive(self.archive, self.destination)
                self.assertEqual(list(self.destination.iterdir()), [])

    def test_restore_refuses_nonempty_storage(self):
        existing = self.destination / "keep.txt"
        existing.write_text("keep", encoding="utf-8")
        self.archive.write_bytes(archive_bytes([("new.txt", b"new")]))
        with self.assertRaisesRegex(ValueError, "empty"):
            volume_archive.restore_archive(self.archive, self.destination)
        self.assertEqual(existing.read_text(), "keep")
        self.assertFalse((self.destination / "new.txt").exists())

    def test_export_rejects_missing_root(self):
        with self.assertRaises(ValueError):
            volume_archive.export_archive(self.root / "missing", BytesIO())

    def test_export_refuses_symlinks(self):
        linked = self.destination / "link"
        try:
            linked.symlink_to(self.root / "elsewhere")
        except OSError:
            self.skipTest("Symlink creation unavailable on this host")
        with self.assertRaises(ValueError):
            volume_archive.export_archive(self.destination, BytesIO())


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="kmg-backup-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "snapshot"
        self.stdout = patch("sys.stdout", new_callable=StringIO)
        self.stdout.start()
        self.addCleanup(self.stdout.stop)

    def make_backup(self):
        compose = FakeCompose()
        backups.backup(compose, self.output)
        return compose, backups.validate_backup(self.output)

    def test_backup_stops_writers_before_reading_and_resumes_them(self):
        compose, manifest = self.make_backup()
        self.assertEqual(compose.calls[1], ["stop", "--timeout", "60", *backups.WRITERS])
        self.assertEqual(compose.calls[-1], ["start", *backups.WRITERS])
        self.assertEqual(set(manifest["artifacts"]), set(backups.ARTIFACTS))
        serialized = (self.output / "manifest.json").read_text()
        for key in backups.KEYS:
            self.assertNotIn(compose.effective["services"]["web"]["environment"][key], serialized)
        self.assertFalse((self.output / "manifest.pending.json").exists())

    def test_dump_failure_resumes_only_previously_running_services(self):
        compose = FakeCompose(fail_dump=True, running="db\nweb\n")
        with self.assertRaises(subprocess.CalledProcessError):
            backups.backup(compose, self.output)
        self.assertEqual(compose.calls[-1], ["start", "web"])
        self.assertFalse((self.output / "manifest.json").exists())

    def test_backup_refuses_existing_directory_without_stopping_source(self):
        self.output.mkdir()
        compose = FakeCompose()
        with self.assertRaises(FileExistsError):
            backups.backup(compose, self.output)
        self.assertFalse(any(command[0] == "stop" for command in compose.calls))

    def test_tampering_fails_before_docker_or_restore(self):
        self.make_backup()
        (self.output / "database.sql").write_bytes(b"tampered")
        target = FakeCompose("restore_new")
        with patch.object(target, "config") as config, patch("subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "checksum"):
                backups.restore(target, self.output)
            config.assert_not_called()
            run.assert_not_called()

    def test_malformed_manifest_rejected(self):
        self.output.mkdir()
        for payload in ([], {}, {"format_version": 1, "artifacts": []}):
            (self.output / "manifest.json").write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                backups.validate_backup(self.output)

    def test_restore_refuses_source_project_existing_volumes_and_containers(self):
        _, manifest = self.make_backup()
        source = FakeCompose()
        with self.assertRaisesRegex(ValueError, "different"):
            backups.require_fresh_target(source, source.config(), manifest, set())
        target = FakeCompose("restore_new")
        with self.assertRaisesRegex(ValueError, "existing volumes"):
            backups.require_fresh_target(target, target.config(), manifest, {"restore_new_mysql_data"})
        target.containers = "existing-container-id"
        with self.assertRaisesRegex(ValueError, "existing containers"):
            backups.require_fresh_target(target, target.config(), manifest, set())

    def test_restore_refuses_wrong_keys_or_external_or_custom_volume(self):
        _, manifest = self.make_backup()
        target = FakeCompose("restore_new")
        config = deepcopy(target.config())
        config["services"]["web"]["environment"]["CHAT_MASTER_KEK"] = "different-key-" + "z" * 40
        with self.assertRaisesRegex(ValueError, "keys differ"):
            backups.require_fresh_target(target, config, manifest, set())
        for volume_change in ({"external": True}, {"name": "pilot_mysql_data"}):
            config = deepcopy(target.config())
            config["volumes"]["mysql_data"].update(volume_change)
            with self.assertRaisesRegex(ValueError, "storage volumes"):
                backups.require_fresh_target(target, config, manifest, set())

    def test_restore_loads_only_new_storage_without_starting_writers(self):
        self.make_backup()
        target = FakeCompose("restore_new")
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout="")):
            backups.restore(target, self.output)
        up = next(command for command in target.calls if command[0] == "up")
        self.assertEqual(up[-2:], ["db", "redis"])
        self.assertFalse(any(command[0] == "start" for command in target.calls))
        self.assertEqual(len([command for command in target.calls if command[0] == "run"]), 2)


if __name__ == "__main__":
    unittest.main()
