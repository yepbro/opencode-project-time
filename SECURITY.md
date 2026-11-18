# Security Policy

## Supported Versions

`opencode-project-time` is under active development. Security fixes are applied
to the `main` branch. There are no published releases yet.

| Version             | Supported          |
| ------------------- | ------------------ |
| `main`              | :white_check_mark: |
| older commits/tags  | :x:                |

## Reporting a Vulnerability

We take the security of this plugin seriously. If you believe you have found a
vulnerability, please report it privately. **Do not report security
vulnerabilities through public GitHub issues, discussions, or pull requests.**

Please report vulnerabilities by email to [denis@yepbro.pro](mailto:denis@yepbro.pro).

To help us understand the nature and scope of the issue, include as much of the
following as you can:

- The type of issue (e.g., path traversal, unsafe argument handling, command
  injection, unintended database writes, disclosure of local session data)
- Step-by-step instructions to reproduce the issue
- Affected commit(s), operating system, Node.js/Python versions, and OpenCode
  version (`opencode --version`)
- The impact, including how local files or OpenCode data could be read or
  modified
- Proof-of-concept code, configurations, or report files, if available

Vulnerabilities that break the plugin's read-only guarantee are especially
important: `scripts/collect.py` must open OpenCode's SQLite database with
`mode=ro` and `PRAGMA query_only = ON`, and the only files written are the JSON
snapshot and Markdown report passed with `--out`.

## Response Timeline

- You will receive an acknowledgment of your report within 48 hours.
- We will investigate the report and keep you informed of our progress.
- Once the issue is confirmed, we will work on a fix and coordinate a release.
- We will credit you in the release notes, unless you prefer to remain anonymous.

## Disclosure Policy

We ask that you give us a reasonable amount of time to address the issue before
any public disclosure. We are committed to fixing confirmed vulnerabilities
promptly and will announce security-relevant changes in the repository history.
