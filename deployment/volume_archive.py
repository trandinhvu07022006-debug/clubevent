"""Stream public/private storage archives without following links or restoring owners."""
import argparse
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile


ROOTS = {"media": Path("/app/media"), "private_vault": Path("/app/private_vault")}


def validate_archive(path):
    """Check all members before any extraction writes to a volume."""
    seen = set()
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            name = member.name
            parts = name.split("/")
            if (
                not name or name.startswith("/") or "\\" in name
                or any(part in ("", ".", "..") for part in parts)
                or ":" in name or not (member.isfile() or member.isdir())
                or name in seen
            ):
                raise ValueError("Unsafe or duplicate archive entry")
            seen.add(name)
        # A regular file must never also be the parent of another entry.
        files = {member.name for member in archive.getmembers() if member.isfile()}
        for name in seen:
            if any(str(parent) in files for parent in PurePosixPath(name).parents):
                raise ValueError("Archive file conflicts with a directory")


def export_archive(root, output, *, public=False):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Storage root must be a regular directory")
    paths = sorted(root.rglob("*"))
    if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in paths):
        raise ValueError("Storage contains links or special files; backup refused")
    with tarfile.open(fileobj=output, mode="w|gz") as archive:
        for path in paths:
            info = archive.gettarinfo(str(path), arcname=path.relative_to(root).as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = (0o755 if info.isdir() else 0o644) if public else (0o700 if info.isdir() else 0o600)
            if not (info.isfile() or info.isdir()):
                raise ValueError("Storage contains linked or special files; backup refused")
            if info.isfile():
                with path.open("rb") as source:
                    archive.addfile(info, source)
            else:
                archive.addfile(info)


def restore_archive(path, root, *, public=False):
    validate_archive(path)
    if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
        raise ValueError("Restore requires an existing empty storage directory")
    directory_mode, file_mode = (0o755, 0o644) if public else (0o700, 0o600)
    root.chmod(directory_mode)

    def ensure_directory(directory):
        current = root
        for part in directory.relative_to(root).parts:
            current = current / part
            current.mkdir(exist_ok=True, mode=directory_mode)
            current.chmod(directory_mode)

    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            target = root.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                ensure_directory(target)
            else:
                ensure_directory(target.parent)
                with target.open("xb") as destination, archive.extractfile(member) as source:
                    target.chmod(file_mode)
                    shutil.copyfileobj(source, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "restore"))
    parser.add_argument("storage", choices=ROOTS)
    args = parser.parse_args()
    root = ROOTS[args.storage]
    if args.action == "export":
        export_archive(root, sys.stdout.buffer, public=args.storage == "media")
    else:
        with tempfile.TemporaryDirectory(prefix="kmg-restore-") as temporary:
            archive_path = Path(temporary) / "storage.tar.gz"
            with archive_path.open("xb") as output:
                shutil.copyfileobj(sys.stdin.buffer, output)
            restore_archive(archive_path, root, public=args.storage == "media")


if __name__ == "__main__":
    main()
