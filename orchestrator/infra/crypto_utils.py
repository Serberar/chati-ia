from cryptography.fernet import Fernet, InvalidToken


def encrypt_text(dek: bytes, plaintext: str) -> bytes:
    return Fernet(dek).encrypt(plaintext.encode("utf-8"))


def decrypt_text(dek: bytes, ciphertext: bytes) -> str | None:
    try:
        return Fernet(dek).decrypt(ciphertext).decode("utf-8")
    except InvalidToken:
        return None


def encrypt_bytes(dek: bytes, data: bytes) -> bytes:
    return Fernet(dek).encrypt(data)


def decrypt_bytes(dek: bytes, ciphertext: bytes) -> bytes | None:
    try:
        return Fernet(dek).decrypt(ciphertext)
    except InvalidToken:
        return None
