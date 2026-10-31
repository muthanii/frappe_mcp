# Contributing

## Commit messages

This project uses [Conventional Commits](https://www.conventionalcommits.org)
and [Semantic Versioning](https://semver.org). Releases are cut automatically
from commit messages, so every commit on `main` must follow the format:

```
<type>(<optional scope>): <description>
```

| Commit | Release |
|---|---|
| `fix: ...` | patch (1.2.0 → 1.2.1) |
| `feat: ...` | minor (1.2.0 → 1.3.0) |
| `feat!: ...` or a `BREAKING CHANGE:` footer | major (1.2.0 → 2.0.0) |
| `docs`, `chore`, `ci`, `test`, `refactor`, `style`, `build`, `perf` | no release |

Pull requests are checked by the **Conventional Commits** workflow (PR title
and every commit). To catch mistakes before you push, install the local hook:

```bash
pip install pre-commit
pre-commit install
```

## Releasing

Don't bump versions or tag by hand. On every push to `main`, the **Release**
workflow:

1. runs the tests,
2. lets python-semantic-release pick the next version from the commits since
   the last tag, update `pyproject.toml`, `server.json` and `CHANGELOG.md`,
   commit `chore(release): X.Y.Z`, tag `vX.Y.Z` and create a GitHub Release,
3. publishes to PyPI, Docker Hub and GHCR,
4. publishes `server.json` to the official MCP Registry.

`pyproject.toml` holds the version; `scripts/sync_version.py` copies it into
`server.json`. Run `python scripts/sync_version.py --check` to verify they
agree.
