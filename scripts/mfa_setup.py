"""Create the TOTP secret for dashboard and API MFA (NFR-009, FR-052).

Usage: uv run python scripts/mfa_setup.py

Prints a new secret and the ``otpauth://`` link. Add it to your authenticator app, then put the
secret in MFA_TOTP_SECRET (local .env and the aqta/prod secret) and set MFA_REQUIRED=true.
Nothing is written to disk.
"""

from __future__ import annotations

import sys

from aqta.core.totp import generate_secret, provisioning_uri


def main() -> int:
    secret = generate_secret()
    print("1. In your authenticator app choose 'Enter a setup key' and type this key:")  # noqa: T201
    print(f"     {secret}")  # noqa: T201
    print("   (time-based, 6 digits). Or turn this link into a QR code locally and scan it:")  # noqa: T201
    print(f"     {provisioning_uri(secret)}")  # noqa: T201
    print("2. Add to .env and to the aqta/prod secret in AWS Secrets Manager:")  # noqa: T201
    print(f"     MFA_TOTP_SECRET={secret}")  # noqa: T201
    print("     MFA_REQUIRED=true")  # noqa: T201
    print("3. Clear this terminal. Keep the key only in the app and the secret stores.")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
