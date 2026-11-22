"""Compile exact bounded guest lines; never execute a shell or contact a VM."""

import ast
import base64
import hashlib
import json
import shlex
import zlib
from pathlib import Path

from . import guest_transfer_entry as entry
from . import maintenance_serial_worker as serial

CHUNK = 480
MAX_MEMBER = 1024**2


def canonical(value):
    return serial.encode(value)


def digest(raw):
    return serial.digest(raw)


def subnonce(nonce, phase):
    return hashlib.sha256((nonce + ":" + phase).encode()).hexdigest()[:32]


def entry_bytes(grant):
    raw = Path(entry.__file__).read_bytes()
    serial.require(
        digest(raw) == grant["sources"]["entry"],
        "transfer entry source differs from granted bytes",
    )
    return raw


def quoted(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def packed_step(code, nonce, index, acknowledge=True):
    source = (
        "import sys\n"
        "if sys.flags.optimize: raise RuntimeError('fixed isolated invocation required')\n"
        "try:\n"
        + "\n".join(" " + line for line in code.splitlines())
        + (f'\n print("MCLI1_ACK_{nonce}_{index}",flush=True)' if acknowledge else "")
        + f'\nexcept BaseException:\n print("MCLI1_NACK_{nonce}_{index}",flush=True)\n raise SystemExit(2)\n'
    )
    serial.require(len(source.encode()) <= 16 * 1024, "guest step source exceeds bound")
    compile(source, "<mcli1-transfer>", "exec")
    packed = base64.b64encode(zlib.compress(source.encode(), 9)).decode()
    loader = f'import base64,zlib;exec(compile(zlib.decompress(base64.b64decode("{packed}")),"<mcli1-transfer>","exec"))'
    line = "/usr/bin/python3 -I -B -c " + shlex.quote(loader)
    serial.require(
        len(line) <= 2047 and all(32 <= ord(c) <= 126 for c in line),
        "compiled serial line exceeds tty bound",
    )
    return {"send": line, "ack": f"MCLI1_ACK_{nonce}_{index}"}


def serial_request(grant, steps, phase):
    return {
        "format": "mcli1-serial-exchange-v1",
        "mode": "guest",
        "request_id": subnonce(grant["run_nonce"], phase),
        "target_vm_uuid": grant["target"]["vm_uuid"],
        "pipe": "\\\\.\\pipe\\mcli1-maint-" + grant["target"]["vm_uuid"],
        "steps": steps,
        "activation_reference": grant["approval"]["transfer"],
        "worker_sha256": digest(Path(serial.__file__).read_bytes()),
        "expires_utc_ns": grant["phase_window"]["expires_utc_ns"],
        "expires_mono_ns": grant["phase_window"]["expires_mono_ns"],
    }


def identity_request(grant, grant_sha):
    nonce = subnonce(grant["run_nonce"], "identity")
    expected = {k: grant["target"][k] for k in ("dmi_uuid", "root_fs_uuid", "boot_id")}
    raw_source = entry_bytes(grant).decode()
    function = next(
        node
        for node in ast.parse(raw_source).body
        if isinstance(node, ast.FunctionDef) and node.name == "read_identity"
    )
    source = ast.get_source_segment(raw_source, function)
    source += "\ni=read_identity()\n"
    source += "assert all(i[k]==v for k,v in " + quoted(expected) + ".items())\n"
    source += (
        'import base64,json\ne={"format":"mcli1-transfer-identity-v1","grant_sha256":'
        + quoted(grant_sha)
        + ',"run_nonce":'
        + quoted(grant["run_nonce"])
        + ',"identity":i}\n'
    )
    source += f'print("MCLI1_DATA_{nonce}_0:"+base64.b64encode(json.dumps(e,sort_keys=True,separators=(",",":")).encode()).decode(),flush=True)'
    return serial_request(grant, [packed_step(source, nonce, 0)], "identity")


def guest_guard(identity, window, stage=None):
    code = (
        "import os,sys,json,time,stat,base64,zlib,hashlib\n"
        'assert sys.platform=="linux" and os.geteuid()==0\n'
        'assert not any(s in os.uname().release.lower() for s in ("wsl","microsoft"))\n'
        'assert open("/proc/sys/kernel/random/boot_id").read().strip()=='
        + quoted(identity["boot_id"])
        + "\n"
        'assert open("/sys/class/dmi/id/product_uuid").read().strip().lower()=='
        + quoted(identity["dmi_uuid"])
        + "\n"
        'r=os.stat("/")\nassert (r.st_dev,r.st_ino,os.stat("/proc/self/ns/mnt").st_ino)=='
        + repr((identity["root_dev"], identity["root_ino"], identity["mnt_ino"]))
        + "\n"
        f"assert {window['issued_utc_ns']}<=time.time_ns()<{window['expires_utc_ns']}\n"
        f"assert {window['issued_mono_ns']}<=time.monotonic_ns()<{window['expires_mono_ns']}\n"
        "u=0; flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC\n"
    )
    if stage is not None:
        code += 'r=os.open("/run",flags);s=os.fstat(r);assert s.st_uid==u and not stat.S_IMODE(s.st_mode)&0o022\n'
        code += (
            "d=os.open("
            + quoted(stage.rsplit("/", 1)[1])
            + ",flags,dir_fd=r);os.close(r)\n"
        )
        code += "s=os.fstat(d);assert s.st_uid==u and stat.S_IMODE(s.st_mode)==0o700\n"
    return code


def chunk_body(name, offset, raw):
    flags = "os.O_WRONLY|os.O_NOFOLLOW|os.O_CLOEXEC|" + (
        "os.O_CREAT|os.O_EXCL" if offset == 0 else "os.O_APPEND"
    )
    return (
        "f=os.open(" + quoted(name + ".part") + "," + flags + ",0o600,dir_fd=d)\n"
        f"s=os.fstat(f);assert stat.S_ISREG(s.st_mode) and s.st_uid==u and s.st_nlink==1 and stat.S_IMODE(s.st_mode)==0o600 and s.st_size=={offset}\n"
        "b=base64.b64decode(" + quoted(base64.b64encode(raw).decode()) + ")\n"
        "assert os.write(f,b)==len(b)\nos.fsync(f);os.close(f);os.fsync(d)\n"
    )


def finish_body(name, raw, compressed):
    return (
        "f=os.open("
        + quoted(name + ".part")
        + ",os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)\n"
        f"s=os.fstat(f);assert stat.S_ISREG(s.st_mode) and s.st_uid==u and s.st_nlink==1 and stat.S_IMODE(s.st_mode)==0o600 and s.st_size=={len(compressed)}\n"
        f"c=os.read(f,{len(compressed) + 1});os.close(f);assert len(c)=={len(compressed)} and hashlib.sha256(c).hexdigest()=="
        + quoted(digest(compressed))
        + "\n"
        f"z=zlib.decompressobj();b=z.decompress(c,{len(raw) + 1})\n"
        f"assert z.eof and not z.unused_data and not z.unconsumed_tail and len(b)=={len(raw)} and hashlib.sha256(b).hexdigest()=="
        + quoted(digest(raw))
        + "\n"
        "f=os.open("
        + quoted(name)
        + ",os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=d)\n"
        "assert os.write(f,b)==len(b)\nos.fsync(f);os.close(f);os.fsync(d)\n"
    )


def compile_upload(grant, grant_sha, identity, guest_window, files):
    blobs = dict(files)
    blobs["guest_transfer_entry.py"] = entry_bytes(grant)
    for name, raw in blobs.items():
        serial.require(
            isinstance(raw, bytes) and len(raw) <= MAX_MEMBER,
            "transfer member exceeds byte bound",
        )
        serial.require(
            name
            in {
                "guest_transfer_entry.py",
                "guest_maintenance_probe.py",
                "guest_maintenance_control.py",
                "inspection-spec.json",
                "request.json",
                "observation.json",
            },
            "transfer filename outside cohort",
        )
    catalog = {
        name: {"bytes": len(raw), "sha256": digest(raw)}
        for name, raw in sorted(blobs.items())
    }
    capsule = {
        "format": "mcli1-transfer-capsule-v1",
        "purpose": grant["purpose"],
        "run_nonce": grant["run_nonce"],
        "grant_sha256": grant_sha,
        "identity_sha256": digest(canonical(identity)),
        "identity": identity,
        "guest_window": guest_window,
        "files": catalog,
    }
    blobs["capsule.json"] = canonical(capsule)
    stage = (
        "/run/mcli1-"
        + ("observe" if grant["purpose"] == "inspect" else "control")
        + "-"
        + grant["run_nonce"]
    )
    nonce = subnonce(grant["run_nonce"], "upload")
    initial = guest_guard(identity, guest_window)
    initial += 'r=os.open("/run",flags);s=os.fstat(r);assert s.st_uid==u and not stat.S_IMODE(s.st_mode)&0o022\n'
    initial += (
        "os.mkdir("
        + quoted(stage.rsplit("/", 1)[1])
        + ",0o700,dir_fd=r);os.fsync(r);os.close(r)\n"
    )
    steps = [packed_step(initial, nonce, 0)]
    prefix = guest_guard(identity, guest_window, stage)
    layout = []
    for name, raw in sorted(blobs.items()):
        compressed = zlib.compress(raw, 9)
        serial.require(
            len(steps) + (len(compressed) + CHUNK - 1) // CHUNK + 2 <= 128,
            "transfer requires too many serial steps",
        )
        for offset in range(0, len(compressed), CHUNK):
            steps.append(
                packed_step(
                    prefix
                    + chunk_body(name, offset, compressed[offset : offset + CHUNK])
                    + "os.close(d)",
                    nonce,
                    len(steps),
                )
            )
        steps.append(
            packed_step(
                prefix + finish_body(name, raw, compressed) + "os.close(d)",
                nonce,
                len(steps),
            )
        )
        layout.append(
            {
                "name": name,
                "bytes": len(raw),
                "sha256": digest(raw),
                "compressed_bytes": len(compressed),
                "compressed_sha256": digest(compressed),
            }
        )
    source = blobs["guest_transfer_entry.py"]
    final = (
        prefix
        + 'f=os.open("guest_transfer_entry.py",os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)\n'
    )
    final += f"s=os.fstat(f);assert s.st_uid==u and s.st_nlink==1 and stat.S_IMODE(s.st_mode)==0o600 and s.st_size=={len(source)}\n"
    final += (
        f"b=os.read(f,{len(source) + 1});os.close(f);os.close(d);assert len(b)=={len(source)} and hashlib.sha256(b).hexdigest()=="
        + quoted(digest(source))
        + "\n"
    )
    path = stage + "/guest_transfer_entry.py"
    final += (
        "sys.argv="
        + quoted([path, digest(blobs["capsule.json"]), nonce, str(len(steps))])
        + "\n"
    )
    final += (
        "exec(compile(b,"
        + quoted(path)
        + ',"exec"),{"__name__":"__main__","__file__":'
        + quoted(path)
        + "})"
    )
    steps.append(packed_step(final, nonce, len(steps), acknowledge=False))
    request = serial_request(grant, steps, "upload")
    raw = canonical(request)
    serial.checked(raw, digest(raw))
    return {
        "request": request,
        "capsule": capsule,
        "capsule_sha256": digest(blobs["capsule.json"]),
        "layout": layout,
        "stage": stage,
    }
