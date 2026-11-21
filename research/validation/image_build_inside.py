"""Run only inside the approved offline image builder, with no host mounts."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path("/inputs")
EVIDENCE = Path("/build-evidence")


def run(args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True, timeout=300)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(path, destination, prefix):
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(path) as archive:
        # The host prepared this exact checksum-pinned archive. Python's data
        # filter supplies another extraction boundary inside the disposable build.
        archive.extractall(destination, filter="data")
    target = destination / prefix
    if not target.is_dir():
        raise ValueError("unexpected archive root")
    return target


def main():
    if os.name != "posix" or ROOT != Path.cwd():
        raise ValueError("offline builder working directory required")
    manifest = json.loads((ROOT / "context-manifest.json").read_bytes())
    for name, expected in manifest["files"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("build input changed: " + name)
    EVIDENCE.mkdir()
    run([sys.executable, "-m", "venv", "/opt/build-env"])
    pip = ["/opt/build-env/bin/python", "-m", "pip"]
    run(
        pip
        + [
            "install",
            "--no-index",
            "--no-deps",
            "--require-hashes",
            "-r",
            "build-requirements.txt",
        ]
    )
    wheels = Path("/wheels")
    wheels.mkdir()
    sdist = ROOT / "archives/func_timeout-4.3.5.tar.gz"
    run(
        pip
        + [
            "wheel",
            "--no-index",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheels),
            str(sdist),
        ]
    )
    for package in ["openhands-sdk", "openhands-tools", "openhands-agent-server"]:
        run(
            pip
            + [
                "wheel",
                "--no-index",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(wheels),
                str(ROOT / "source" / package),
            ]
        )
    built = sorted(wheels.glob("*.whl"))
    if len(built) != 4:
        raise ValueError("expected exactly four locally built wheels")
    requirements = (ROOT / "runtime-requirements.txt").read_text()
    requirements += "".join(str(p) + " --hash=sha256:" + sha(p) + "\n" for p in built)
    (EVIDENCE / "installed-requirements.txt").write_text(requirements)
    run([sys.executable, "-m", "venv", "--without-pip", "/opt/openhands"])
    target_pip = pip[:3] + ["--python", "/opt/openhands/bin/python"]
    run(
        target_pip
        + [
            "install",
            "--no-index",
            "--no-deps",
            "--require-hashes",
            "-r",
            str(EVIDENCE / "installed-requirements.txt"),
        ]
    )
    run(target_pip + ["check"])
    runtime = Path("/opt/runtime")
    (runtime / "bin").mkdir(parents=True)
    (runtime / "lib").mkdir()
    (runtime / "licenses").mkdir()
    node = extract(
        ROOT / "assets/node-v22.16.0-linux-x64.tar.xz",
        Path("/work/node"),
        "node-v22.16.0-linux-x64",
    )
    shutil.copy2(node / "bin/node", runtime / "bin/node")
    shutil.copy2(node / "LICENSE", runtime / "licenses/node.txt")
    git = extract(ROOT / "assets/git-2.51.0.tar.xz", Path("/work/git"), "git-2.51.0")
    # Only local Git operations are in the fixture. Do not inherit the builder's
    # system Git, curl/SSH helpers, Perl or optional regex integrations.
    flags = [
        "prefix=/opt/runtime/git",
        "NO_CURL=YesPlease",
        "NO_EXPAT=YesPlease",
        "NO_OPENSSL=YesPlease",
        "NO_GETTEXT=YesPlease",
        "NO_TCLTK=YesPlease",
        "NO_PERL=YesPlease",
        "NO_PYTHON=YesPlease",
        "NO_INSTALL_HARDLINKS=YesPlease",
    ]
    run(["make", "-j2", *flags, "all", "install"], cwd=git)
    (runtime / "bin/git").symlink_to("../git/bin/git")
    shutil.copy2(git / "COPYING", runtime / "licenses/git.txt")
    shutil.copy2(ROOT / "source/LICENSE", runtime / "licenses/openhands.txt")
    shutil.copy2(ROOT / "assets/tini-static-amd64", runtime / "bin/tini")
    (runtime / "bin/tini").chmod(0o755)
    # Explicitly retain the builder's C++ runtime as copied artifacts; these
    # files are inventoried separately from the final base's dpkg database.
    for library in ["libstdc++.so.6", "libgcc_s.so.1"]:
        shutil.copy2(
            Path("/usr/lib/x86_64-linux-gnu") / library, runtime / "lib" / library
        )
    for package in ["libstdc++6", "libgcc-s1"]:
        shutil.copy2(
            Path("/usr/share/doc") / package / "copyright",
            runtime / "licenses" / (package + ".txt"),
        )
    run([str(runtime / "bin/node"), "--version"])
    run([str(runtime / "bin/git"), "--version"])
    run([str(runtime / "bin/tini"), "--version"])
    run(
        [
            "/opt/openhands/bin/python",
            "-c",
            "import importlib.metadata as m; import openhands.sdk, openhands.agent_server; from openhands.tools.terminal import TerminalTool; from openhands.tools.file_editor import FileEditorTool; assert m.version('litellm') == '1.105.1'; assert m.version('openhands-sdk') == '1.62.0'",
        ]
    )
    run(
        [
            "/opt/openhands/bin/python",
            "-c",
            "import importlib.metadata as m,json; print(json.dumps(sorted([(d.metadata['Name'],d.version) for d in m.distributions()])))",
        ]
    )
    evidence = {
        "input_manifest_sha256": sha(ROOT / "context-manifest.json"),
        "built_wheels": {p.name: sha(p) for p in built},
        "copied_runtime_files": {
            p.relative_to(runtime).as_posix(): sha(p)
            for p in sorted(runtime.rglob("*"))
            if p.is_file()
        },
        "classification": "offline preparation imports/versions; not M1-12 or executor qualification",
    }
    (EVIDENCE / "build-receipt.json").write_text(
        json.dumps(evidence, sort_keys=True, indent=2) + "\n"
    )
    shutil.copy2(ROOT / "context-manifest.json", EVIDENCE / "context-manifest.json")


if __name__ == "__main__":
    main()
