import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ..types import Capability
from .base import Adapter


class SSHAdapter(Adapter):
    kind = "ssh"
    capabilities = frozenset({Capability.SHELL})

    async def available(self) -> tuple[bool, str | None]:
        return (True, None) if shutil.which("ssh") else (False, "OpenSSH client not found")

    def _argv(self) -> tuple[list[str], dict[str, str], tempfile.TemporaryDirectory[str] | None]:
        host = self.config["host"]
        user = self.config.get("user")
        destination = f"{user}@{host}" if user else host
        args = ["ssh", "-T", "-p", str(self.config.get("port", 22))]
        args += ["-o", f"ConnectTimeout={int(self.config.get('timeout', 10))}"]
        checking = self.config.get("host_key_checking", "accept-new")
        if checking == "none":
            args += ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"]
        else:
            args += ["-o", f"StrictHostKeyChecking={checking}"]
        if identity := self.config.get("identity_file"):
            args += ["-i", str(Path(identity).expanduser())]
        environment = os.environ.copy()
        temporary = None
        if password := self.config.get("password"):
            temporary = tempfile.TemporaryDirectory(prefix="dockernaut-askpass-")
            helper = Path(temporary.name) / "askpass"
            helper.write_text("#!/bin/sh\nprintf '%s\\n' \"$DOCKERNAUT_SSH_PASSWORD\"\n")
            helper.chmod(0o700)
            environment.update({
                "DISPLAY": environment.get("DISPLAY", ":0"),
                "DOCKERNAUT_SSH_PASSWORD": str(password),
                "SSH_ASKPASS": str(helper),
                "SSH_ASKPASS_REQUIRE": "force",
            })
        args.append(destination)
        return args, environment, temporary

    async def shell(self, command: str, stdin: bytes | None = None) -> tuple[int, bytes, bytes]:
        args, environment, temporary = self._argv()
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
            )
            stdout, stderr = await process.communicate(stdin)
            return process.returncode, stdout, stderr
        finally:
            if temporary:
                temporary.cleanup()


def create(name: str, config: dict[str, Any], adapters: dict[str, Adapter]) -> Adapter:
    return SSHAdapter(name, config)
