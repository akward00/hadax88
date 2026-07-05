"""Local DAX88 debug GUI server."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
from urllib.parse import parse_qs, urlparse

from dax88_protocol import DEFAULT_PORT, Dax88Client

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"


def local_subnet_guess() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        local_ip = sock.getsockname()[0]
    except OSError:
        return "192.168.1.0/24"
    finally:
        sock.close()
    return str(ipaddress.ip_network(f"{local_ip}/24", strict=False))


class DaxDebugHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/query":
            self._handle_query(parsed)
            return
        if parsed.path == "/api/scan":
            self._handle_scan(parsed)
            return
        if parsed.path == "/api/defaults":
            self._json({"subnet": local_subnet_guess(), "port": DEFAULT_PORT})
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/send":
            self._handle_send()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_query(self, parsed) -> None:
        qs = parse_qs(parsed.query)
        host = qs.get("host", [""])[0].strip()
        port = int(qs.get("port", [DEFAULT_PORT])[0])
        timeout = float(qs.get("timeout", [2.0])[0])
        if not host:
            self._json({"ok": False, "error": "host is required"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            state = Dax88Client(host, port, timeout).query()
        except Exception as err:
            self._json({"ok": False, "error": str(err)}, HTTPStatus.BAD_GATEWAY)
            return
        self._json({"ok": True, "state": state.to_dict()})

    def _handle_send(self) -> None:
        try:
            payload = self._read_json()
            host = str(payload["host"]).strip()
            port = int(payload.get("port", DEFAULT_PORT))
            zone = int(payload["zone"])
            command = str(payload["command"])
            value = payload["value"]
            if command not in {"power", "mute"}:
                value = int(value)
            ack = Dax88Client(host, port, float(payload.get("timeout", 2.0))).send(zone, command, value)
        except Exception as err:
            self._json({"ok": False, "error": str(err)}, HTTPStatus.BAD_REQUEST)
            return
        self._json({"ok": True, "ack_hex": ack.hex(" ")})

    def _handle_scan(self, parsed) -> None:
        qs = parse_qs(parsed.query)
        subnet = qs.get("subnet", [local_subnet_guess()])[0].strip()
        port = int(qs.get("port", [DEFAULT_PORT])[0])
        timeout = float(qs.get("timeout", [0.35])[0])
        try:
            network = ipaddress.ip_network(subnet, strict=False)
        except ValueError as err:
            self._json({"ok": False, "error": str(err)}, HTTPStatus.BAD_REQUEST)
            return
        hosts = [str(host) for host in network.hosts()]
        if len(hosts) > 512:
            self._json({"ok": False, "error": "Scan is limited to /23 or smaller networks"}, HTTPStatus.BAD_REQUEST)
            return

        found = []
        with ThreadPoolExecutor(max_workers=64) as pool:
            futures = {pool.submit(_scan_one, host, port, timeout): host for host in hosts}
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    found.append(result)
        found.sort(key=lambda item: tuple(int(part) for part in item["host"].split(".")))
        self._json({"ok": True, "devices": found})

    def _read_json(self) -> dict:
        length = int(self.headers.get("content-length", "0"))
        data = self.rfile.read(length)
        return json.loads(data.decode("utf-8"))

    def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _scan_one(host: str, port: int, timeout: float) -> dict | None:
    try:
        state = Dax88Client(host, port, timeout).query()
    except Exception:
        return None
    return {
        "host": host,
        "device_name": state.device_name or "DAX88",
        "zones": [zone.name for zone in state.zones],
        "sources": state.config.sources if state.config else [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DAX88 local debug GUI.")
    parser.add_argument("--bind", default="127.0.0.1", help="HTTP bind address")
    parser.add_argument("--port", type=int, default=8898, help="HTTP port")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.bind, args.port), DaxDebugHandler)
    print(f"DAX88 debug GUI: http://{args.bind}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
