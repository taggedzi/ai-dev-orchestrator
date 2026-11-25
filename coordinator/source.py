"""Trusted Git object intake. No checkout or source execution.

Input is a bounded byte map from a trusted intake controller, not a path to an
agent-controlled repository or archive. All objects are written in a new local
managed bare repository. These primitives do not establish stop/isolation proof.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .domain import Conflict, canonical, digest, ident, integer, require, text

MAX_FILES = 2000
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024
OID = re.compile(r"[0-9a-f]{40}")


def source_path(value):
    text(value, "source path", 4096)
    require(unicodedata.normalize("NFC", value) == value, "source path must be NFC")
    require(len(value.split("/")) <= 128, "source path nesting exceeds intake limit")
    require(
        not any(ord(c) < 32 or ord(c) == 127 or c in '\\<>:"|?*' for c in value),
        "source path contains unsafe characters",
    )
    for part in value.split("/"):
        require(
            part not in {"", ".", ".."}
            and not part.endswith((" ", "."))
            and len(part.encode("utf-8")) <= 255,
            "invalid source path component",
        )
        folded = part.casefold()
        require(
            folded != ".git"
            and not re.fullmatch(r"git~[0-9]+", folded)
            and not re.fullmatch(
                r"(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?", folded
            ),
            "source path names protected metadata or a device",
        )
    return value


@dataclass(frozen=True)
class SourceFile:
    data: bytes
    mode: str = "100644"

    def __post_init__(self):
        require(type(self.data) is bytes, "source contents must be bytes")
        require(len(self.data) <= MAX_FILE_BYTES, "source file too large")
        require(
            type(self.mode) is str and self.mode in {"100644", "100755"},
            "regular source files only",
        )


@dataclass(frozen=True, init=False)
class Snapshot:
    """Immutable validated source set; file modes are explicit, no symlinks."""

    _entries: tuple
    _manifest_json: str
    digest: str

    def __init__(self, files):
        require(type(files) is dict and len(files) <= MAX_FILES, "invalid source map")
        require(all(type(path) is str for path in files), "source paths must be text")
        aliases = {}
        entries = []
        total = 0
        for path, file in sorted(files.items()):
            source_path(path)
            require(type(file) is SourceFile, "source map needs SourceFile entries")
            total += len(file.data)
            parts = path.split("/")
            for end in range(1, len(parts) + 1):
                prefix = "/".join(parts[:end])
                key = prefix.casefold()
                require(
                    key not in aliases or aliases[key] == prefix,
                    "source paths alias on a case-insensitive filesystem",
                )
                aliases[key] = prefix
            entries.append((path, file))
        require(total <= MAX_SNAPSHOT_BYTES, "source snapshot too large")
        names = set(files)
        require(
            not any(
                "/".join(path.split("/")[:end]) in names
                for path in names
                for end in range(1, len(path.split("/")))
            ),
            "source file conflicts with a directory",
        )
        manifest = [
            {
                "path": path,
                "mode": file.mode,
                "bytes": len(file.data),
                "sha256": hashlib.sha256(file.data).hexdigest(),
            }
            for path, file in entries
        ]
        object.__setattr__(self, "_entries", tuple(entries))
        object.__setattr__(self, "_manifest_json", canonical(manifest))
        object.__setattr__(self, "digest", digest(manifest))

    @property
    def manifest(self):
        return json.loads(self._manifest_json)

    def files(self):
        return dict(self._entries)


@dataclass(frozen=True)
class CandidateBinding:
    attempt_id: str
    plan_digest: str
    task_digest: str
    generation: int

    def __post_init__(self):
        ident(self.attempt_id, "attempt id")
        integer(self.generation, "authority generation")
        for checksum in (self.plan_digest, self.task_digest):
            require(
                type(checksum) is str and re.fullmatch(r"[0-9a-f]{64}", checksum),
                "invalid candidate binding digest",
            )

    def record(self):
        return {
            "attempt_id": self.attempt_id,
            "plan_digest": self.plan_digest,
            "task_digest": self.task_digest,
            "generation": self.generation,
        }


class TrustedRepository:
    """Exclusive local object writer; private refs only, no accepted milestone ref.

    The root/config/objects must be outside every untrusted runtime. This is not
    an access-control mechanism against another process running as the owner.
    """

    def __init__(self, root, *, git=None):
        path = Path(root).absolute()
        require(
            path.is_dir() and not path.is_symlink() and not path.is_junction(),
            "managed repository must be an ordinary trusted directory",
        )
        self.root = path.resolve()
        self.repository = self.root / "objects.git"
        self.hooks = self.root / "empty-hooks"
        executable = git or shutil.which("git")
        require(executable is not None, "Git is unavailable")
        self.git = str(Path(executable).resolve())
        self.marker = json.loads((self.root / "repository.json").read_bytes())
        require(
            self.marker["path"] == str(self.root)
            and self.marker["format"] == "orchestrator-git-v1"
            and self.marker["object_format"] == "sha1",
            "copied or unsupported managed repository",
        )
        self._verify_layout()

    @classmethod
    def create(cls, root, *, git=None):
        path = Path(root).absolute()
        path.mkdir(parents=True, exist_ok=False)
        path = path.resolve()
        hooks = path / "empty-hooks"
        hooks.mkdir()
        executable = git or shutil.which("git")
        require(executable is not None, "Git is unavailable")
        executable = str(Path(executable).resolve())
        environment = cls._environment()
        result = subprocess.run(
            [
                executable,
                "init",
                "--bare",
                "--object-format=sha1",
                f"--template={hooks}",
                "--",
                str(path / "objects.git"),
            ],
            env=environment,
            cwd=path,
            capture_output=True,
            timeout=15,
            check=False,
        )
        require(result.returncode == 0, "managed Git initialization failed", Conflict)
        marker = {
            "format": "orchestrator-git-v1",
            "repository_id": uuid4().hex,
            "path": str(path),
            "object_format": "sha1",
            "config_sha256": hashlib.sha256(
                (path / "objects.git/config").read_bytes()
            ).hexdigest(),
        }
        (path / "repository.json").write_text(canonical(marker), encoding="utf-8")
        return cls(path, git=executable)

    @staticmethod
    def _environment():
        # Do not inherit GIT_DIR, alternates, config injection, replacement refs,
        # command tracing, author identities, askpass, hooks or transport setup.
        env = {
            key: os.environ[key]
            for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")
            if key in os.environ
        }
        env.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_ATTR_NOSYSTEM": "1",
                "GIT_NO_REPLACE_OBJECTS": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_AUTHOR_NAME": "Orchestrator intake",
                "GIT_AUTHOR_EMAIL": "intake@orchestrator.invalid",
                "GIT_COMMITTER_NAME": "Orchestrator intake",
                "GIT_COMMITTER_EMAIL": "intake@orchestrator.invalid",
                "GIT_AUTHOR_DATE": "@946684800 +0000",
                "GIT_COMMITTER_DATE": "@946684800 +0000",
                "LC_ALL": "C",
            }
        )
        return env

    def _verify_layout(self):
        for path in (
            self.repository,
            self.repository / "config",
            self.repository / "objects",
            self.repository / "refs",
            self.hooks,
        ):
            require(
                path.exists() and not path.is_symlink() and not path.is_junction(),
                "managed Git layout changed",
                Conflict,
            )
        require(
            hashlib.sha256((self.repository / "config").read_bytes()).hexdigest()
            == self.marker["config_sha256"],
            "managed Git configuration changed",
            Conflict,
        )
        require(
            not (self.repository / "objects/info/alternates").exists()
            and not (self.repository / "objects/info/http-alternates").exists()
            and not (self.repository / "shallow").exists()
            and not any(self.hooks.iterdir()),
            "external objects, shallow history or executable hooks are refused",
            Conflict,
        )

    def _run(self, *arguments, data=None, allow_failure=False):
        self._verify_layout()
        command = [
            self.git,
            "--no-pager",
            "--no-replace-objects",
            f"--git-dir={self.repository}",
            "-c",
            f"core.hooksPath={self.hooks}",
            "-c",
            f"core.attributesFile={os.devnull}",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.autocrlf=false",
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "core.fsync=committed",
            "-c",
            "merge.renormalize=false",
            "-c",
            "merge.renames=false",
            *arguments,
        ]
        try:
            result = subprocess.run(
                command,
                input=data,
                env=self._environment(),
                cwd=self.root,
                capture_output=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise Conflict(
                "Git outcome unknown; inspect private refs before retry"
            ) from error
        require(
            result.returncode == 0 or allow_failure,
            "trusted Git operation failed; inspect before retry",
            Conflict,
        )
        return result

    @staticmethod
    def _oid(raw):
        value = raw.decode("ascii").strip()
        require(OID.fullmatch(value), "Git returned an invalid object id", Conflict)
        return value

    def _tree(self, snapshot):
        tree = {}
        for path, file in snapshot.files().items():
            target = tree
            parts = path.split("/")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            oid = self._oid(
                self._run(
                    "hash-object", "-w", "--no-filters", "--stdin", data=file.data
                ).stdout
            )
            target[parts[-1]] = (file.mode, "blob", oid)

        def write(entries):
            rows = []
            for name, entry in sorted(entries.items()):
                mode, kind, oid = (
                    ("040000", "tree", write(entry)) if type(entry) is dict else entry
                )
                rows.append(f"{mode} {kind} {oid}\t{name}".encode() + b"\0")
            return self._oid(self._run("mktree", "-z", data=b"".join(rows)).stdout)

        return write(tree)

    def snapshot(self, revision):
        require(
            type(revision) is str and OID.fullmatch(revision), "invalid input revision"
        )
        require(
            self._run("cat-file", "-t", revision).stdout == b"commit\n",
            "input revision must be a commit",
        )
        entries = self._run("ls-tree", "-r", "-z", "--full-tree", revision).stdout
        files = {}
        total = 0
        for entry in entries.split(b"\0"):
            if not entry:
                continue
            header, raw_path = entry.split(b"\t", 1)
            mode, kind, raw_oid = header.decode("ascii").split(" ")
            require(kind == "blob" and mode in {"100644", "100755"}, "unsafe Git entry")
            path = source_path(raw_path.decode("utf-8"))
            require(
                path not in files and len(files) < MAX_FILES,
                "duplicate or excessive source entries",
            )
            size = int(self._run("cat-file", "-s", raw_oid).stdout)
            require(size <= MAX_FILE_BYTES, "source file too large")
            total += size
            require(total <= MAX_SNAPSHOT_BYTES, "source snapshot too large")
            raw = self._run("cat-file", "blob", raw_oid).stdout
            require(len(raw) == size, "Git blob size changed", Conflict)
            files[path] = SourceFile(raw, mode)
        return Snapshot(files)

    def _retain(self, category, key, revision):
        # Private audit refs only. Milestone acceptance uses advance_milestone_ref.
        ref = f"refs/orchestrator/{category}/{key}"
        symbolic = self._run("symbolic-ref", "-q", ref, allow_failure=True)
        require(
            symbolic.returncode == 1, "private ref is symbolic or unknown", Conflict
        )
        update = self._run(
            "update-ref", "--no-deref", ref, revision, "0" * 40, allow_failure=True
        )
        observed = self._run("show-ref", "--verify", "--hash", ref, allow_failure=True)
        require(
            observed.returncode == 0 and self._oid(observed.stdout) == revision,
            "private audit ref conflicts or has unknown outcome",
            Conflict,
        )
        return {"ref": ref, "reconciled_existing": update.returncode != 0}

    def baseline(self, snapshot):
        require(type(snapshot) is Snapshot, "validated source snapshot required")
        tree = self._tree(snapshot)
        message = canonical({"kind": "baseline", "source_digest": snapshot.digest})
        revision = self._oid(
            self._run("commit-tree", tree, data=message.encode()).stdout
        )
        retained = self._retain("baselines", snapshot.digest, revision)
        return {
            "repository_id": self.marker["repository_id"],
            "object_format": "sha1",
            "revision": revision,
            "tree": tree,
            "source_digest": snapshot.digest,
            **retained,
        }

    def candidate_intent(self, input_revision, snapshot, *, allowed_paths, binding):
        require(
            type(snapshot) is Snapshot and type(binding) is CandidateBinding,
            "validated snapshot and binding required",
        )
        require(
            type(allowed_paths) is list and allowed_paths,
            "explicit literal path scope required",
        )
        allowed = {source_path(path) for path in allowed_paths}
        require(len(allowed) == len(allowed_paths), "duplicate allowed path")
        before = self.snapshot(input_revision).files()
        after = snapshot.files()
        changed = sorted(
            path
            for path in before.keys() | after.keys()
            if before.get(path) != after.get(path)
        )
        require(
            set(changed) <= allowed,
            "candidate changes paths outside approved scope",
            Conflict,
        )
        intent = {
            "kind": "candidate",
            "repository_id": self.marker["repository_id"],
            "input_revision": input_revision,
            "binding": binding.record(),
            "source_digest": snapshot.digest,
            "allowed_paths": sorted(allowed),
        }
        return intent, changed

    def seal(self, input_revision, snapshot, *, allowed_paths, binding):
        intent, changed = self.candidate_intent(
            input_revision, snapshot, allowed_paths=allowed_paths, binding=binding
        )
        tree = self._tree(snapshot)
        key = digest(intent)
        revision = self._oid(
            self._run(
                "commit-tree",
                tree,
                "-p",
                input_revision,
                data=canonical(intent).encode(),
            ).stdout
        )
        # One sealed subject per admitted attempt. Changed content or bindings
        # cannot silently replace its receipt; a correction needs a fresh attempt.
        retained = self._retain("candidates", binding.attempt_id, revision)
        return {
            **intent,
            "revision": revision,
            "tree": tree,
            "changed_paths": changed,
            "parents": [input_revision],
            "intake_digest": key,
            "task_accepted": False,
            **retained,
        }

    def observe_candidate(self, input_revision, snapshot, *, allowed_paths, binding):
        """Read-only reconciliation. A missing ref never causes a new write."""
        intent, changed = self.candidate_intent(
            input_revision, snapshot, allowed_paths=allowed_paths, binding=binding
        )
        ref = f"refs/orchestrator/candidates/{binding.attempt_id}"
        require(
            self._run("symbolic-ref", "-q", ref, allow_failure=True).returncode == 1,
            "candidate ref is symbolic or unknown",
            Conflict,
        )
        observed = self._run("show-ref", "--verify", "--hash", ref, allow_failure=True)
        require(
            observed.returncode == 0,
            "candidate effect is not proven; do not replay",
            Conflict,
        )
        revision = self._oid(observed.stdout)
        raw = self._run("cat-file", "commit", revision).stdout
        checksum = hashlib.sha1(
            b"commit " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest()
        require(checksum == revision, "candidate commit bytes are corrupt", Conflict)
        headers, message = raw.split(b"\n\n", 1)
        lines = headers.split(b"\n")
        require(
            len(lines) == 4 and lines[0].startswith(b"tree "),
            "unexpected candidate commit headers",
            Conflict,
        )
        tree = self._oid(lines[0][5:])
        expected = [
            f"parent {input_revision}".encode(),
            b"author Orchestrator intake <intake@orchestrator.invalid> 946684800 +0000",
            b"committer Orchestrator intake <intake@orchestrator.invalid> 946684800 +0000",
        ]
        require(
            lines[1:] == expected and message == canonical(intent).encode(),
            "candidate ref does not match its durable intent",
            Conflict,
        )
        require(
            self.snapshot(revision).files() == snapshot.files(),
            "candidate source differs from its durable manifest",
            Conflict,
        )
        return {
            **intent,
            "revision": revision,
            "tree": tree,
            "changed_paths": changed,
            "parents": [input_revision],
            "intake_digest": digest(intent),
            "task_accepted": False,
            "ref": ref,
        }

    def _commit_info(self, revision):
        require(type(revision) is str and OID.fullmatch(revision), "invalid commit id")
        raw = self._run("cat-file", "commit", revision).stdout
        require(
            hashlib.sha1(b"commit " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            == revision,
            "commit content is corrupt",
            Conflict,
        )
        header, message = raw.split(b"\n\n", 1)
        lines = header.split(b"\n")
        require(lines[0].startswith(b"tree "), "missing commit tree", Conflict)
        tree = self._oid(lines[0][5:])
        parents = []
        for line in lines[1:]:
            if line.startswith(b"parent "):
                parents.append(self._oid(line[7:]))
        expected = [
            f"tree {tree}".encode(),
            *[f"parent {parent}".encode() for parent in parents],
            b"author Orchestrator intake <intake@orchestrator.invalid> 946684800 +0000",
            b"committer Orchestrator intake <intake@orchestrator.invalid> 946684800 +0000",
        ]
        require(lines == expected, "unexpected managed commit headers", Conflict)
        return tree, parents, message

    def _integration_intent(
        self, candidate, expected_head, proposal_id, authorization_digest, allowed_paths
    ):
        ident(proposal_id, "proposal id")
        require(
            type(authorization_digest) is str
            and re.fullmatch(r"[0-9a-f]{64}", authorization_digest),
            "invalid integration authorization digest",
        )
        require(
            type(allowed_paths) is list and allowed_paths,
            "explicit integration scope required",
        )
        allowed = sorted({source_path(path) for path in allowed_paths})
        require(len(allowed) == len(allowed_paths), "duplicate integration path")
        _, parents, _ = self._commit_info(candidate)
        require(len(parents) == 1, "candidate must have one input parent")
        self.snapshot(candidate)
        self.snapshot(expected_head)
        base = parents[0]
        require(
            self._run(
                "merge-base", "--is-ancestor", base, expected_head, allow_failure=True
            ).returncode
            == 0,
            "integration head is not an authorized input descendant",
            Conflict,
        )
        if base != expected_head:
            require(
                self._run(
                    "merge-base",
                    "--is-ancestor",
                    candidate,
                    expected_head,
                    allow_failure=True,
                ).returncode
                == 1,
                "head already contains candidate or ancestry is unknown",
                Conflict,
            )
        return {
            "kind": "integration",
            "repository_id": self.marker["repository_id"],
            "proposal_id": proposal_id,
            "authorization_digest": authorization_digest,
            "candidate_revision": candidate,
            "input_revision": base,
            "expected_head": expected_head,
            "allowed_paths": allowed,
            "strategy": "direct" if base == expected_head else "merge",
        }

    def _integration_receipt(self, intent, revision):
        tree, parents, message = self._commit_info(revision)
        if intent["strategy"] == "direct":
            require(
                revision == intent["candidate_revision"]
                and parents == [intent["expected_head"]],
                "direct integration differs from candidate",
                Conflict,
            )
        else:
            require(
                parents == [intent["expected_head"], intent["candidate_revision"]]
                and message == canonical(intent).encode(),
                "merged integration differs from its intent",
                Conflict,
            )
        before, after = self.snapshot(intent["expected_head"]), self.snapshot(revision)
        old, new = before.files(), after.files()
        changed = sorted(
            path for path in old.keys() | new.keys() if old.get(path) != new.get(path)
        )
        require(
            set(changed) <= set(intent["allowed_paths"]),
            "integration changes paths outside approved scope",
            Conflict,
        )
        return {
            **intent,
            "revision": revision,
            "tree": tree,
            "parents": parents,
            "changed_paths": changed,
            "source_digest": after.digest,
            "source_manifest": after.manifest,
            "input_source_manifest": before.manifest,
            "effective_diff_digest": digest(
                {"before": before.manifest, "after": after.manifest}
            ),
            "ref": f"refs/orchestrator/integrations/{intent['proposal_id']}",
            "task_accepted": False,
        }

    def descends_from(self, ancestor, descendant):
        """True when both are commits and ancestor is contained in descendant."""
        self.snapshot(ancestor)
        self.snapshot(descendant)
        return (
            self._run(
                "merge-base",
                "--is-ancestor",
                ancestor,
                descendant,
                allow_failure=True,
            ).returncode
            == 0
        )

    def stage_integration(
        self,
        candidate,
        expected_head,
        *,
        proposal_id,
        authorization_digest,
        allowed_paths,
    ):
        """Construct a private proposal; never updates a milestone/publication ref."""
        intent = self._integration_intent(
            candidate, expected_head, proposal_id, authorization_digest, allowed_paths
        )
        if intent["strategy"] == "direct":
            revision = candidate
        else:
            result = self._run(
                "merge-tree",
                "--write-tree",
                f"--merge-base={intent['input_revision']}",
                expected_head,
                candidate,
                allow_failure=True,
            )
            require(
                result.returncode == 0,
                "integration conflict or unknown merge result; no proposal retained",
                Conflict,
            )
            tree = self._oid(result.stdout.splitlines()[0])
            revision = self._oid(
                self._run(
                    "commit-tree",
                    tree,
                    "-p",
                    expected_head,
                    "-p",
                    candidate,
                    data=canonical(intent).encode(),
                ).stdout
            )
        receipt = self._integration_receipt(intent, revision)
        intent_oid = self._oid(
            self._run(
                "hash-object",
                "-w",
                "--no-filters",
                "--stdin",
                data=canonical(intent).encode(),
            ).stdout
        )
        self._retain("integration-intents", proposal_id, intent_oid)
        self._retain("integrations", proposal_id, revision)
        return receipt

    def observe_integration(
        self,
        candidate,
        expected_head,
        *,
        proposal_id,
        authorization_digest,
        allowed_paths,
    ):
        """Read-only recovery; a missing stage ref is held without reconstruction."""
        intent = self._integration_intent(
            candidate, expected_head, proposal_id, authorization_digest, allowed_paths
        )
        ref = f"refs/orchestrator/integrations/{proposal_id}"
        intent_ref = f"refs/orchestrator/integration-intents/{proposal_id}"
        require(
            self._run("symbolic-ref", "-q", intent_ref, allow_failure=True).returncode
            == 1,
            "integration intent ref is symbolic or unknown",
            Conflict,
        )
        observed_intent = self._run(
            "show-ref", "--verify", "--hash", intent_ref, allow_failure=True
        )
        require(
            observed_intent.returncode == 0,
            "integration intent effect missing; do not replay",
            Conflict,
        )
        intent_bytes = canonical(intent).encode()
        expected_oid = hashlib.sha1(
            b"blob " + str(len(intent_bytes)).encode() + b"\0" + intent_bytes
        ).hexdigest()
        require(
            self._oid(observed_intent.stdout) == expected_oid
            and self._run("cat-file", "blob", expected_oid).stdout == intent_bytes,
            "integration intent ref differs from its authorization",
            Conflict,
        )
        require(
            self._run("symbolic-ref", "-q", ref, allow_failure=True).returncode == 1,
            "integration ref is symbolic or unknown",
            Conflict,
        )
        observed = self._run("show-ref", "--verify", "--hash", ref, allow_failure=True)
        require(
            observed.returncode == 0,
            "integration effect missing; do not replay",
            Conflict,
        )
        return self._integration_receipt(intent, self._oid(observed.stdout))

    def _milestone_ref(self, milestone_id):
        ident(milestone_id, "milestone id")
        return f"refs/orchestrator/milestones/{milestone_id}"

    def _ref_oid(self, ref):
        symbolic = self._run("symbolic-ref", "-q", ref, allow_failure=True)
        require(
            symbolic.returncode == 1, "milestone ref is symbolic or unknown", Conflict
        )
        observed = self._run("show-ref", "--verify", "--hash", ref, allow_failure=True)
        if observed.returncode != 0:
            return None
        return self._oid(observed.stdout)

    def advance_milestone_ref(self, milestone_id, expected_revision, revision):
        """CAS one private milestone ref. This is not a branch or validation ref.

        A missing ref is created from the all-zero guard. An existing ref moves
        only from expected_revision. A ref already at the target is not rewritten.
        """
        self.snapshot(revision)
        if expected_revision is not None:
            self.snapshot(expected_revision)
        ref = self._milestone_ref(milestone_id)
        current = self._ref_oid(ref)
        if current == revision:
            return {
                "ref": ref,
                "guard_accepted": False,
                "created": False,
                "observed_revision": current,
                "task_accepted": False,
            }
        if current is None:
            guard = "0" * 40
        elif current == expected_revision:
            guard = expected_revision
        else:
            raise Conflict("milestone ref differs")
        update = self._run(
            "update-ref", "--no-deref", ref, revision, guard, allow_failure=True
        )
        observed = self._ref_oid(ref)
        require(
            update.returncode == 0 and observed == revision,
            "milestone ref update outcome is unknown",
            Conflict,
        )
        return {
            "ref": ref,
            "guard_accepted": True,
            "created": current is None,
            "observed_revision": observed,
            "task_accepted": False,
        }

    def observe_milestone_ref(self, milestone_id, revision):
        """Read a private milestone ref. A missing or old ref is not recreated."""
        self.snapshot(revision)
        ref = self._milestone_ref(milestone_id)
        current = self._ref_oid(ref)
        require(
            current == revision,
            "milestone ref effect missing; do not replay",
            Conflict,
        )
        return {
            "ref": ref,
            "guard_accepted": False,
            "observed_revision": current,
            "task_accepted": False,
        }

    def update_validation_ref(self, key, expected_revision, revision):
        """Measure the guarded update primitive on a private validation ref only."""
        ident(key, "validation ref key")
        self.snapshot(revision)
        if expected_revision is not None:
            self.snapshot(expected_revision)
        ref = f"refs/orchestrator/validation/{key}"
        require(
            self._run("symbolic-ref", "-q", ref, allow_failure=True).returncode == 1,
            "validation ref is symbolic or unknown",
            Conflict,
        )
        update = self._run(
            "update-ref",
            "--no-deref",
            ref,
            revision,
            expected_revision or "0" * 40,
            allow_failure=True,
        )
        observed = self._run("show-ref", "--verify", "--hash", ref, allow_failure=True)
        return {
            "ref": ref,
            "guard_accepted": update.returncode == 0,
            "observed_revision": self._oid(observed.stdout)
            if observed.returncode == 0
            else None,
            "task_accepted": False,
        }
