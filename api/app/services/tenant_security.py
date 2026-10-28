import base64
import hashlib
import hmac
import ipaddress
import re
import secrets

from pydantic import BaseModel, ConfigDict, Field, field_validator

PASSWORD_ITERATIONS = 600_000
RESERVED_SLUGS = {"app", "api", "www", "admin", "login", "register", "portal", "support", "assets", "static", "auth"}


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(32)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def password_matches(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(iterations) <= 2_000_000:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt, validate=True), int(iterations))
        return hmac.compare_digest(digest, base64.b64decode(expected, validate=True))
    except (ValueError, TypeError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_domain(value: str) -> str:
    domain = value.strip().rstrip(".").lower()
    if ":" in domain or "/" in domain or "@" in domain or "*" in domain:
        raise ValueError("Enter a hostname only, without scheme, path, wildcard or port")
    try:
        domain = domain.encode("idna").decode("ascii")
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ValueError("Custom domains must be DNS hostnames, not IP addresses")
    if len(domain) > 253 or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain):
        raise ValueError("Enter a valid public DNS hostname")
    if domain.endswith((".localhost", ".local", ".internal", ".invalid", ".test", ".example")):
        raise ValueError("Use a public domain you own")
    return domain


class Registration(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False, extra="forbid")
    company_name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{1,46}[a-z0-9])$", max_length=48)
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("company_name", "display_name")
    @classmethod
    def clean_name(cls, value: str):
        if not value.strip():
            raise ValueError("Name is required")
        return value.strip()

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("slug")
    @classmethod
    def valid_slug(cls, value: str):
        if value in RESERVED_SLUGS:
            raise ValueError("This workspace address is reserved")
        return value


class Login(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)


class MemberCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=150)
    email: str = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)
    role: str = Field(pattern=r"^(admin|staff|viewer)$")
    _email = field_validator("email")(Registration.clean_email.__func__)
    _name = field_validator("display_name")(Registration.clean_name.__func__)