# bibump

[![PyPI - Version](https://img.shields.io/pypi/v/bibump.svg)](https://pypi.org/project/bibump)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/bibump.svg)](https://pypi.org/project/bibump)

-----

Checks every entry in a `.bib` file against its upstream provider (INSPIRE-HEP
and Zenodo) and reports whether an update is available, e.g.:

- an INSPIRE-HEP preprint that has since been accepted/published in a journal
  (or has grown an erratum), or
- a Zenodo record for which a newer version has been released (typically
  changing the `version`/`title`/`doi` fields).

## Table of Contents

- [Installation](#installation)
- [License](#license)
- [Usage](#usage)

## Installation

```console
pip install bibump
```

## License

`bibump` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.

## Usage

```console
$ bibump references.bib
```

For every entry with an update available, prints a colored diff against
what each provider offers, then asks which version to keep:

```
[zenodo] lukas_heinrich_2026_21360926
  option 1: -> lukas_heinrich_2026_23082467 (doi, month, title, url, version)
    - title = scikit-hep/pylhe: v2.0.0
    + title = scikit-hep/pylhe: v2.1.0
    ...
  [0] keep original
  [1] use option 1
Pick [0-1] (default 0, keep original):
```

`0` always keeps the entry exactly as it was; `1`, `2`, ... apply one of the
suggested updates (a provider can offer more than one candidate, e.g. an
ambiguous INSPIRE-HEP search or a Zenodo free-text search). Once you've gone
through every entry, the file is rewritten in place (a `.bak` backup is kept
alongside it first).

Other flags:

- `-y`, `--yes` — don't prompt, apply the first suggested update for every
  entry automatically.
- `-n`, `--dry-run` — don't prompt or write anything, just print the diffs.
- `-v`, `--verbose` — also list entries that are already up to date, or for
  which no provider could be determined.
- `--no-backup` — don't write a `.bak` file when changes are written.
- `--no-color` — disable colored output.
- `-i`, `--ignore FIELD` — ignore a field when comparing entries (repeatable,
  or comma-separated: `--ignore keywords,note`). Handy for fields you set
  by hand, like `keywords`, that providers don't know about.

If stdin isn't a terminal (e.g. piped input or CI), bibump automatically
falls back to `--dry-run` instead of hanging on a prompt.

### Reading from stdin

The `bibfile` argument can be omitted, in which case bibump reads the
`.bib` content from stdin and writes the (possibly updated) result to
stdout, so it can be used as a filter:

```console
$ cat references.bib | bibump -y > references.bib.new
```

All diffs and status messages are written to stderr in this mode, keeping
stdout clean for the BibTeX output. Since stdin is already consumed by the
input itself, this mode always runs non-interactively (same fallback as
above): pass `-y` to apply updates, or leave it as a dry-run check.
