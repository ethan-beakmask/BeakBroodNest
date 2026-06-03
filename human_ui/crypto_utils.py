import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def generate_key() -> bytes:
    return os.urandom(32)


def aes_gcm_decrypt(key: bytes, enc_b64: str) -> bytes:
    raw = base64.b64decode(enc_b64)
    iv, ciphertext_with_tag = raw[:12], raw[12:]
    return AESGCM(key).decrypt(iv, ciphertext_with_tag, None)
