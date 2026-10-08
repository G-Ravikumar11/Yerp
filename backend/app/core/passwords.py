"""How passwords are stored and checked: salted PBKDF2, and the older forms still readable."""
import hashlib
import hmac
import os


# How many rounds a new password hash takes. Tests lower it so the suite is not spent hashing.
PASSWORD_ITERATIONS = int(os.getenv("PASSWORD_ITERATIONS", "600000"))

_HASH_PREFIX = "pbkdf2_sha256$"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return "%s%d$%s$%s" % (_HASH_PREFIX, PASSWORD_ITERATIONS, salt.hex(), digest.hex())


def verify_password(password: str, stored: str) -> bool:
    """Whether a password matches what is stored. Reads today's form, the 100,000-round form earlier releases
    wrote ("salt:hash"), and the bare sha256 older still; an empty or unreadable value is simply a no."""
    if not stored or not password:
        return False
    try:
        if stored.startswith(_HASH_PREFIX):
            _, rounds, salt_hex, want = stored.split("$")
            got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)).hex()
        elif ":" in stored:
            salt_hex, want = stored.split(":", 1)
            got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 100000).hex()
        else:
            got, want = hashlib.sha256(password.encode()).hexdigest(), stored
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


def needs_rehash(stored: str) -> bool:
    """Whether a stored password is in an older or weaker form than a new one would be."""
    if not stored:
        return False
    if not stored.startswith(_HASH_PREFIX):
        return True
    try:
        return int(stored.split("$")[1]) < PASSWORD_ITERATIONS
    except (IndexError, ValueError):
        return True
