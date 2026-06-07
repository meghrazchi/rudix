from __future__ import annotations

from dataclasses import dataclass

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHash, VerificationError


@dataclass(frozen=True)
class PasswordHashConfig:
    memory_cost: int
    time_cost: int
    parallelism: int
    hash_length: int
    salt_length: int


def build_password_hasher(config: PasswordHashConfig) -> PasswordHasher:
    return PasswordHasher(
        time_cost=config.time_cost,
        memory_cost=config.memory_cost,
        parallelism=config.parallelism,
        hash_len=config.hash_length,
        salt_len=config.salt_length,
        type=Type.ID,
    )


def hash_password(password: str, hasher: PasswordHasher) -> str:
    return hasher.hash(password)


def verify_password(password: str, hashed_password: str, hasher: PasswordHasher) -> bool:
    try:
        return hasher.verify(hashed_password, password)
    except (InvalidHash, VerificationError):
        return False
