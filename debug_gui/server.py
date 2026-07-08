"""Local DAX88 debug GUI server."""

from __future__ import annotations

import argparse
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import json
import re
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import struct
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlparse

from dax88_protocol import (
    DEFAULT_PORT,
    MAGIC,
    Dax88Client,
    DaxConfig,
    DaxState,
    apply_event_to_state,
    build_command_frame,
    build_query_frame,
    frame_update_to_dict,
    parse_frame,
    safe_name,
)

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"


class DaxSubscription:
    """Persistent TCP subscription to DAX88 pushed status/events."""

    def __init__(self, host: str, port: int = DEFAULT_PORT, timeout: float = 2.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.lock = threading.RLock()
        self.sock: socket.socket | None = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.state: DaxState | None = None
        self.last_event: dict | None = None
        self.last_update: dict | None = None
        self.last_unknown: dict | None = None
        self.last_error: str | None = None
        self.last_rx = 0.0
        self.generation = 0
        self.update_seq = 0
        self.update_log: list[dict] = []
        self.connected = False

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run, name=f"dax88-{self.host}:{self.port}", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        with self.lock:
            sock = self.sock
            self.sock = None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def send(self, zone: int, command: str, value: int | bool) -> str:
        frame = build_command_frame(zone, command, value)
        with self.lock:
            sock = self.sock
        if sock is None:
            raise RuntimeError("subscription socket is not connected")
        sock.sendall(frame)
        return frame.hex(" ")

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "host": self.host,
                "port": self.port,
                "connected": self.connected,
                "generation": self.generation,
                "last_rx": self.last_rx,
                "last_error": self.last_error,
                "last_event": self.last_event,
                "last_update": self.last_update,
                "last_unknown": self.last_unknown,
                "update_log": list(self.update_log),
                "state": self.state.to_dict() if self.state else None,
            }

    def _run(self) -> None:
        backoff = 0.5
        while not self.stop_event.is_set():
            try:
                with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                    sock.settimeout(0.5)
                    with self.lock:
                        self.sock = sock
                        self.connected = True
                        self.last_error = None
                    sock.sendall(build_query_frame())
                    backoff = 0.5
                    self._read_loop(sock)
            except Exception as err:
                with self.lock:
                    self.connected = False
                    self.sock = None
                    self.last_error = str(err)
            if not self.stop_event.wait(backoff):
                backoff = min(5.0, backoff * 1.5)

    def _read_loop(self, sock: socket.socket) -> None:
        buf = b""
        while not self.stop_event.is_set():
            try:
                data = sock.recv(8192)
            except socket.timeout:
                continue
            if not data:
                raise RuntimeError("DAX88 closed the subscription socket")
            buf += data
            while True:
                frame, buf = _pop_frame(buf)
                if frame is None:
                    break
                self._handle_frame(frame)

    def _handle_frame(self, frame: bytes) -> None:
        update = parse_frame(frame)
        now = time.time()
        with self.lock:
            self.last_update = frame_update_to_dict(update)
            update_type = update.get("type")
            if update_type == "event":
                event = update["event"]
                self.last_event = event.to_dict()
                self.state = apply_event_to_state(self.state, event)
            elif update_type == "config":
                self.state = _apply_config_update(self.state, update["config"], update.get("raw_frame_hex", ""))
            elif update_type == "status":
                self.state = _apply_status_update(self.state, update["state"])
            else:
                self.last_unknown = self.last_update
            self.last_rx = now
            self.generation += 1
            self.update_seq += 1
            logged_update = dict(self.last_update)
            logged_update["seq"] = self.update_seq
            logged_update["rx"] = now
            self.update_log.append(logged_update)
            self.update_log = self.update_log[-200:]


def _apply_config_update(current: DaxState | None, config: DaxConfig, raw_frame_hex: str) -> DaxState:
    zones = current.zones if current else []
    if zones:
        zones = _apply_config_names(zones, config)
    return DaxState(
        device_name=config.device_name or (current.device_name if current else None),
        config=config,
        zones=zones,
        raw_response_hex=raw_frame_hex or (current.raw_response_hex if current else ""),
    )


def _apply_status_update(current: DaxState | None, status: DaxState) -> DaxState:
    config = current.config if current else status.config
    zones = status.zones
    if config and zones:
        zones = _apply_config_names(zones, config)
    return DaxState(
        device_name=(config.device_name if config else None) or status.device_name or (current.device_name if current else None),
        config=config,
        zones=zones,
        raw_response_hex=status.raw_response_hex,
    )


def _apply_config_names(zones, config: DaxConfig):
    renamed = []
    for zone in zones:
        renamed.append(
            replace(
                zone,
                name=safe_name(config.zones, zone.zone, f"Zone {zone.zone}"),
                source_name=safe_name(config.sources, zone.source, f"Source {zone.source}"),
            )
        )
    return renamed


def _pop_frame(buf: bytes) -> tuple[bytes | None, bytes]:
    start = buf.find(MAGIC)
    if start < 0:
        return None, b"" if len(buf) > 4096 else buf
    if start > 0:
        buf = buf[start:]
    if len(buf) < 20:
        return None, buf
    payload_len = struct.unpack("<I", buf[4:8])[0]
    total = 20 + payload_len
    if len(buf) < total:
        return None, buf
    return buf[:total], buf[total:]


class SubscriptionRegistry:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sessions: dict[tuple[str, int], DaxSubscription] = {}

    def get(self, host: str, port: int) -> DaxSubscription:
        key = (host, port)
        with self.lock:
            session = self.sessions.get(key)
            if session is None:
                session = DaxSubscription(host, port)
                self.sessions[key] = session
            session.start()
            return session


SUBSCRIPTIONS = SubscriptionRegistry()


def local_subnet_guess() -> str:
    local_ip = _local_route_ip()
    networks = _windows_local_networks()
    if local_ip:
        for network in networks:
            if local_ip in network:
                return str(network)
        if networks:
            return str(networks[0])
        return str(ipaddress.ip_network(f"{local_ip}/24", strict=False))
    if networks:
        return str(networks[0])
    return "192.168.1.0/24"


def _local_route_ip() -> ipaddress.IPv4Address | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return ipaddress.ip_address(sock.getsockname()[0])
    except OSError:
        return None
    finally:
        sock.close()


def _windows_local_networks() -> list[ipaddress.IPv4Network]:
    try:
        output = subprocess.check_output(["ipconfig"], text=True, encoding="utf-8", errors="ignore")
    except (OSError, subprocess.SubprocessError):
        return []

    records = []
    current: dict[str, object] = {}

    def flush_current() -> None:
        nonlocal current
        if current:
            records.append(current)
            current = {}

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            flush_current()
            continue
        if line.endswith(":") and " adapter " in line.lower():
            flush_current()
            continue

        ip_match = re.search(r"IPv4 Address[.\s]*:\s*([0-9.]+)", line)
        if ip_match:
            try:
                current["ip"] = ipaddress.ip_address(ip_match.group(1))
            except ValueError:
                current.pop("ip", None)
            continue

        mask_match = re.search(r"Subnet Mask[.\s]*:\s*([0-9.]+)", line)
        if mask_match:
            current["mask"] = mask_match.group(1)
            continue

        gateway_match = re.search(r"Default Gateway[.\s]*:\s*([0-9.]+)", line)
        if gateway_match:
            current["has_gateway"] = True

    flush_current()

    gateway_networks = []
    other_networks = []
    for record in records:
        local_ip = record.get("ip")
        mask = record.get("mask")
        if not isinstance(local_ip, ipaddress.IPv4Address) or not isinstance(mask, str):
            continue
        try:
            network = ipaddress.ip_network(f"{local_ip}/{mask}", strict=False)
        except ValueError:
            continue
        if local_ip.is_loopback or local_ip.is_link_local or network.prefixlen >= 31:
            continue
        if record.get("has_gateway"):
            gateway_networks.append(network)
        else:
            other_networks.append(network)
    return gateway_networks + other_networks

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
        if parsed.path == "/api/connect":
            self._handle_connect(parsed)
            return
        if parsed.path == "/api/state":
            self._handle_state(parsed)
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

    def _host_port(self, parsed) -> tuple[str, int]:
        qs = parse_qs(parsed.query)
        host = qs.get("host", [""])[0].strip()
        port = int(qs.get("port", [DEFAULT_PORT])[0])
        if not host:
            raise ValueError("host is required")
        return host, port

    def _handle_connect(self, parsed) -> None:
        try:
            host, port = self._host_port(parsed)
            session = SUBSCRIPTIONS.get(host, port)
            deadline = time.time() + 3.0
            snap = session.snapshot()
            while time.time() < deadline and not snap["state"] and not snap["last_error"]:
                time.sleep(0.05)
                snap = session.snapshot()
        except Exception as err:
            self._json({"ok": False, "error": str(err)}, HTTPStatus.BAD_REQUEST)
            return
        self._json({"ok": True, **snap})

    def _handle_state(self, parsed) -> None:
        try:
            host, port = self._host_port(parsed)
            session = SUBSCRIPTIONS.get(host, port)
            snap = session.snapshot()
        except Exception as err:
            self._json({"ok": False, "error": str(err)}, HTTPStatus.BAD_REQUEST)
            return
        self._json({"ok": True, **snap})

    def _handle_query(self, parsed) -> None:
        try:
            host, port = self._host_port(parsed)
            state = Dax88Client(host, port, 2.0).query()
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
            session = SUBSCRIPTIONS.get(host, port)
            sent_hex = session.send(zone, command, value)
        except Exception as err:
            self._json({"ok": False, "error": str(err)}, HTTPStatus.BAD_REQUEST)
            return
        self._json({"ok": True, "sent_hex": sent_hex, **session.snapshot()})

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
