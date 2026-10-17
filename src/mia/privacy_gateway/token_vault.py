"""Token Vault: correspondencia cifrada y temporal entre un pseudo-token (p. ej. ``PERSON_001``) y el
valor real que representa.

Solo vive en memoria del proceso (nunca en disco ni BD): es exactamente lo que ya se decidió para la
caché de importes de nóminas de esta misma sesión — ningún dato sensible se persiste más tiempo del
estrictamente necesario para completar la operación en curso, y se pierde al reiniciar el servicio.
El valor en memoria va cifrado (Fernet, cifrado autenticado) para que un volcado de memoria o un log
accidental de la estructura interna no exponga el texto claro.
"""

from __future__ import annotations

import base64
import hashlib
import threading
import time
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

from mia.privacy_gateway.exceptions import RestorationDeniedError


def _derive_fernet_key(raw: str) -> bytes:
    """Cualquier cadena de configuración -> clave Fernet válida (32 bytes url-safe base64)."""
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@dataclass(frozen=True, slots=True)
class _Entry:
    ciphertext: bytes
    expires_at: float
    user_id: str
    operation_id: str


class TokenVault:
    """Aislada por (user_id, operation_id): un token solo se restaura para el mismo usuario y la misma
    operación/turno que lo generó. Un token de otra sesión, usuario u operación nunca se restaura."""

    def __init__(self, key: str, ttl_seconds: int) -> None:
        fernet_key = key.encode("utf-8") if key and len(key) == 44 else _derive_fernet_key(key or "mia-dev-only")
        self._fernet = Fernet(fernet_key)
        self._ttl = ttl_seconds
        self._entries: dict[tuple[str, str, str], _Entry] = {}
        self._lock = threading.Lock()

    def store(self, token: str, value: str, *, user_id: str, operation_id: str) -> None:
        ciphertext = self._fernet.encrypt(value.encode("utf-8"))
        entry = _Entry(ciphertext, time.monotonic() + self._ttl, user_id, operation_id)
        with self._lock:
            self._entries[(user_id, operation_id, token)] = entry

    def resolve(self, token: str, *, user_id: str, operation_id: str) -> str | None:
        """Devuelve el valor original, o None si el token no existe/caducó/no pertenece a este contexto.
        Nunca lanza para un token simplemente ausente: eso es el caso normal de texto que no es un token."""
        with self._lock:
            entry = self._entries.get((user_id, operation_id, token))
        if entry is None:
            return None
        if entry.expires_at < time.monotonic() or entry.user_id != user_id or entry.operation_id != operation_id:
            return None
        try:
            return self._fernet.decrypt(entry.ciphertext).decode("utf-8")
        except InvalidToken as exc:  # pragma: no cover — ciphertext corrupto o clave rotada
            raise RestorationDeniedError("Token Vault: no se pudo descifrar la entrada") from exc

    def purge_operation(self, operation_id: str) -> None:
        """Borra todas las entradas de una operación al terminar el turno: limpieza inmediata, no solo TTL."""
        with self._lock:
            stale = [key for key, e in self._entries.items() if e.operation_id == operation_id]
            for key in stale:
                del self._entries[key]

    def purge_expired(self) -> None:
        now = time.monotonic()
        with self._lock:
            stale = [key for key, e in self._entries.items() if e.expires_at < now]
            for key in stale:
                del self._entries[key]

    def __len__(self) -> int:
        return len(self._entries)
