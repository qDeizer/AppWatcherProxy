from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from mitmproxy.certs import CertStore

StoreScope = Literal["user", "machine"]


@dataclass(frozen=True, slots=True)
class CertificateStatus:
    path: Path
    exists: bool
    subject: str | None
    thumbprint: str | None
    not_before: datetime | None
    not_after: datetime | None
    trusted_user: bool
    trusted_machine: bool

    @property
    def trusted(self) -> bool:
        return self.trusted_user or self.trusted_machine


class CertificateManager:
    def __init__(self, confdir: Path | None = None) -> None:
        self.confdir = confdir or Path.home() / ".mitmproxy"
        self.cert_path = self.confdir / "mitmproxy-ca-cert.cer"
        self.combined_ca_path = self.confdir / "mitmproxy-ca.pem"

    def ensure_ca(self) -> CertificateStatus:
        store = CertStore.from_store(self.confdir, "mitmproxy", 2048)
        if not self.cert_path.exists():
            self.cert_path.write_bytes(store.default_ca.to_pem())
        return self.status()

    def status(self) -> CertificateStatus:
        if not self.cert_path.exists():
            return CertificateStatus(
                path=self.cert_path,
                exists=False,
                subject=None,
                thumbprint=None,
                not_before=None,
                not_after=None,
                trusted_user=False,
                trusted_machine=False,
            )

        certificate = x509.load_pem_x509_certificate(self.cert_path.read_bytes())
        der = certificate.public_bytes(serialization.Encoding.DER)
        thumbprint = hashlib.sha1(der, usedforsecurity=False).hexdigest().upper()
        return CertificateStatus(
            path=self.cert_path,
            exists=True,
            subject=certificate.subject.rfc4514_string(),
            thumbprint=thumbprint,
            not_before=certificate.not_valid_before_utc,
            not_after=certificate.not_valid_after_utc,
            trusted_user=self._is_trusted(thumbprint, "user"),
            trusted_machine=self._is_trusted(thumbprint, "machine"),
        )

    def install(self, scope: StoreScope = "machine") -> CertificateStatus:
        if os.name != "nt":
            raise RuntimeError("Windows certificate store is only available on Windows")
        self.ensure_ca()
        command = ["certutil"]
        if scope == "user":
            command.append("-user")
        command.extend(["-addstore", "-f", "Root", str(self.cert_path)])
        result = subprocess.run(command, capture_output=True, check=False)
        if result.returncode != 0:
            output = (result.stdout + result.stderr).decode(errors="replace").strip()
            raise RuntimeError(f"Certificate installation failed: {output}")
        installed = self.status()
        trusted = installed.trusted_machine if scope == "machine" else installed.trusted_user
        if not trusted:
            raise RuntimeError("Certificate command completed, but trust verification failed")
        return installed

    def remove(self, scope: StoreScope = "machine") -> None:
        status = self.status()
        if not status.thumbprint or os.name != "nt":
            return
        command = ["certutil"]
        if scope == "user":
            command.append("-user")
        command.extend(["-delstore", "Root", status.thumbprint])
        result = subprocess.run(command, capture_output=True, check=False)
        if result.returncode != 0:
            output = (result.stdout + result.stderr).decode(errors="replace").strip()
            raise RuntimeError(f"Certificate removal failed: {output}")

    @staticmethod
    def _is_trusted(thumbprint: str, scope: StoreScope) -> bool:
        if os.name != "nt":
            return False
        command = ["certutil"]
        if scope == "user":
            command.append("-user")
        command.extend(["-store", "Root", thumbprint])
        result = subprocess.run(command, capture_output=True, check=False)
        return result.returncode == 0
