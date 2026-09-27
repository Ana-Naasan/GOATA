"""Real subprocess protocol fixture. No GPU or inference claim."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROTOCOL = "gvhmr-resident-1"


def emit(value):
    print(json.dumps({"protocol": PROTOCOL, **value}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--ready-delay", type=float, default=0)
    parser.add_argument("--job-delay", type=float, default=0)
    parser.add_argument("--mode", default="ok")
    parser.add_argument("--copy-native", type=Path)
    parser.add_argument("--allow-estimated-intrinsics", action="store_true")
    parser.add_argument("--allow-unverified-pinhole", action="store_true")
    args = parser.parse_args()
    root = args.data_root
    with (root / "launches.jsonl").open("a") as log:
        log.write(json.dumps({"pid": os.getpid(), "token_present": "PROCESSING_TOKEN" in os.environ,
                              "cwd": str(Path.cwd()), "pythonpath": os.environ.get("PYTHONPATH"),
                              "estimated": args.allow_estimated_intrinsics,
                              "pinhole": args.allow_unverified_pinhole}) + "\n")
    launches = len((root / "launches.jsonl").read_text().splitlines())
    if args.mode == "startup-exit" or args.mode == "recovery-exit" and launches > 1:
        sys.exit(2)
    # Match the approved worker: never reuse unknown scratch, even in tests.
    warmup = root / "resident.tmp"
    warmup.mkdir()
    (warmup / "marker").write_bytes(b"warmup")
    if args.mode == "warmup-budget":
        (warmup / "large").write_bytes(b"x" * 8192)
        time.sleep(60)
    if args.mode == "warmup-partial":
        sys.stdout.write('{"protocol":')
        sys.stdout.flush()
        time.sleep(60)
    if args.mode == "warmup-bad":
        emit({"event": "ready", "warmup_complete": False})
        time.sleep(60)
    time.sleep(args.ready_delay)
    shutil.rmtree(warmup)
    emit({"event": "ready", "warmup_complete": True, "pid": os.getpid()})
    if args.mode == "idle-exit":
        time.sleep(.15)
        sys.exit(3)
    for index, line in enumerate(sys.stdin, 1):
        request = json.loads(line)
        with (root / "requests.jsonl").open("a") as log:
            log.write(json.dumps(request) + "\n")
        output = Path(request["output"])
        if args.copy_native:
            shutil.copytree(args.copy_native, output)
        else:
            output.mkdir()
            (output / "pid").write_text(str(os.getpid()))
        time.sleep(args.job_delay)
        mode = args.mode
        if mode == "job-exit":
            sys.exit(4)
        if mode in {"timeout", "grandchild"}:
            if mode == "grandchild":
                code = ("import pathlib,time,sys; p=pathlib.Path(sys.argv[1]);\n"
                        "while True:\n p.mkdir(exist_ok=True); (p/'heartbeat').write_text(str(time.time())); time.sleep(.01)")
                child = subprocess.Popen([sys.executable, "-c", code, str(output)])
                (root / "grandchild.pid").write_text(str(child.pid))
            time.sleep(60)
        if mode == "oversized":
            sys.stdout.write("x" * 16385)
            sys.stdout.flush()
            time.sleep(60)
        if mode == "malformed":
            print("private path and secret, not JSON", flush=True)
            time.sleep(60)
        if mode == "partial":
            sys.stdout.write('{"event":')
            sys.stdout.flush()
            time.sleep(60)
        if mode == "budget":
            (output / "big").write_bytes(b"x" * 8192)
        if mode == "linked":
            (output / "link").symlink_to(root)
        if mode == "files":
            for number in range(130):
                (output / str(number)).touch()
        response = {"event": "result", "id": request["id"], "ok": True,
                    "resident_pid": os.getpid(), "job_index": index}
        if mode == "mismatched":
            response["id"] = "00000000-0000-0000-0000-000000000000"
        if mode == "not-bool":
            response["ok"] = 1
        if mode in {"failure", "recovery-exit"}:
            response["ok"] = False
        if mode == "overflow":
            print(json.dumps({"protocol": PROTOCOL, **response})[:-1] + ',"constructors":{"pose":1e999}}', flush=True)
        elif mode == "duplicate":
            print('{"protocol":"gvhmr-resident-1","event":"result","id":"' + request["id"]
                  + '","ok":false,"ok":true}', flush=True)
        elif mode == "extra":
            print(json.dumps({"protocol": PROTOCOL, **response}) + '\n{}', flush=True)
        else:
            emit(response)


if __name__ == "__main__":
    main()
