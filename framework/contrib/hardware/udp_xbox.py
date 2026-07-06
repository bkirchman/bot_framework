from __future__ import annotations

import json
import socket
import threading
from collections.abc import Callable, Mapping
from typing import Any, Optional

from framework.interfaces import Action, OutputDevice


class UDPXboxOutput(OutputDevice):
    def __init__(
        self,
        udp_ip: str = "192.168.1.196",
        udp_port: int = 5005,
        *,
        response_port: int = 5006,
        response_mode: int = 0,
        debug_mode: bool = False,
        response_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        socket_factory: Callable[[int, int], socket.socket] = socket.socket,
    ) -> None:
        self.udp_ip = udp_ip
        self.udp_port = udp_port
        self.response_port = response_port
        self._response_mode = max(0, min(2, response_mode))
        self._debug_mode = debug_mode
        self._response_callback = response_callback
        self._socket_factory = socket_factory
        self._send_socket = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        self._listener_running = False
        self._listener_thread: Optional[threading.Thread] = None
        self._receive_socket: Optional[socket.socket] = None
        self._sequence = 0
        self._sequence_lock = threading.Lock()

        if self._response_mode > 0 or self._debug_mode or self._response_callback is not None:
            self._start_listener()

    def execute(self, action: Action) -> None:
        payload = self._coerce_payload(action.payload)
        payload["seq"] = self._next_sequence()
        payload["resp"] = self._response_mode

        message = json.dumps(payload) + "\n"
        self._send_socket.sendto(message.encode("utf-8"), (self.udp_ip, self.udp_port))

        if self._debug_mode:
            print(f"[SEND] seq={payload['seq']} {payload}")

    def close(self) -> None:
        self._stop_listener()
        self._send_socket.close()

    def ping(self, timeout: float = 1.0) -> bool:
        sequence = self._next_sequence()
        payload = {"ping": 1, "seq": sequence, "resp": 1}
        message = json.dumps(payload) + "\n"

        if self._listener_running:
            self._send_socket.sendto(message.encode("utf-8"), (self.udp_ip, self.udp_port))
            if self._debug_mode:
                print(f"[PING] seq={sequence}")
            return True

        response_socket = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        response_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            response_socket.bind(("", self.response_port))
            response_socket.settimeout(timeout)
        except OSError:
            response_socket.close()
            self._send_socket.sendto(message.encode("utf-8"), (self.udp_ip, self.udp_port))
            return False

        self._send_socket.sendto(message.encode("utf-8"), (self.udp_ip, self.udp_port))
        try:
            data, _ = response_socket.recvfrom(1024)
            response = json.loads(data.decode("utf-8"))
            return response.get("msg_type") == "pong" and response.get("seq") == sequence
        except (socket.timeout, json.JSONDecodeError):
            return False
        finally:
            response_socket.close()

    def _next_sequence(self) -> int:
        with self._sequence_lock:
            self._sequence = (self._sequence + 1) % 65536
            return self._sequence

    def _start_listener(self) -> None:
        if self._listener_running:
            return

        receive_socket = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        receive_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            receive_socket.bind(("", self.response_port))
            receive_socket.settimeout(0.1)
        except OSError:
            receive_socket.close()
            return

        self._receive_socket = receive_socket
        self._listener_running = True
        self._listener_thread = threading.Thread(target=self._listener_loop, daemon=True)
        self._listener_thread.start()

    def _stop_listener(self) -> None:
        self._listener_running = False
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=1.0)
            self._listener_thread = None
        if self._receive_socket is not None:
            self._receive_socket.close()
            self._receive_socket = None

    def _listener_loop(self) -> None:
        while self._listener_running and self._receive_socket is not None:
            try:
                data, _ = self._receive_socket.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                response = json.loads(data.decode("utf-8", errors="replace").strip())
            except json.JSONDecodeError:
                response = {"raw": data.decode("utf-8", errors="replace").strip()}

            if self._debug_mode:
                print(f"[RESPONSE] {response}")

            if self._response_callback is not None:
                self._response_callback(response)

    @staticmethod
    def _coerce_payload(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise TypeError("UDPXboxOutput expects Action.payload to be a mapping of command values")
        return dict(payload)