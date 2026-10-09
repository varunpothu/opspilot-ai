# Security policy

## Current scope

OpsPilot AI is an early local MVP. It analyzes configured JSON fixtures, persists run results to a local SQLite database and exposes a FastAPI service intended for localhost development.

It does not currently provide authentication, multi-tenant isolation, production connectors, or production remediation. Do not expose the API to an untrusted network.

## Safe-use rules

- Keep the API bound to `127.0.0.1` for local development.
- Do not place secrets or personal/customer data in fixtures.
- Do not treat hypotheses as confirmed root causes without reviewing evidence.
- Remediation plans are advisory only; the current MVP does not execute them.
- Do not connect this MVP to production systems or grant it production credentials.
- Keep local databases and generated reports out of version control if they may contain sensitive data.

## Reporting a vulnerability

Please do not publish sensitive vulnerability details in a public issue. Contact the repository owner privately through GitHub to coordinate triage and a fix. Include the affected commit, reproduction steps, impact and any suggested mitigation.

## Before production use

A production deployment would require authentication and authorization, secret management, audit identity, rate and resource limits, dependency/security scanning, tenant isolation where relevant, integration-specific least privilege, a threat model, monitoring, backup/restore testing and independent security review.
