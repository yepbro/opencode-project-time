# Contributing to opencode-project-time

Thank you for considering contributing. This plugin reports how much time
OpenCode agents spent on a project, using read-only queries against OpenCode's
local SQLite database.

## Code of Conduct

By participating in this project, you agree to abide by our
[Code of Conduct](CODE_OF_CONDUCT.md). Please read it before interacting with
the project.

## How Can I Contribute?

### Reporting Bugs

Bugs are tracked as [GitHub issues](https://github.com/yepbro/opencode-project-time/issues).
Before creating a bug report, check that the issue has not already been
reported. Include:

- A clear and descriptive title
- Steps to reproduce the problem
- Expected and actual behavior
- OpenCode version (`opencode --version`), Node.js and Python versions, and OS
- Output of `opencode plugin list` and relevant lines from
  `~/.local/share/opencode/log/opencode.log`, with tokens, keys, and session
  contents redacted

Security vulnerabilities must be reported privately as described in
[SECURITY.md](SECURITY.md), not as public issues.

### Suggesting Enhancements

Enhancement suggestions are also tracked as GitHub issues. Please provide:

- A clear and descriptive title
- A detailed description of the proposed behavior
- Why the enhancement would be useful to plugin users

### Pull Requests

1. Fork the repository and create your branch from `main`.
2. If you add or change behavior, add tests.
3. Ensure the checks below pass.
4. Open a pull request with a clear description of the problem and the solution.

`main` is protected: changes require a pull request with one approving review,
and history must stay linear (squash or rebase; merge commits are disabled).
The owner reviews and merges pull requests. The owner can also push directly to
`main`; everyone else must use a pull request.

## Development Setup

Requirements: OpenCode 2, Node.js with npm, and Python 3 on `PATH`. There is no
build step — OpenCode loads the TypeScript source directly, and the Python
scripts use only the standard library.

```bash
git clone git@github.com:yepbro/opencode-project-time.git
cd opencode-project-time
npm install
```

To test the plugin inside OpenCode, add the checkout directory to `plugins` in
`~/.config/opencode/opencode.jsonc`:

```jsonc
{
  "plugins": ["/path/to/opencode-project-time"]
}
```

Then verify with `opencode plugin list`; run `opencode service restart` if the
plugin does not appear. Use `/project-time` in a session to exercise the full
path from the plugin to `collect.py` and `report.py`.

## Checks

Run before submitting a pull request:

```sh
python3 -m unittest discover -s tests -v
node --test tests/command.test.mjs
```

The Node test uses the `typescript` dev dependency installed by `npm install`.
Set `TS_MODULE` to override its location. The test stubs `@opencode/plugin` and
`python3`, so it checks argument parsing and script invocation but not actual
loading in OpenCode; use `opencode plugin list` and `/project-time` for that.

No formatter or linter is configured yet. Keep the existing style: single
quotes and no semicolons in TypeScript, four-space indentation in Python, and
no unrelated changes.

## Commit Messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

<optional body>
```

Common types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`.

## Review Process

- The owner reviews pull requests and may request changes or provide feedback.
- Small, focused pull requests are reviewed and merged faster than large ones.
- Once approved, the owner merges with a squash or rebase to keep `main` linear.

## License

By contributing to `opencode-project-time`, you agree that your contributions
are licensed under the project's MIT license, with no additional terms. See
[LICENSE](LICENSE).
