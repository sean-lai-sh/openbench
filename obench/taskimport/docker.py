"""Thin ``docker`` CLI wrapper used by the import pipeline. Every call goes
through ``Docker._run`` so tests can substitute a fake (``FakeDocker`` in the
tests) and no Docker daemon is needed to test the pipeline."""

from __future__ import annotations

import json
import subprocess


class DockerError(RuntimeError):
    pass


class Docker:
    def __init__(self, platform: str = "linux/amd64", binary: str = "docker"):
        self.platform, self.binary = platform, binary

    def _run(self, args: list[str], *, timeout: int = 3600, check: bool = True) -> tuple[int, str]:
        proc = subprocess.run([self.binary, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL)
        if check and proc.returncode != 0:
            raise DockerError(f"docker {' '.join(args[:3])} ... exited {proc.returncode}: {proc.stdout[-800:]}")
        return proc.returncode, proc.stdout

    def pull(self, ref: str) -> None:
        self._run(["pull", "--platform", self.platform, ref])

    def inspect(self, ref: str) -> dict:
        _, out = self._run(["image", "inspect", ref])
        return json.loads(out)[0]

    def pinned_ref(self, ref: str) -> str:
        """``name@sha256:...`` for a pulled image (its repo digest)."""
        digests = self.inspect(ref).get("RepoDigests") or []
        if not digests:
            raise DockerError(f"{ref} has no repo digest (not pulled from a registry)")
        return digests[0]

    def image_id(self, ref: str) -> str:
        return self.inspect(ref)["Id"]

    def workdir(self, ref: str) -> str:
        return (self.inspect(ref).get("Config") or {}).get("WorkingDir") or "/"

    def build(self, context: str, tag: str, *, dockerfile: str | None = None, timeout: int = 3600) -> None:
        args = ["build", "--platform", self.platform, "-t", tag]
        if dockerfile:
            args += ["-f", dockerfile]
        self._run(args + [context], timeout=timeout)

    def copy_out(self, image: str, src: str, dest: str) -> None:
        """Copy ``src`` (a directory, contents only) out of ``image`` into ``dest``."""
        _, cid = self._run(["create", "--platform", self.platform, image])
        cid = cid.strip()
        try:
            self._run(["cp", f"{cid}:{src.rstrip('/')}/.", dest])
        finally:
            self._run(["rm", "-f", cid], check=False)

    def run(self, image: str, command: list[str], *, mounts: list[tuple[str, str, bool]] = (), workdir: str | None = None,
            network: str | None = None, timeout: int = 3600) -> tuple[int, str]:
        args = ["run", "--rm", "--platform", self.platform]
        if network:
            args += ["--network", network]
        for host, container, readonly in mounts:
            args += ["-v", f"{host}:{container}{':ro' if readonly else ''}"]
        if workdir:
            args += ["-w", workdir]
        return self._run(args + [image, *command], timeout=timeout, check=False)
