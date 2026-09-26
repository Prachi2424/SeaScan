from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def canonical_manifest(manifest: dict[str, object]) -> bytes:
    return json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def public_key_id(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()


def generate_private_key(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    path.write_bytes(private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    path.chmod(0o600)
    return public_key_id(private_key.public_key())


def load_private_key(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("SeaScan signing key must be an Ed25519 private key.")
    return key


def sign_manifest(manifest: dict[str, object], private_key: Ed25519PrivateKey) -> tuple[bytes, bytes]:
    payload = canonical_manifest(manifest)
    signature = private_key.sign(payload)
    public_pem = private_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return signature, public_pem


def signing_certificate(private_key: Ed25519PrivateKey, identity: str) -> bytes:
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, identity)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(private_key, algorithm=None)
    )
    return certificate.public_bytes(serialization.Encoding.PEM)


def verify_package(package: bytes, trusted_key_ids: set[str] | None = None) -> dict[str, object]:
    errors: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            signature = base64.b64decode(archive.read("manifest.sig"), validate=True)
            certificate = x509.load_pem_x509_certificate(archive.read("signing_certificate.pem"))
            public_key = certificate.public_key()
            if not isinstance(public_key, Ed25519PublicKey):
                raise ValueError("Public key is not Ed25519.")
            key_id = public_key_id(public_key)
            if manifest.get("signing_key_id") != key_id:
                errors.append("Manifest signing key identifier does not match the included public key.")
            try:
                public_key.verify(signature, canonical_manifest(manifest))
            except InvalidSignature:
                errors.append("Manifest signature is invalid.")
            report_name = str(manifest.get("report_filename", ""))
            report = archive.read(report_name)
            if hashlib.sha256(report).hexdigest() != manifest.get("report_sha256"):
                errors.append("PDF SHA-256 integrity check failed.")
            trusted = trusted_key_ids is not None and key_id in trusted_key_ids
            if trusted_key_ids is not None and not trusted:
                errors.append("Signing key is not in the configured trust store.")
    except (KeyError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        errors.append(f"Invalid evidence package: {error}")
        key_id = None
        trusted = False
        manifest = None
    return {"valid": not errors, "trusted": trusted, "signing_key_id": key_id, "errors": errors, "manifest": manifest}
