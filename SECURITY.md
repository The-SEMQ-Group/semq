# Security Policy

This policy tells you how to report a vulnerability in the SEMQ SDK, and
what we do in return.

## Reporting a vulnerability

Send a detailed report to **security@thesemqgroup.ai**.

Please include:

- What the issue is, and the impact it can have.
- Steps to reproduce it, with a minimal proof of concept if you have one.
- The SDK versions and language bindings that the issue affects.
- Your name and contact details, if you want the credit.

To encrypt your report, ask for our PGP key in your first message. We
reply with the public key before you send any technical detail.

**Please do not** open a public issue, a pull request, or a discussion
post about a suspected vulnerability. Every customer stays at risk until
the fix ships.

## Supported versions

| Version | Security fixes |
| --- | --- |
| Latest minor release of 1.x | Yes |
| Earlier 1.x releases | No; upgrade to the latest 1.x minor release |
| Release candidates | No |

Supported platforms and language versions are listed in
[Compatibility and migration](docs/compatibility.md#supported-platforms).

## What to expect

| Step                      | Target time                |
|---------------------------|----------------------------|
| We acknowledge the report | Within 2 business days     |
| We finish a first review  | Within 5 business days     |
| We send a status update   | At least every 14 days     |
| We disclose, with you     | Within 90 days of report   |

The 90-day window covers issues that we confirm as vulnerabilities. Some
issues need a coordinated change upstream, and those can take longer. In
that case we write to the reporter with the new date.

## Scope

In scope:

- The native C library (`libsemq`) and every published binding.
- The build pipeline that produces the release artifacts.
- The documented installation and packaging tools.

Out of scope:

- A vulnerability in a third-party dependency that we do not ship. Report
  those upstream.
- An issue that needs physical access to a customer machine.
- Self-XSS, and social engineering against a person.

## Safe harbor

We bring no civil or criminal action against a researcher who:

- Makes a good-faith effort to follow this policy.
- Protects privacy, and avoids both service disruption and data loss.
- Gives The SEMQ Group Inc. reasonable time to fix the issue before any public
  disclosure.

## Hall of fame

A researcher who discloses a vulnerability to us gets public credit, with
their consent, in the release notes of the version that carries the fix.
