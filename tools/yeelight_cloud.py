"""Authenticated API helper; never prints tokens or raw error bodies."""

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class Cloud:
    def __init__(self, credentials=None):
        self.path = credentials or Path.home() / ".local/state/yeegate/credentials.json"
        self.credentials = json.loads(self.path.read_text())
        region = self.credentials["region"]
        self.base = ("https://api.yeelight.com" if region == "cn" else
                     f"https://api-{region}.yeelight.com") + "/apis/iot/v1"

    def post(self, path, body=None, house_id=None):
        token = self.credentials["token"]
        headers = {"Authorization": "Bearer " + token["accessToken"],
                   "Accept": "application/json", "Content-Type": "application/json",
                   "Accept-Language": "zh-CN", "bizType": "0"}
        if token.get("clientId"):
            headers["Client-Id"] = str(token["clientId"])
        if house_id:
            headers["houseId"] = str(house_id)
            headers["house-id"] = str(house_id)
        request = Request(self.base + path,
                          data=json.dumps(body or {}).encode(), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=15) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"Yeelight HTTP status {exc.code}") from None
        if isinstance(result, dict) and result.get("success") is False:
            raise RuntimeError("Yeelight API rejected request")
        return result

    def save_private(self, name, data):
        path = self.path.parent / name
        import os
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
        return path
