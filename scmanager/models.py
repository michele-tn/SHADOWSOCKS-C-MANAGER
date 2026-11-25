"""Conservative, source-reviewed server configuration contract."""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

CIPHERS = ("aes-128-gcm", "aes-192-gcm", "aes-256-gcm", "chacha20-ietf-poly1305")


class ConfigurationError(ValueError):
    """A redacted configuration validation failure."""


class ServerConfig(BaseModel):
    """Supported settings; unknown options always block deployment."""

    model_config = ConfigDict(extra="forbid", strict=True)
    server: str
    server_port: int = Field(ge=1024, le=65535)
    password: SecretStr
    method: Literal["aes-128-gcm", "aes-192-gcm", "aes-256-gcm", "chacha20-ietf-poly1305"]
    mode: Literal["tcp_only", "tcp_and_udp", "udp_only"] = "tcp_only"
    timeout: int = Field(default=60, ge=1, le=2147483647)

    @field_validator("server")
    @classmethod
    def literal_address(cls, value: str) -> str:
        """Reject hostnames and multi-address configurations."""
        if "%" in value:
            raise ValueError("Scoped addresses are unsupported")
        ipaddress.ip_address(value)
        return value

    @field_validator("password")
    @classmethod
    def nonempty_password(cls, value: SecretStr) -> SecretStr:
        """Accept existing credentials without silently strengthening them."""
        if not value.get_secret_value() or "\x00" in value.get_secret_value():
            raise ValueError("Password must be nonempty and contain no NUL")
        return value

    def target_bytes(self) -> bytes:
        """Serialize a separate destination, never the source file."""
        data = self.model_dump(exclude={"password"})
        data["password"] = self.password.get_secret_value()
        return (json.dumps(data, indent=2) + "\n").encode()


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys whose interpretation could be ambiguous."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError("Duplicate JSON key; input was not changed")
        result[key] = value
    return result


def parse_config(raw: bytes) -> ServerConfig:
    """Validate without putting input values into error messages."""
    if len(raw) > 1024 * 1024:
        raise ConfigurationError("Configuration exceeds 1 MiB")
    try:
        data = json.loads(raw, object_pairs_hook=unique_object)
        return ServerConfig.model_validate(data)
    except ValidationError as error:
        fields = sorted({str(item["loc"][0]) if item["loc"] else "document"
                         for item in error.errors(include_input=False)})
        known = set(ServerConfig.model_fields)
        labels = [field if field in known else "unsupported option" for field in fields]
        raise ConfigurationError("Incompatible configuration fields: " + ", ".join(labels)) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ConfigurationError("Invalid JSON; input was not changed") from None


def load_config(path: Path) -> ServerConfig:
    """Read a regular nonsymlink configuration."""
    from scmanager.paths import safe_path
    safe_path(path, must_exist=True)
    return parse_config(path.read_bytes())
