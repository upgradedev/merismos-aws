"""The dependency layer hashed differently every time identical packages were zipped.

infra/build.sh zipped the installed packages with zip(1), which stores each file's
modification time and the order the filesystem listed it. The dry run straight
after the 2026-09-13 apply (Actions run 34773349052) therefore planned to replace
the layer it had just published and to update all four functions with it, with no
dependency changed, so the plan could never be read as a drift check. These tests
hold the archive to one rule: the same files give the same bytes.
"""

import base64
import hashlib
import importlib.util
import os
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("package_backend", ROOT / "infra/package_backend.py")
PACKAGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGER)

FILES = {
    "python/alpha.pth": b"import alpha\n",
    "python/strands/__init__.py": b"VERSION = '1'\n",
    "python/strands/agent/core.py": b"def run():\n    return 42\n",
    "python/zeta/_speedups.so": b"\x7fELF not really a shared object",
}


def install(build: Path, order, mtime: int) -> None:
    for name in order:
        path = build / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(FILES[name])
        os.utime(path, (mtime, mtime))


def digest(path: Path) -> str:
    return base64.b64encode(hashlib.sha256(path.read_bytes()).digest()).decode()


def test_the_same_packages_zip_to_the_same_bytes_whatever_the_order_and_time(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    install(first, sorted(FILES), mtime=1_700_000_000)
    install(second, sorted(FILES, reverse=True), mtime=1_800_000_000)

    one = PACKAGER.zip_layer(first)
    two = PACKAGER.zip_layer(second)

    assert (first / "deps.zip").read_bytes() == (second / "deps.zip").read_bytes()
    assert one == two == digest(first / "deps.zip")


def test_the_archive_is_sorted_timeless_and_rooted_at_python(tmp_path):
    install(tmp_path, FILES, mtime=1_750_000_000)
    PACKAGER.zip_layer(tmp_path)
    with zipfile.ZipFile(tmp_path / "deps.zip") as archive:
        infos = archive.infolist()
        assert [info.filename for info in infos] == sorted(FILES)
        assert {info.date_time for info in infos} == {(2026, 1, 1, 0, 0, 0)}
        assert all(archive.read(name) == content for name, content in FILES.items())


def test_a_changed_package_changes_the_hash(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    install(first, FILES, mtime=1)
    install(second, FILES, mtime=1)
    (second / "python/strands/__init__.py").write_bytes(b"VERSION = '2'\n")
    assert PACKAGER.zip_layer(first) != PACKAGER.zip_layer(second)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_an_executable_keeps_its_bit_and_every_other_mode_is_normalised(tmp_path):
    install(tmp_path, FILES, mtime=1)
    (tmp_path / "python/zeta/_speedups.so").chmod(0o755)
    (tmp_path / "python/alpha.pth").chmod(0o600)
    PACKAGER.zip_layer(tmp_path)
    with zipfile.ZipFile(tmp_path / "deps.zip") as archive:
        modes = {info.filename: info.external_attr >> 16 for info in archive.infolist()}
    assert modes["python/zeta/_speedups.so"] == 0o755
    assert modes["python/alpha.pth"] == 0o644


def test_a_stale_archive_is_never_appended_to(tmp_path):
    install(tmp_path, FILES, mtime=1)
    (tmp_path / "deps.zip").write_bytes(b"stale")
    with pytest.raises(FileExistsError):
        PACKAGER.zip_layer(tmp_path)


def test_build_sh_uses_the_reproducible_writer_and_drops_console_scripts():
    script = (ROOT / "infra/build.sh").read_text(encoding="utf-8")
    assert 'package_backend.py" --layer' in script
    assert "zip -qr" not in script
    assert 'rm -rf "${target}/bin"' in script
    assert script.index("pip list") < script.index('-name "*.dist-info"')
