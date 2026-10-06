#!/usr/bin/env python3
"""Generate the RSA private key SZLG+ uses to sign OIDC ID tokens.

Run it from the project root, before the first start:

    python scripts/generate_oidc_key.py

The target path is OIDC_RSA_PRIVATE_KEY_FILE (from the environment or .env),
defaulting to .secrets/oidc-private.pem. An existing key is never overwritten
unless --force is given: replacing it invalidates every ID token signed so far
and changes the public key published at the JWKS endpoint.

This script deliberately does not import the Django settings, because the
settings refuse to load while the key is missing.
"""

import argparse
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_KEY_PATH = ".secrets/oidc-private.pem"


def configured_key_path() -> Path:
    try:
        from dotenv import load_dotenv

        load_dotenv(BASE_DIR / ".env")
    except ImportError:
        pass
    path = Path(os.environ.get("OIDC_RSA_PRIVATE_KEY_FILE", DEFAULT_KEY_PATH))
    return path if path.is_absolute() else BASE_DIR / path


def write_private_key(path: Path, bits: int, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if force else os.O_EXCL)
    # 0o600: readable by the owner only (ignored on Windows).
    descriptor = os.open(path, flags | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(pem)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the SZLG+ OIDC signing key.")
    parser.add_argument("--path", type=Path, help="where to write the key")
    parser.add_argument("--bits", type=int, default=3072, help="RSA key size (default: 3072)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing key")
    args = parser.parse_args()

    if args.bits < 2048:
        parser.error("--bits must be at least 2048")

    path = args.path or configured_key_path()
    if path.exists() and not args.force:
        print(f"A kulcs már létezik, nem írom felül: {path}")
        print("Csere csak szándékosan: --force (a korábban kiadott ID tokenek érvénytelenné válnak).")
        return 0

    try:
        write_private_key(path, args.bits, args.force)
    except OSError as error:
        print(f"Nem sikerült megírni a kulcsot ({path}): {error}", file=sys.stderr)
        return 1

    print(f"RSA-{args.bits} privát kulcs létrehozva: {path}")
    print("Ezt a fájlt soha ne commitold és ne oszd meg; a publikus kulcsot a JWKS végpont adja ki.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
