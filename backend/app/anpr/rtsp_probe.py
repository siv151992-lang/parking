"""Explain why an RTSP stream cannot be opened.

OpenCV/FFmpeg only reports "could not open". This module talks to the camera
directly (TCP connect, then an RTSP DESCRIBE with Basic or Digest auth) so the
user is told whether the camera is unreachable, the port is closed, the login
is wrong, or the stream path is wrong.
"""
from __future__ import annotations

import hashlib
import os
import re
import socket
from urllib.parse import unquote, urlparse, urlunparse


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def _auth_header(challenge: str, user: str, password: str, method: str, uri: str) -> str | None:
    scheme = challenge.split(" ", 1)[0].lower()
    if scheme == "basic":
        import base64
        return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    if scheme != "digest":
        return None
    params = dict(re.findall(r'(\w+)="?([^",]*)"?', challenge))
    realm, nonce = params.get("realm", ""), params.get("nonce", "")
    ha1 = _md5(f"{user}:{realm}:{password}")
    ha2 = _md5(f"{method}:{uri}")
    parts = [f'username="{user}"', f'realm="{realm}"', f'nonce="{nonce}"', f'uri="{uri}"']
    if "auth" in params.get("qop", "").split(","):
        cnonce = os.urandom(8).hex()
        resp = _md5(f"{ha1}:{nonce}:00000001:{cnonce}:auth:{ha2}")
        parts += ["qop=auth", "nc=00000001", f'cnonce="{cnonce}"']
    else:
        resp = _md5(f"{ha1}:{nonce}:{ha2}")
    parts.append(f'response="{resp}"')
    if "opaque" in params:
        parts.append(f'opaque="{params["opaque"]}"')
    return "Digest " + ", ".join(parts)


def _request(sock: socket.socket, uri: str, cseq: int, auth: str | None) -> tuple[int, str, dict]:
    lines = [f"DESCRIBE {uri} RTSP/1.0", f"CSeq: {cseq}", "Accept: application/sdp", "User-Agent: SmartParking"]
    if auth:
        lines.append(f"Authorization: {auth}")
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    data = b""
    while b"\r\n\r\n" not in data and len(data) < 65536:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    head = data.split(b"\r\n\r\n", 1)[0].decode(errors="replace").split("\r\n")
    m = re.match(r"RTSP/\d\.\d\s+(\d{3})\s*(.*)", head[0] if head else "")
    if not m:
        raise ValueError("not an RTSP response")
    headers: dict[str, list[str]] = {}
    for line in head[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers.setdefault(k.strip().lower(), []).append(v.strip())
    return int(m.group(1)), m.group(2), headers


def diagnose(url: str, timeout: float = 4.0) -> str | None:
    """Return a plain-language reason the stream fails, or None if the camera
    accepted the login and the stream path (the problem is then decoding)."""
    p = urlparse(url)
    if p.scheme.lower() != "rtsp" or not p.hostname:
        return None
    host, port = p.hostname, p.port or 554
    user, password = unquote(p.username or ""), unquote(p.password or "")
    netloc = host + (f":{p.port}" if p.port else "")
    uri = urlunparse(p._replace(netloc=netloc))

    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except socket.timeout:
        return (f"No answer from {host}:{port}. The camera is switched off, the IP address is wrong, "
                f"or this server is not on the camera's network.")
    except ConnectionRefusedError:
        return (f"{host} is reachable but refused port {port}. RTSP is disabled on the camera "
                f"or it uses a different RTSP port.")
    except OSError as e:
        return f"Cannot reach {host}:{port} ({e.strerror or e}). Check the IP address and the network."

    try:
        sock.settimeout(timeout)
        code, reason, headers = _request(sock, uri, 1, None)
        if code == 401:
            if not user:
                return "The camera requires a username and password."
            challenges = headers.get("www-authenticate", [])
            challenge = next((c for c in challenges if c.lower().startswith("digest")), challenges[0] if challenges else "")
            auth = _auth_header(challenge, user, password, "DESCRIBE", uri)
            if auth is None:
                return f"The camera asked for an unsupported login method ({challenge.split(' ', 1)[0]})."
            code, reason, headers = _request(sock, uri, 2, auth)
            if code == 401:
                return ("Wrong username or password. Note: many cameras lock the account for several "
                        "minutes after repeated failed logins.")
        if code == 200:
            return None
        if code == 404:
            return f"Login OK, but the stream path {p.path or '/'} does not exist. Choose another camera brand or enter the RTSP URL."
        if code in (403,):
            return "The camera rejected this user (403). Give the user live-view / RTSP permission in the camera's settings."
        if code == 454 or code == 400:
            return f"The camera rejected the stream path ({code} {reason}). Choose another camera brand or enter the RTSP URL."
        return f"The camera answered RTSP {code} {reason}."
    except socket.timeout:
        return f"{host}:{port} accepted the connection but did not answer RTSP. Check the RTSP port."
    except (OSError, ValueError):
        return f"{host}:{port} is not an RTSP server. Check the RTSP port."
    finally:
        sock.close()
