"""Yeelight QR sign-in, following the official yeelight-home API contract."""

import argparse
import json
import os
from pathlib import Path
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

import qrcode


def post(base, path):
    request = Request(base + path, data=b"", method="POST", headers={
        "Accept": "application/json", "Accept-Language": "zh-CN", "bizType": "1"})
    with urlopen(request, timeout=15) as response:
        body = json.load(response)
    if body.get("success") is False:
        raise RuntimeError("Yeelight rejected the QR sign-in request")
    return body.get("data") or body


def login(args):
    base = f"https://api-{args.region}.yeelight.com"
    if args.region == "cn":
        base = "https://api.yeelight.com"
    device = args.device.upper()
    created = post(base, "/apis/account/user/scan-login/query/qrcode/" + quote(device, safe=""))
    qr_id = created.get("qrCodeId")
    if not qr_id:
        raise RuntimeError("Yeelight did not return a QR sign-in identifier")
    qrcode.make(f"cli&{device}&{qr_id}").save(args.qr_image)
    print(f"QR ready: {args.qr_image}", flush=True)
    previous = None
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        time.sleep(3)
        result = post(base, "/apis/account/user/scan-login/check/qrcode/" + quote(qr_id, safe=""))
        status = result.get("status")
        if status != previous:
            print("Login status:", status, flush=True)
            previous = status
        if status == "EXPIRED":
            raise RuntimeError("QR sign-in expired")
        token = result.get("token")
        if status == "LOGIN" and isinstance(token, dict) and token.get("accessToken"):
            args.credentials.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(args.credentials, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump({"region": args.region, "token": token,
                           "source": result.get("source")}, stream)
            print("Signed in. Credentials saved privately; token not printed.", flush=True)
            return
    raise RuntimeError("QR sign-in timed out")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=["cn", "sg", "us", "de"], default="sg")
    parser.add_argument("--device", default="B0:3C:DC:CB:2A:22")
    parser.add_argument("--qr-image", type=Path, default=Path("yeelight-login.png"))
    parser.add_argument("--credentials", type=Path,
                        default=Path.home() / ".local/state/yeegate/credentials.json")
    login(parser.parse_args())
