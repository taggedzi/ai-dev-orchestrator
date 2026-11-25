# Product web dependencies: installation review

Status: **Approved and installed, November 24, 2026.** The exact reviewed set
was installed offline into `.local/product-web-venv`; all 19 versions and
installed RECORD hashes verify, `pip check` passes and the base interpreter's
package list is unchanged. See [approval](web-install-approval.json) and
[measured evidence](web-install-evidence.json). The original approved plan bytes
are preserved at `.local/validation/web-dependency-review-01/approved-plan.md`.
The sections below retain the reviewed installation procedure and its limits.

## Exact proposed change

Create a **new** `.local/product-web-venv` using already installed
`C:\Python315\python.exe` (Python 3.15.2 / SQLite 3.53.4). Refuse an existing
environment rather than modifying or replacing it. Do not change host packages,
PATH, the original Python, product databases or either VM/journal.

Install the 19 selected wheels from the retained local wheelhouse, offline,
with required hashes and no source builds, dependency re-resolution or bytecode
compilation during installation. The wheelhouse is **4,044,961 bytes**. Two
packages contain native extensions: MarkupSafe and pydantic-core, both selected
as CPython 3.15 Windows AMD64 wheels. No wheel contains a `.pth` startup file.

The four requested packages resolved to FastAPI **0.165.0**, Uvicorn **0.54.0**,
Jinja2 **3.1.6** and HTTPX **0.28.1**. The complete 19-package set, exact wheel
names/hashes, declared license metadata and upstream dependencies are retained in
[the manifest](../../requirements/web-wheel-manifest.json). No legal or security
qualification is inferred from metadata or a hash.

| Reviewed artifact | SHA-256 |
| --- | --- |
| [Windows/Python 3.15 lock](../../requirements/web-win-py315.lock) | `a0a1619c04c3480dfc1b5a73cb783535b08f944c734af8d68eb5b658c7846cea` |
| [Selected-wheel manifest](../../requirements/web-wheel-manifest.json) | `7d4909ec027f84218363c4b18fc193b7c7adfb1ace0c94a1dfdfa10e8b7ae681` |

## Preparation evidence

Installed uv **0.13.9** resolved the public PyPI metadata with wheel-only mode
and generated exact package/version/hash pins. Pip **26.2.2** performed a
`--dry-run --ignore-installed --only-binary=:all: --require-hashes` check against
the lock, then downloaded the selected wheels without installing them. All 19
wheel hashes match both the resolver lock and pip report; none of those packages
is installed in the inspected Python 3.15 environment. No wheel code was imported.

Raw report and archives are in
`.local/validation/web-dependency-review-01/`. An initial uv invocation rejected
mutually exclusive `--no-build`/`--only-binary` options before resolution. The
corrected wheel-only invocation succeeded; no source build was enabled. The
sandbox denied launching the installed uv; the metadata-only command succeeded
with the tool's approved escalation. Neither action installed anything.

## Commands after approval

First verify the lock/manifest/archive hashes and absence of the destination.
Then execute only:

```powershell
C:/Python315/python.exe -m venv --without-pip .local/product-web-venv
C:/Python315/python.exe -m pip --python .local/product-web-venv/Scripts/python.exe install --no-index --find-links .local/validation/web-dependency-review-01/wheelhouse --require-hashes --only-binary=:all: --no-deps --no-compile -r requirements/web-win-py315.lock --disable-pip-version-check
```

Pip documents using [`--python` to manage a venv without pip](https://pip.pypa.io/en/stable/topics/python-option/).
Keep the existing base interpreter unchanged. After installation, verify all 19
versions, `pip check`, base/venv Python and SQLite identity, and run the product
tests. Retain the installed-file inventory and results. An interrupted/failed
installation remains a partial new environment for inspection; do not overwrite
or automatically delete it.

Approval includes these local installation/compatibility checks only. It does
not approve listening on a port, remote exposure, telemetry/export configuration,
model calls, source execution, VM work, native reservation transfer or publication.
The API/dashboard still needs implementation, authentication/CSRF/Host/Origin
checks and tests. Linux/self-hosted deployment is not qualified by this Windows
wheel selection.

## Primary-source context

FastAPI advises pinning a tested version and validating upgrades in its
[version guidance](https://fastapi.tiangolo.com/deployment/versions/). The
[uv locking documentation](https://docs.astral.sh/uv/pip/compile/) distinguishes
resolution/locking from environment synchronization. Jinja's
[installation documentation](https://jinja.palletsprojects.com/en/stable/intro/)
describes using a virtual environment and its MarkupSafe dependency. These are
source-reviewed prerequisites; application compatibility is still unmeasured.
