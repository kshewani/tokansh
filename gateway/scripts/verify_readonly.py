"""Opt-in real read-only verification. Requires exported DRUNIX_* credentials paths.

Starts/stops only a new gateway child process; never manages DRUNIX containers.
"""
import http.client
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import time


def sanitized_stderr(value, env):
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    value = re.sub(r"-----BEGIN [^-]+-----.*?(?:-----END [^-]+-----|$)", "[REDACTED PEM]", value, flags=re.S)
    for name, secret in env.items():
        if secret and any(word in name.upper() for word in ("PASSWORD", "SECRET", "TOKEN", "PRIVATE_KEY")):
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"(?i)(password|token|secret|authorization)\s*[:=]\s*\S+", r"\1=[REDACTED]", value)
    value = re.sub(r"[A-Za-z0-9+/=_-]{80,}", "[REDACTED ENCODED DATA]", value)
    return value.strip()[:2000] or "No stderr detail returned."


def peer_cli(drunix, env, address, *arguments):
    # Copy per command: selecting a query peer must never affect channel checks.
    command_env = dict(env, CORE_PEER_ADDRESS=address)
    try:
        result = subprocess.run([str(drunix / "build/bin/peer"), *arguments], env=command_env,
                                capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired as exc:
        detail = exc.stderr or ""
        if isinstance(detail, bytes):
            detail = detail.decode(errors="replace")
        raise RuntimeError("Read-only peer CLI timed out: " + sanitized_stderr(detail, command_env)) from None
    if result.returncode:
        raise RuntimeError("Read-only peer CLI verification failed: " + sanitized_stderr(result.stderr, command_env))
    return result.stdout


def main():
    gateway = Path(__file__).resolve().parents[1]
    repo = gateway.parent
    drunix = Path(os.environ.get("DRUNIX_REPOSITORY", str(Path.home() / "projects/drunix")))
    required = ["DRUNIX_MSP_ID", "DRUNIX_CERT_PATH", "DRUNIX_KEY_PATH", "DRUNIX_TLS_CA_PATH",
                "DRUNIX_PEER_ENDPOINT", "DRUNIX_TLS_SERVER_NAME"]
    if any(not os.environ.get(name) for name in required):
        raise SystemExit("Export the required DRUNIX_* configuration first; no credentials are generated.")
    env = dict(os.environ, GOTOOLCHAIN="local")
    env.update(FABRIC_CFG_PATH=str(drunix / "drunix-network/config"), FABRIC_LOGGING_SPEC="error",
               CORE_PEER_TLS_ENABLED="true", CORE_PEER_LOCALMSPID=env["DRUNIX_MSP_ID"],
               CORE_PEER_MSPCONFIGPATH=str(Path(env["DRUNIX_CERT_PATH"]).parent.parent),
               CORE_PEER_TLS_ROOTCERT_FILE=env["DRUNIX_TLS_CA_PATH"])

    committing_peer = env.get("DRUNIX_CLI_COMMITTING_PEER_ADDRESS", "localhost:7061")
    lite_peer = env.get("DRUNIX_CLI_LITE_PEER_ADDRESS", "localhost:7051")

    def blockchain_info():
        output = peer_cli(drunix, env, committing_peer, "channel", "getinfo", "-c", "mychannel")
        info = json.loads(output.split("Blockchain info: ", 1)[1])
        return {key: info[key] for key in ("height", "currentBlockHash", "previousBlockHash")}

    before = blockchain_info()
    expected = json.loads(peer_cli(drunix, env, lite_peer, "chaincode", "query", "-C", "mychannel", "-n", "basic", "-c", '{"Args":["GetAllAssets"]}'))
    probe = subprocess.run([str(gateway / "bin/probe")], env=env, capture_output=True, text=True, timeout=20)
    if probe.returncode:
        # probe prints only reviewed, sanitized configuration/evaluation errors.
        raise RuntimeError("SDK read-only probe failed: " + probe.stderr.strip())
    actual = json.loads(probe.stdout)["assets"]
    assert sorted(actual, key=lambda a: a["ID"]) == sorted(expected, key=lambda a: a["ID"])

    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    env["DRUNIX_LISTEN_ADDRESS"] = f"127.0.0.1:{port}"
    env["DRUNIX_GATEWAY_URL"] = env["TOKANSH_TEST_GATEWAY_URL"] = f"http://127.0.0.1:{port}"
    process = subprocess.Popen([str(gateway / "bin/gateway")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for attempt in range(50):
            if process.poll() is not None:
                raise RuntimeError("New gateway listener failed to start; no existing process was stopped")
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            try:
                connection.request("GET", "/health")
                response = connection.getresponse()
                if response.status == 200:
                    response.read()
                    break
            except OSError:
                time.sleep(0.1)
            finally:
                connection.close()
        else:
            raise RuntimeError("New gateway did not become live")
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.request("GET", "/v1/basic/assets")
            response = connection.getresponse()
            assert response.status == 200
            observed = json.loads(response.read())["data"]
            assert observed["source"] == "DRUNIX_EVALUATE"
            assert sorted(observed["result"], key=lambda a: a["ID"]) == sorted(expected, key=lambda a: a["ID"])
        finally:
            connection.close()
        env["RUN_DRUNIX_INTEGRATION"] = "1"
        subprocess.run(["go", "test", "-mod=readonly", "-count=1", "-run", "TestDRUNIXReadOnlyIntegration", "-v", "./internal/readonly"],
                       cwd=gateway, env=env, check=True, timeout=60)
        subprocess.run([str(repo / "backend/.venv/bin/python"), "-m", "pytest", "-q",
                        "tests/test_drunix.py::test_real_private_gateway_integration"],
                       cwd=repo / "backend", env=env, check=True, timeout=60)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    after = blockchain_info()
    assert before == after, "Channel height or block hashes changed; investigate external activity without resetting anything"
    print(json.dumps({"sdk_cli_full_payload_match": True, "http_cli_full_payload_match": True,
                      "fastapi_real_read_test": "PASS", "asset_ids": sorted(a["ID"] for a in actual),
                      "assets": sorted(actual, key=lambda a: a["ID"]),
                      "channel_height_before": before["height"], "channel_height_after": after["height"],
                      "blockchain_before": before, "blockchain_after": after,
                      "new_gateway_process_stopped": True}))


if __name__ == "__main__":
    main()
