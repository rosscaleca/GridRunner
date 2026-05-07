# Security Policy

## Reporting a Vulnerability

If you believe you've found a security vulnerability in GridRunner, please **do not** open a public issue. Instead, report it privately via GitHub:

1. Go to https://github.com/rosscaleca/GridRunner/security/advisories/new
2. Fill out the advisory form with as much detail as you can (steps to reproduce, affected versions, potential impact).

I'll acknowledge your report within a few days and keep you informed as a fix lands.

## Supported Versions

Only the latest tagged release on the [Releases page](https://github.com/rosscaleca/GridRunner/releases) is actively supported.

## Scope

GridRunner is a single-user desktop application that binds to `127.0.0.1` and is intended for local use only. Reports should focus on:

- Code-execution paths reachable without local access (network-exposed flaws)
- Privilege escalation on the host
- Secret/credential leakage between the app and external services (SMTP, webhooks)
- Supply-chain or build-artifact integrity issues

The `AUTH_ENABLED=false` default is intentional for a single-user local app and is not in itself a vulnerability.
