from __future__ import annotations

import sys

from backend.cert.manager import CertificateManager
from backend.net.recovery import is_admin


def _confirmed() -> bool:
    print()
    print("DIKKAT: Network Inspector HTTPS trafigini inceleyebilmek icin")
    print("kendi yerel CA sertifikasini Windows Trusted Root deposuna kuracak.")
    print("Ozel anahtar yalnizca bu bilgisayardaki .mitmproxy klasorunde kalir.")
    answer = input("Bu sertifikayi Yerel Makine deposuna kurmak istiyor musunuz? [E/h]: ")
    return answer.strip().casefold() in {"", "e", "evet", "y", "yes"}


def main() -> int:
    manager = CertificateManager()
    try:
        status = manager.ensure_ca()
    except Exception as exc:  # noqa: BLE001 - CLI boundary must render setup failures.
        print(f"HATA: CA sertifikasi olusturulamadi: {exc}", file=sys.stderr)
        return 1

    print(f"CA dosyasi: {status.path}")
    print(f"Parmak izi: {status.thumbprint}")

    if status.trusted_machine:
        print("CA sertifikasi Yerel Makine guven deposunda kurulu ve dogrulandi.")
        return 0

    if status.trusted_user:
        print("Not: Ayni CA yalnizca mevcut kullanici deposunda kurulu.")
        print("Sistem servislerini de kapsamak icin Yerel Makine deposuna kurulacak.")

    if not _confirmed():
        print("Sertifika kurulumu kullanici tarafindan iptal edildi.")
        return 2
    if not is_admin():
        print("HATA: Sertifika kurulumu icin yonetici yetkisi gerekiyor.", file=sys.stderr)
        return 3

    try:
        installed = manager.install("machine")
    except Exception as exc:  # noqa: BLE001 - certutil errors must reach the console.
        print(f"HATA: {exc}", file=sys.stderr)
        return 4

    print("CA sertifikasi basariyla kuruldu ve dogrulandi.")
    print(f"Gecerlilik sonu: {installed.not_after:%Y-%m-%d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
