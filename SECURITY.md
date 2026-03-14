# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.x     | ✅ Yes     |

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report privately by emailing the repository owner via the contact on the [GitHub profile](https://github.com/JacobJandon), or use [GitHub private vulnerability reporting](https://github.com/JacobJandon/Sicry/security/advisories/new).

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You will receive a response within 72 hours. Please allow time to patch before public disclosure.

## Scope

SICRY™ routes traffic through Tor. Security issues in scope include:
- Traffic leaking outside Tor
- Authentication bypass in `renew_identity()`
- Unsafe handling of untrusted `.onion` content
- Dependency vulnerabilities in `requests`, `stem`, `beautifulsoup4`
