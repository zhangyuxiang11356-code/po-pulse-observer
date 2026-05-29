# coding=utf-8
"""Filter a browser storage_state file down to X/Twitter-compatible cookies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ALLOWED_DOMAINS = ("x.com", "twitter.com", "twimg.com")
ALLOWED_SAMESITE = {"Strict", "Lax", "None"}


def is_allowed_domain(domain: str) -> bool:
    normalized = domain.lstrip(".").lower()
    return normalized in ALLOWED_DOMAINS or normalized.endswith(tuple(f".{item}" for item in ALLOWED_DOMAINS))


def filter_state(input_path: Path, output_path: Path) -> dict[str, object]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    cookies = []
    for cookie in payload.get("cookies", []) or []:
        domain = str(cookie.get("domain", "") or "")
        if not is_allowed_domain(domain):
            continue
        same_site = cookie.get("sameSite", "Lax")
        if same_site not in ALLOWED_SAMESITE:
            same_site = "Lax"
        try:
            expires = float(cookie.get("expires", -1))
        except (TypeError, ValueError):
            expires = -1
        cookies.append(
            {
                "name": str(cookie.get("name", "") or ""),
                "value": str(cookie.get("value", "") or ""),
                "domain": domain,
                "path": str(cookie.get("path", "") or "/"),
                "expires": expires,
                "httpOnly": bool(cookie.get("httpOnly", False)),
                "secure": bool(cookie.get("secure", True)),
                "sameSite": same_site,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps({"cookies": cookies, "origins": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    names = {cookie["name"] for cookie in cookies}
    return {
        "output": str(output_path),
        "cookie_count": len(cookies),
        "domains": sorted({cookie["domain"] for cookie in cookies}),
        "has_auth_token": "auth_token" in names,
        "has_ct0": "ct0" in names,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    args = parser.parse_args()
    result = filter_state(Path(args.input), Path(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
