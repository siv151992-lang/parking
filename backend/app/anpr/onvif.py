"""ONVIF support.

* WS-Discovery: dependency-free multicast probe that finds ONVIF cameras on
  the local network (UDP 239.255.255.250:3702).
* Stream URI lookup: uses onvif-zeep (optional, requirements-ai.txt) to ask
  a camera for its RTSP URI(s) given IP / port / credentials.
"""
from __future__ import annotations

import re
import socket
import uuid
from urllib.parse import urlparse

PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
 xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
 <e:Header><w:MessageID>uuid:{uid}</w:MessageID>
 <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
 <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action></e:Header>
 <e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>
</e:Envelope>"""


def discover(timeout: float = 3.0) -> list[dict]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(timeout)
    found: dict[str, dict] = {}
    try:
        sock.sendto(PROBE.format(uid=uuid.uuid4()).encode(), ("239.255.255.250", 3702))
        while True:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                break
            text = data.decode("utf-8", "ignore")
            xaddrs = re.findall(r"<[^>]*XAddrs>([^<]+)</", text)
            scopes = re.findall(r"<[^>]*Scopes>([^<]+)</", text)
            urls = xaddrs[0].split() if xaddrs else []
            name = hw = ""
            for scope in (scopes[0].split() if scopes else []):
                if "/name/" in scope:
                    name = scope.rsplit("/", 1)[-1]
                if "/hardware/" in scope:
                    hw = scope.rsplit("/", 1)[-1]
            port = urlparse(urls[0]).port if urls else 80
            found[addr[0]] = {"ip_address": addr[0], "onvif_port": port or 80, "xaddrs": urls, "name": name, "hardware": hw}
    except OSError as e:
        raise RuntimeError(f"Discovery failed: {e}") from e
    finally:
        sock.close()
    return list(found.values())


def get_stream_uris(ip: str, port: int, username: str, password: str) -> list[dict]:
    try:
        from onvif import ONVIFCamera  # type: ignore
    except ImportError as e:
        raise RuntimeError("onvif-zeep is not installed (pip install onvif-zeep)") from e
    cam = ONVIFCamera(ip, port, username, password)
    media = cam.create_media_service()
    out = []
    for profile in media.GetProfiles():
        req = media.create_type("GetStreamUri")
        req.ProfileToken = profile.token
        req.StreamSetup = {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}}
        uri = media.GetStreamUri(req).Uri
        res = None
        try:
            enc = profile.VideoEncoderConfiguration
            res = f"{enc.Resolution.Width}x{enc.Resolution.Height}"
        except AttributeError:
            pass
        out.append({"profile": profile.Name, "token": profile.token, "rtsp_url": uri, "resolution": res})
    return out
