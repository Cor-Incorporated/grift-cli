"""Race-resistant primitives for publishing private output artifacts.

The helpers deliberately keep user-supplied paths lexical.  Calling
``Path.resolve()`` before checking the path would make a user-managed parent
symlink indistinguishable from the intended destination.
"""

from __future__ import annotations

import os
import secrets
import stat
import sys
from dataclasses import dataclass
from pathlib import Path


class SecureOutputError(ValueError):
    """A destination cannot be used without following an unsafe link."""


_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


@dataclass
class SecureParent:
    """An anchored parent directory and its final lexical member name."""

    path: Path
    fd: int
    leaf: str

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> SecureParent:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


@dataclass
class SecureDirectory:
    """A directory opened without following a user-managed link."""

    path: Path
    fd: int

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> SecureDirectory:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def lexical_absolute(path: Path) -> Path:
    """Return an absolute path without resolving any filesystem links."""

    raw = os.fspath(path)
    if "\0" in raw:
        raise SecureOutputError("output path contains a NUL byte")
    if ".." in Path(raw).parts:
        raise SecureOutputError("output path must not contain '..'")
    absolute = Path(os.path.abspath(raw))
    if absolute == Path(absolute.anchor):
        raise SecureOutputError("filesystem root cannot be an output path")
    return absolute


def open_secure_parent(path: Path, *, create: bool) -> SecureParent:
    """Open a destination parent one component at a time with no link follow."""

    absolute = lexical_absolute(path)
    components = absolute.parts[1:-1]
    current_fd = os.open(absolute.anchor, _DIRECTORY_FLAGS)
    current_path = Path(absolute.anchor)
    try:
        root_stat = os.fstat(current_fd)
        for index, component in enumerate(components):
            try:
                entry_stat = os.stat(component, dir_fd=current_fd, follow_symlinks=False)
            except FileNotFoundError:
                if not create:
                    raise SecureOutputError(
                        f"output parent is missing: {current_path / component}"
                    ) from None
                try:
                    os.mkdir(component, mode=0o700, dir_fd=current_fd)
                except OSError as exc:
                    raise SecureOutputError(
                        f"output parent cannot be created: {current_path / component}"
                    ) from exc
                entry_stat = os.stat(component, dir_fd=current_fd, follow_symlinks=False)
            except OSError as exc:
                raise SecureOutputError(
                    f"output parent cannot be inspected: {current_path / component}"
                ) from exc

            follows_trusted_alias = stat.S_ISLNK(entry_stat.st_mode) and trusted_top_alias(
                index=index,
                component=component,
                entry_stat=entry_stat,
                root_stat=root_stat,
            )
            if stat.S_ISLNK(entry_stat.st_mode) and not follows_trusted_alias:
                raise SecureOutputError(
                    f"output parent must not be a symlink: {current_path / component}"
                )
            if not stat.S_ISDIR(entry_stat.st_mode) and not follows_trusted_alias:
                raise SecureOutputError(
                    f"output parent must be a directory: {current_path / component}"
                )

            flags = _DIRECTORY_FLAGS | (0 if follows_trusted_alias else _NOFOLLOW)
            try:
                next_fd = os.open(component, flags, dir_fd=current_fd)
            except OSError as exc:
                raise SecureOutputError(
                    f"output parent cannot be opened safely: {current_path / component}"
                ) from exc
            opened_stat = os.fstat(next_fd)
            if not stat.S_ISDIR(opened_stat.st_mode):
                os.close(next_fd)
                raise SecureOutputError(
                    f"output parent must be a directory: {current_path / component}"
                )
            if not follows_trusted_alias and (
                opened_stat.st_dev != entry_stat.st_dev or opened_stat.st_ino != entry_stat.st_ino
            ):
                os.close(next_fd)
                raise SecureOutputError(
                    f"output parent changed while it was opened: {current_path / component}"
                )
            if create and not follows_trusted_alias and stat.S_IMODE(entry_stat.st_mode) == 0:
                os.close(next_fd)
                raise SecureOutputError(
                    f"output parent has unusable permissions: {current_path / component}"
                )
            os.close(current_fd)
            current_fd = next_fd
            current_path /= component
        return SecureParent(current_path, current_fd, absolute.name)
    except Exception:
        os.close(current_fd)
        raise


def open_secure_directory(path: Path, *, required_mode: int | None = None) -> SecureDirectory:
    """Open an existing lexical directory and optionally enforce its exact mode."""

    with open_secure_parent(path, create=False) as parent:
        try:
            entry_stat = os.stat(parent.leaf, dir_fd=parent.fd, follow_symlinks=False)
        except OSError as exc:
            raise SecureOutputError("output directory is unavailable") from exc
        if stat.S_ISLNK(entry_stat.st_mode) or not stat.S_ISDIR(entry_stat.st_mode):
            raise SecureOutputError("output directory must be a non-symlink directory")
        try:
            directory_fd = os.open(parent.leaf, _DIRECTORY_FLAGS | _NOFOLLOW, dir_fd=parent.fd)
        except OSError as exc:
            raise SecureOutputError("output directory cannot be opened safely") from exc
        opened_stat = os.fstat(directory_fd)
        if opened_stat.st_dev != entry_stat.st_dev or opened_stat.st_ino != entry_stat.st_ino:
            os.close(directory_fd)
            raise SecureOutputError("output directory changed while it was opened")
        if required_mode is not None and stat.S_IMODE(opened_stat.st_mode) != required_mode:
            os.close(directory_fd)
            raise SecureOutputError(f"output directory permissions must be {required_mode:04o}")
        return SecureDirectory(parent.path / parent.leaf, directory_fd)


def lstat_at(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SecureOutputError(f"output member cannot be inspected: {name}") from exc


def open_directory_at(parent_fd: int, name: str, *, required_mode: int | None = None) -> int:
    metadata = lstat_at(parent_fd, name)
    if metadata is None or stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise SecureOutputError(f"output member must be a non-symlink directory: {name}")
    try:
        directory_fd = os.open(name, _DIRECTORY_FLAGS | _NOFOLLOW, dir_fd=parent_fd)
    except OSError as exc:
        raise SecureOutputError(f"output directory cannot be opened safely: {name}") from exc
    opened = os.fstat(directory_fd)
    if opened.st_dev != metadata.st_dev or opened.st_ino != metadata.st_ino:
        os.close(directory_fd)
        raise SecureOutputError(f"output directory changed while it was opened: {name}")
    if required_mode is not None and stat.S_IMODE(opened.st_mode) != required_mode:
        os.close(directory_fd)
        raise SecureOutputError(f"output directory permissions must be {required_mode:04o}: {name}")
    return directory_fd


def require_absent_at(directory_fd: int, name: str) -> None:
    if lstat_at(directory_fd, name) is not None:
        raise SecureOutputError(f"output destination already exists: {name}")


def create_private_directory_at(directory_fd: int, *, prefix: str) -> tuple[str, int]:
    for _attempt in range(64):
        name = f"{prefix}{secrets.token_hex(12)}"
        try:
            os.mkdir(name, mode=0o700, dir_fd=directory_fd)
        except FileExistsError:
            continue
        except OSError as exc:
            raise SecureOutputError("private staging directory cannot be created") from exc
        try:
            child_fd = os.open(name, _DIRECTORY_FLAGS | _NOFOLLOW, dir_fd=directory_fd)
            os.fchmod(child_fd, 0o700)
        except OSError as exc:
            try:
                os.rmdir(name, dir_fd=directory_fd)
            except OSError:
                pass
            raise SecureOutputError("private staging directory cannot be opened") from exc
        return name, child_fd
    raise SecureOutputError("private staging directory name could not be allocated")


def write_private_at(directory_fd: int, name: str, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
    except OSError as exc:
        raise SecureOutputError(f"private output member cannot be created: {name}") from exc
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fsync(fd)
    except OSError as exc:
        raise SecureOutputError(f"private output member cannot be written: {name}") from exc
    finally:
        os.close(fd)


def read_private_at(directory_fd: int, name: str, *, required_mode: int = 0o600) -> bytes:
    flags = os.O_RDONLY | _NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise SecureOutputError(f"private output member cannot be opened: {name}") from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise SecureOutputError(f"private output member is not regular: {name}")
        if stat.S_IMODE(metadata.st_mode) != required_mode:
            raise SecureOutputError(
                f"private output member permissions must be {required_mode:04o}: {name}"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def set_private_file_mode_at(directory_fd: int, name: str) -> None:
    flags = os.O_RDONLY | _NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise SecureOutputError(f"private output member cannot be opened: {name}") from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size == 0:
            raise SecureOutputError(
                f"private output member must be a non-empty regular file: {name}"
            )
        os.fchmod(fd, 0o600)
        os.fsync(fd)
    finally:
        os.close(fd)


def validate_closed_directory_at(
    directory_fd: int,
    expected_names: set[str],
    *,
    required_file_mode: int | None = None,
) -> None:
    try:
        actual_names = set(os.listdir(directory_fd))
    except OSError as exc:
        raise SecureOutputError("output directory cannot be enumerated") from exc
    if actual_names != expected_names:
        raise SecureOutputError("output directory contains missing or unregistered members")
    for name in expected_names:
        metadata = lstat_at(directory_fd, name)
        if metadata is None or stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise SecureOutputError(f"output member must be a regular non-symlink file: {name}")
        if required_file_mode is not None and stat.S_IMODE(metadata.st_mode) != required_file_mode:
            raise SecureOutputError(
                f"output member permissions must be {required_file_mode:04o}: {name}"
            )


def remove_directory_at(parent_fd: int, name: str) -> None:
    """Remove an anchored tree without following any member symlinks."""

    metadata = lstat_at(parent_fd, name)
    if metadata is None:
        return
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        os.unlink(name, dir_fd=parent_fd)
        return
    child_fd = os.open(name, _DIRECTORY_FLAGS | _NOFOLLOW, dir_fd=parent_fd)
    try:
        for member in os.listdir(child_fd):
            member_stat = lstat_at(child_fd, member)
            if (
                member_stat is not None
                and stat.S_ISDIR(member_stat.st_mode)
                and not stat.S_ISLNK(member_stat.st_mode)
            ):
                remove_directory_at(child_fd, member)
            else:
                os.unlink(member, dir_fd=child_fd)
    finally:
        os.close(child_fd)
    os.rmdir(name, dir_fd=parent_fd)


def fsync_directory(directory_fd: int) -> None:
    try:
        os.fsync(directory_fd)
    except OSError as exc:
        raise SecureOutputError("output directory cannot be synchronized") from exc


def trusted_top_alias(
    *, index: int, component: str, entry_stat: os.stat_result, root_stat: os.stat_result
) -> bool:
    """Allow only macOS's root-managed ``/tmp`` and ``/var`` aliases.

    The filesystem root must itself be root-owned and immutable to ordinary
    users.  No other symlink, including a same-named link below ``/``, receives
    this exception.
    """

    return (
        sys.platform == "darwin"
        and index == 0
        and component in {"tmp", "var"}
        and entry_stat.st_uid == 0
        and root_stat.st_uid == 0
        and stat.S_IMODE(root_stat.st_mode) & 0o022 == 0
    )


# Internal compatibility for callers shipped before the helper was made public.
_trusted_top_alias = trusted_top_alias
