"""Build one OpenCode git SHA into a cached binary.

The shared clone is locked. Each SHA gets its own worktree and its own
output path, so two SHAs can compile at the same time. A crash before
``os.replace`` leaves no binary for that SHA.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from thesis.ab.durable import exclusive_lock
from thesis.ab.errors import BuildError

UPSTREAM = "https://github.com/anomalyco/opencode.git"
FALLBACK_UPSTREAM = "https://github.com/sst/opencode.git"


def _run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True)
    if proc.returncode != 0:
        raise BuildError(f"command failed ({proc.returncode}): {' '.join(cmd)}")


def bun_version(root: Path) -> str | None:
    path = root / "package.json"
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8")).get("packageManager") or ""
    if isinstance(raw, str) and raw.startswith("bun@"):
        return raw.split("@", 1)[1]
    return None


def go_version(root: Path) -> str | None:
    for relative in ("packages/tui/go.mod", "go.mod"):
        path = root / relative
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("go "):
                return line.split()[1]
    return None


def build_plan(root: Path) -> dict:
    """Describe the compile for this checkout. Does not run it."""
    script = root / "packages" / "opencode" / "script"
    build_ts = script / "build.ts"
    publish_ts = script / "publish.ts"
    bun = bun_version(root)
    if build_ts.is_file():
        text = build_ts.read_text(encoding="utf-8", errors="replace")
        args = ["bun", "script/build.ts"]
        if "--single" in text:
            args.append("--single")
        if "--skip-embed-web-ui" in text:
            args.append("--skip-embed-web-ui")
        return {
            "kind": "build.ts",
            "bun": bun,
            "go": None,
            "cwd": "packages/opencode",
            "args": args,
        }
    if publish_ts.is_file() and "bun build" in publish_ts.read_text(
        encoding="utf-8", errors="replace"
    ):
        return {
            "kind": "compile",
            "bun": bun,
            "go": go_version(root),
            "cwd": "packages/opencode",
            "args": [],
        }
    return {
        "kind": "bun-run",
        "bun": bun,
        "go": None,
        "cwd": "packages/opencode",
        "args": ["bun", "run", "./src/index.ts"],
    }


# bash.ts on the v0.x `bun build --compile` trees (no script/build.ts).
# Bun 1.2 rewrites `type: "wasm"` to /$bunfs/tree-sitter-<hash>.wasm and does
# not embed the bytes. The first bash call then aborts with ENOENT.
_TREE_SITTER_WASM_IMPORT = re.compile(
    r"""import\(\s*["'][^"']*tree-sitter[^"']*\.wasm["'][\s\S]*?type:\s*(["'])wasm\1""",
)


def tree_sitter_wasm_compile_bug(root: Path) -> bool:
    """True when this checkout's ``bun build --compile`` drops tree-sitter wasm.

    The gate is the publish-script era plus a ``type: "wasm"`` import of a
    tree-sitter wasm file. #2334 and #2367 match: both sides are
    ``packages/opencode/script/publish.ts`` with ``bun build --compile``, and
    ``bash.ts`` imports ``web-tree-sitter/tree-sitter.wasm`` and
    ``tree-sitter-bash/tree-sitter-bash.wasm`` that way.

    #3052 is the next row and still has that import, but it ships
    ``script/build.ts`` and compiles with ``Bun.build({ compile })``. This
    returns false there so that build, and every later ``build.ts`` tree, is
    left untouched.
    """
    script = Path(root) / "packages" / "opencode" / "script"
    if (script / "build.ts").is_file():
        return False
    publish = script / "publish.ts"
    if not publish.is_file():
        return False
    try:
        publish_text = publish.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if "bun build" not in publish_text:
        return False
    src = Path(root) / "packages" / "opencode" / "src"
    if not src.is_dir():
        return False
    for path in src.rglob("*.ts"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _TREE_SITTER_WASM_IMPORT.search(text):
            return True
    return False


def _rewrite_tree_sitter_wasm_imports(text: str) -> str:
    def repl(match: re.Match) -> str:
        quote = match.group(1)
        return re.sub(
            rf"type:\s*{quote}wasm{quote}",
            f"type: {quote}file{quote}",
            match.group(0),
            count=1,
        )

    return _TREE_SITTER_WASM_IMPORT.sub(repl, text)


def apply_tree_sitter_wasm_fix(root: Path) -> str:
    """Rewrite wasm imports to ``type: "file"`` on the compile-era bug.

    Returns ``file`` when a source file changed, otherwise ``unchanged``.
    ``type: "file"`` makes ``bun build --compile`` embed the bytes and return
    a path. ``Parser.init({ locateFile })`` and ``Language.load`` already
    consume that path. ``type: "wasm"`` is the loader that opens the missing
    bunfs file and aborts the process.
    """
    if not tree_sitter_wasm_compile_bug(root):
        return "unchanged"
    changed = False
    src = Path(root) / "packages" / "opencode" / "src"
    for path in src.rglob("*.ts"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        updated = _rewrite_tree_sitter_wasm_imports(text)
        if updated == text:
            continue
        path.write_text(updated, encoding="utf-8")
        changed = True
    return "file" if changed else "unchanged"


def _host() -> tuple[str, str, str]:
    system = {"Linux": "linux", "Darwin": "darwin"}.get(platform.system())
    machine = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(
        platform.machine()
    )
    goarch = {"x64": "amd64", "arm64": "arm64"}.get(machine or "")
    if not system or not machine or not goarch:
        raise BuildError(f"unsupported host {platform.system()} {platform.machine()}")
    return system, machine, goarch


def _bun_asset(version: str) -> tuple[str, str]:
    system, machine, _goarch = _host()
    name = f"bun-{system}-{machine}"
    return (
        f"https://github.com/oven-sh/bun/releases/download/bun-v{version}/{name}.zip",
        f"{name}/bun",
    )


def ensure_bun(version: str, cache: Path) -> Path:
    dest = cache / "bun" / version / "bun"
    if dest.is_file() and os.access(dest, os.X_OK):
        return dest
    url, member = _bun_asset(version)
    dest.parent.mkdir(parents=True, exist_ok=True)
    blob = dest.parent / "bun.zip"
    urllib.request.urlretrieve(url, blob)
    with zipfile.ZipFile(blob) as zf:
        zf.extract(member, dest.parent)
    extracted = dest.parent / member
    os.replace(extracted, dest)
    dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
    return dest


def _go_ok(version: str) -> bool:
    try:
        proc = subprocess.run(["go", "version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = (proc.stdout or "") + (proc.stderr or "")
    want = tuple(int(part) for part in version.split(".")[:2])
    for token in text.split():
        if token.startswith("go") and token[2:3].isdigit():
            nums = token[2:].split(".")
            try:
                got = (int(nums[0]), int(nums[1]))
            except (ValueError, IndexError):
                continue
            return got >= want
    return False


def ensure_go(version: str, cache: Path) -> str | None:
    """Return a PATH prefix that contains a new enough ``go``, or None to use the host."""
    if _go_ok(version):
        return None
    parts = version.split(".")
    patch = version if len(parts) >= 3 and parts[2] != "0" else f"{parts[0]}.{parts[1]}.6"
    system, _machine, goarch = _host()
    dest = cache / "go" / patch
    go_bin = dest / "bin" / "go"
    if not go_bin.is_file():
        url = f"https://go.dev/dl/go{patch}.{system}-{goarch}.tar.gz"
        blob = cache / "go" / f"go{patch}.tar.gz"
        blob.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, blob)
        import tarfile
        with tarfile.open(blob) as tf:
            tf.extractall(cache / "go" / f"src-{patch}")
        extracted = cache / "go" / f"src-{patch}" / "go"
        if dest.exists():
            shutil.rmtree(dest)
        os.replace(extracted, dest)
    return str(dest / "bin")


def _env_with(bun: Path | None, go_prefix: str | None) -> dict:
    env = dict(os.environ)
    prefixes = []
    if bun is not None:
        prefixes.append(str(bun.parent))
    if go_prefix:
        prefixes.append(go_prefix)
    if prefixes:
        env["PATH"] = os.pathsep.join(prefixes + [env.get("PATH", "")])
    return env


def _compile_old(root: Path, env: dict) -> Path:
    system, machine, goarch = _host()
    pkg = root / "packages" / "opencode"
    dist = pkg / "dist" / f"opencode-{system}-{machine}" / "bin"
    dist.mkdir(parents=True, exist_ok=True)
    tui_main = root / "packages" / "tui" / "cmd" / "opencode" / "main.go"
    tui_out = dist / "tui"
    if tui_main.is_file():
        _run(
            [
                "go", "build",
                "-ldflags=-s -w -X main.Version=openbench",
                "-o", str(tui_out),
                "./cmd/opencode/main.go",
            ],
            cwd=root / "packages" / "tui",
            env={**env, "CGO_ENABLED": "0", "GOOS": system, "GOARCH": goarch},
        )
    outfile = dist / "opencode"
    # Same command as publish.ts: --compile, no --minify. The wasm embed is
    # apply_tree_sitter_wasm_fix, which runs before this. Minify stays off
    # because that is the upstream command and a minified stamp is stale.
    cmd = [
        "bun", "build",
        "--define", "OPENCODE_VERSION='openbench'",
        "--compile",
        f"--target=bun-{system}-{machine}",
        f"--outfile={outfile}",
        "./src/index.ts",
    ]
    if tui_out.is_file():
        cmd.append(str(tui_out))
    _run(cmd, cwd=pkg, env=env)
    if not outfile.is_file():
        raise BuildError(f"compile did not produce {outfile}")
    return outfile


def host_libc() -> str:
    if platform.system() != "Linux":
        return "glibc"
    name = platform.libc_ver()[0]
    if "musl" in name:
        return "musl"
    if name == "glibc":
        return "glibc"
    try:
        proc = subprocess.run(
            ["ldd", sys.executable],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "glibc"
    if "musl" in (proc.stdout or "") + (proc.stderr or ""):
        return "musl"
    return "glibc"


def _dist_target(path: Path) -> dict | None:
    name = path.parent.parent.name
    prefix = "opencode-"
    if not name.startswith(prefix):
        return None
    parts = name[len(prefix):].split("-")
    if len(parts) < 2:
        return None
    os_name, arch, *flags = parts
    if any(flag not in {"baseline", "musl"} for flag in flags):
        return None
    return {
        "os": os_name,
        "arch": arch,
        "baseline": "baseline" in flags,
        "musl": "musl" in flags,
    }


def elf_interpreter(path: Path) -> str | None:
    """Return the ELF PT_INTERP string.

    ``None`` means the file is not an ELF. ``""`` means an ELF with no
    interpreter. A path is the dynamic linker ``exec`` needs.
    """
    try:
        handle = path.open("rb")
    except OSError:
        return None
    with handle:
        ident = handle.read(16)
        if len(ident) < 16 or ident[:4] != b"\x7fELF":
            return None
        elf_class = ident[4]
        data = ident[5]
        if data == 1:
            endian = "<"
        elif data == 2:
            endian = ">"
        else:
            return None
        if elf_class == 2:
            handle.seek(32)
            raw = handle.read(8)
            if len(raw) < 8:
                return None
            phoff = struct.unpack(endian + "Q", raw)[0]
            handle.seek(54)
            raw = handle.read(4)
            if len(raw) < 4:
                return None
            phentsize, phnum = struct.unpack(endian + "HH", raw)
            offset_at = 8
            filesz_at = 32
            word = "Q"
        elif elf_class == 1:
            handle.seek(28)
            raw = handle.read(4)
            if len(raw) < 4:
                return None
            phoff = struct.unpack(endian + "I", raw)[0]
            handle.seek(42)
            raw = handle.read(4)
            if len(raw) < 4:
                return None
            phentsize, phnum = struct.unpack(endian + "HH", raw)
            offset_at = 4
            filesz_at = 16
            word = "I"
        else:
            return None
        if phnum <= 0 or phentsize < filesz_at + struct.calcsize(word) or phoff <= 0:
            return ""
        for index in range(min(phnum, 128)):
            handle.seek(phoff + index * phentsize)
            entry = handle.read(phentsize)
            if len(entry) < phentsize:
                return ""
            p_type = struct.unpack_from(endian + "I", entry, 0)[0]
            if p_type != 3:
                continue
            p_offset = struct.unpack_from(endian + word, entry, offset_at)[0]
            p_filesz = struct.unpack_from(endian + word, entry, filesz_at)[0]
            if p_filesz <= 0 or p_filesz > 4096:
                return ""
            handle.seek(p_offset)
            blob = handle.read(p_filesz)
            return blob.split(b"\x00", 1)[0].decode("utf-8", "replace")
        return ""


def _shebang_can_exec(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            line = handle.readline(512)
    except OSError:
        return False
    if not line.startswith(b"#!"):
        return True
    parts = line[2:].strip().split()
    if not parts:
        return False
    program = parts[0].decode("utf-8", "replace")
    if Path(program).name == "env":
        if len(parts) < 2:
            return False
        return shutil.which(parts[1].decode("utf-8", "replace")) is not None
    return Path(program).is_file()


def can_exec(path: Path) -> bool:
    """True when this host can ``exec`` the file.

    A musl OpenCode build is mode 755 and still raises ``ENOENT`` on a glibc
    host: the kernel looks up ``/lib/ld-musl-x86_64.so.1`` and that file is
    absent. The same error is a ``#!/usr/bin/env node`` launcher when ``node``
    is not on ``PATH``.
    """
    if not path.is_file() or not os.access(path, os.X_OK):
        return False
    interpreter = elf_interpreter(path)
    if interpreter is None:
        return _shebang_can_exec(path)
    if interpreter == "":
        return True
    return Path(interpreter).is_file()


def _ensure_exec_bit(path: Path) -> None:
    mode = path.stat().st_mode
    if mode & stat.S_IXUSR:
        return
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def select_dist_binary(paths, *, system: str, machine: str, libc: str) -> Path:
    parsed = []
    for path in paths:
        info = _dist_target(Path(path))
        if info is None or info["os"] != system or info["arch"] != machine:
            continue
        parsed.append((Path(path), info))
    if libc == "musl":
        preferred = [item for item in parsed if item[1]["musl"]]
        pool = preferred or [item for item in parsed if not item[1]["musl"]]
    else:
        pool = [item for item in parsed if not item[1]["musl"]]
    runnable = [item for item in pool if can_exec(item[0])]
    plain = [item for item in runnable if not item[1]["baseline"]]
    chosen = plain or runnable
    if not chosen:
        missing = []
        for path, _info in pool:
            interpreter = elf_interpreter(path)
            if interpreter:
                missing.append(f"{path.parent.parent.name} -> {interpreter}")
        detail = f"; missing interpreter: {'; '.join(missing[:4])}" if missing else ""
        raise BuildError(f"no runnable {system}-{machine} {libc} opencode binary{detail}")
    chosen.sort(key=lambda item: str(item[0]))
    return chosen[0][0]


def _find_binary(root: Path) -> Path:
    pkg = root / "packages" / "opencode"
    found = sorted(pkg.glob("dist/**/bin/opencode"))
    candidates = []
    for path in found:
        if not path.is_file():
            continue
        try:
            _ensure_exec_bit(path)
        except OSError:
            continue
        candidates.append(path)
    if not candidates:
        wrapper = pkg / "bin" / "opencode"
        if wrapper.is_file():
            try:
                _ensure_exec_bit(wrapper)
            except OSError:
                wrapper = None
        if wrapper is not None and wrapper.is_file() and can_exec(wrapper):
            return wrapper
        raise BuildError(f"no opencode binary under {pkg / 'dist'}")
    system, machine, _goarch = _host()
    return select_dist_binary(candidates, system=system, machine=machine, libc=host_libc())


def _build_stamp(plan: dict) -> dict:
    """Identity of the recipe that produced a cached binary.

    ``binary()`` refuses a cache hit whose stamp does not match the recipe
    this process would write. A missing stamp, a compile stamp that still
    records ``minify: true``, or a compile stamp with no ``tree_sitter_wasm``
    marker is rebuilt. That drops cached binaries from before the wasm embed
    fix on the old ``bun build --compile`` trees (#2334 and #2367).
    """
    kind = plan.get("kind")
    if kind == "compile":
        mode = plan.get("tree_sitter_wasm")
        if mode not in {"file", "unchanged"}:
            mode = "unchanged"
        return {
            "flags": ["--compile"],
            "kind": "compile",
            "minify": False,
            "tree_sitter_wasm": mode,
        }
    return {"args": list(plan.get("args") or []), "kind": kind}


def _read_build_stamp(published: Path) -> dict | None:
    path = published.parent / "build-stamp.json"
    if not path.is_file():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _stamp_current(stamp: dict | None) -> bool:
    if not isinstance(stamp, dict):
        return False
    kind = stamp.get("kind")
    if kind == "compile":
        return (
            stamp.get("minify") is False
            and stamp.get("tree_sitter_wasm") in {"file", "unchanged"}
        )
    return kind in {"build.ts", "bun-run"}


def _write_build_stamp(published: Path, plan: dict) -> None:
    path = published.parent / "build-stamp.json"
    path.write_text(json.dumps(_build_stamp(plan), sort_keys=True), encoding="utf-8")


def _execute_plan(root: Path, plan: dict, cache: Path) -> Path:
    bun_path = ensure_bun(plan["bun"], cache) if plan.get("bun") else None
    go_prefix = ensure_go(plan["go"], cache) if plan.get("go") else None
    env = _env_with(bun_path, go_prefix)
    _run(["bun", "install"], cwd=root, env=env)
    if plan["kind"] == "compile":
        plan["tree_sitter_wasm"] = apply_tree_sitter_wasm_fix(root)
        return _compile_old(root, env)
    if plan["kind"] == "bun-run":
        # No compile script. A wrapper keeps ``binary()`` a single executable path.
        pkg = root / "packages" / "opencode"
        wrapper = cache / "wrappers" / "opencode"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        bun = str(bun_path or "bun")
        wrapper.write_text(
            "#!/bin/sh\n"
            f"exec {bun} run {pkg / 'src' / 'index.ts'} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        return wrapper
    _run(plan["args"], cwd=root / plan["cwd"], env=env)
    return _find_binary(root)


def _ensure_mirror(cache: Path) -> Path:
    mirror = cache / "mirror"
    if (mirror / ".git").exists() or (mirror / "HEAD").exists():
        _run(["git", "-C", str(mirror), "fetch", "--all", "--tags", "--prune"], cwd=cache)
        return mirror
    cache.mkdir(parents=True, exist_ok=True)
    try:
        _run(["git", "clone", "--filter=blob:none", UPSTREAM, str(mirror)], cwd=cache)
    except BuildError:
        if mirror.exists():
            shutil.rmtree(mirror)
        _run(["git", "clone", "--filter=blob:none", FALLBACK_UPSTREAM, str(mirror)], cwd=cache)
    return mirror


def _ensure_worktree(mirror: Path, sha: str, dest: Path) -> None:
    if (dest / ".git").exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(
        ["git", "-C", str(mirror), "worktree", "add", "--detach", str(dest), sha],
        cwd=mirror.parent,
    )


def binary(sha: str, cache: Path) -> Path:
    """Return a runnable ``opencode`` for ``sha``, building it on a cache miss."""
    sha = sha.strip().lower()
    if len(sha) != 40:
        raise BuildError(f"expected a 40-character SHA, got {sha!r}")
    # Git resolves a relative dest against ``cwd``. Callers pass ``results/...``.
    cache = Path(cache).resolve()
    published = cache / "bin" / sha / "opencode"
    if can_exec(published) and _stamp_current(_read_build_stamp(published)):
        return published
    with exclusive_lock(cache / "locks" / f"{sha}.lock"):
        if can_exec(published) and _stamp_current(_read_build_stamp(published)):
            return published
        with exclusive_lock(cache / "mirror.lock"):
            mirror = _ensure_mirror(cache)
            worktree = cache / "worktrees" / sha
            _ensure_worktree(mirror, sha, worktree)
        plan = build_plan(worktree)
        built = _execute_plan(worktree, plan, cache)
        try:
            _ensure_exec_bit(built)
        except OSError as exc:
            raise BuildError(f"cannot mark {built} executable: {exc}") from exc
        if not can_exec(built):
            interpreter = elf_interpreter(built)
            detail = f" (interpreter {interpreter})" if interpreter else ""
            raise BuildError(f"built opencode cannot exec on this host: {built}{detail}")
        published.parent.mkdir(parents=True, exist_ok=True)
        tmp = published.with_name("opencode.tmp")
        shutil.copy2(built, tmp)
        tmp.chmod(0o755)
        os.replace(tmp, published)
        _write_build_stamp(published, plan)
    return published


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build one OpenCode SHA")
    parser.add_argument("sha")
    parser.add_argument("--cache", type=Path, default=Path("results/opencode-src"))
    args = parser.parse_args(argv)
    try:
        print(binary(args.sha, args.cache))
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
