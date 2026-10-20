"""Diagnostic : que répond l'API ZeroMEV pour des blocs de différents âges ?"""

import time

import requests

from collector import _block_at

URL = "https://data.zeromev.org/v1/mevBlock"
now = int(time.time())

for label, days in [("hier", 1), ("il y a 30 j", 30), ("il y a 180 j", 180), ("il y a 1 an", 365)]:
    block = _block_at(now - days * 86400)
    try:
        r = requests.get(URL, params={"block_number": block}, timeout=30)
        body = r.text[:300].replace("\n", " ")
        print(f"[{label}] bloc {block} -> HTTP {r.status_code}, {len(r.text)} octets : {body}")
    except requests.RequestException as exc:
        print(f"[{label}] bloc {block} -> ERREUR : {exc}")
    time.sleep(0.5)
