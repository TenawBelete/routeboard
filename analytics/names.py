"""Turn the registry's network list into names people recognise.

Input lines look like:  `15169 GOOGLE, US`  or
`7552 VIETEL-AS-AP Viettel Group, VN`  (handle, optional description, country).
"""

import re

# Registry handles of the best-known networks -> the name everyone uses.
KNOWN = {
    174: "Cogent", 701: "Verizon", 714: "Apple", 1273: "Vodafone", 1299: "Arelion", 2906: "Netflix", 2914: "NTT",
    3257: "GTT", 3320: "Deutsche Telekom", 3333: "RIPE NCC", 3356: "Lumen", 3491: "PCCW Global", 4134: "China Telecom",
    4637: "Telstra", 4837: "China Unicom", 5511: "Orange", 6453: "Tata Communications", 6461: "Zayo",
    6762: "Telecom Italia Sparkle", 6939: "Hurricane Electric", 7018: "AT&T", 7922: "Comcast", 8075: "Microsoft",
    9498: "Bharti Airtel", 12956: "Telxius", 13335: "Cloudflare", 15169: "Google", 16509: "Amazon", 14618: "Amazon",
    20940: "Akamai", 32934: "Meta", 36459: "GitHub", 54113: "Fastly", 63949: "Akamai (Linode)", 14061: "DigitalOcean",
    24940: "Hetzner", 30987: "EriTel", 24757: "Ethio Telecom", 30990: "Djibouti Telecom", 16276: "OVHcloud", 20473: "Vultr", 8452: "Telecom Egypt", 3215: "Orange France", 3352: "Telefónica España",
    12389: "Rostelecom", 9121: "Türk Telekom", 4766: "Korea Telecom", 2516: "KDDI", 17676: "SoftBank", 4713: "NTT Docomo",
    55836: "Reliance Jio", 45609: "Bharti Airtel Mobile", 7473: "Singtel", 4826: "Vocus", 37100: "SEACOM", 30844: "Liquid Telecom",
}
_SUFFIX = re.compile(r"(-AS(-AP|N)?|-ASN?\d*|-NET|-AP|-BLOCK|-BACKBONE)+$", re.I)
_LEGAL = re.compile(
    r",?\s+(inc\.?|llc\.?|l\.l\.c\.?|ltd\.?|limited|gmbh|s\.?a\.?|s\.a\.[a-z]\.?|s\.l\.u?\.?|corp\.?|corporation|company|share company|share"
    r"|co\.?,? ltd\.?|pvt\.? ltd\.?|pte\.? ?(ltd\.?)?|b\.v\.|ab|plc|jsc|pjsc|ooo|s\.?r\.?l\.?|s\.p\.a\.?|a\.s\.|s\.r\.o\.|sp\. z o\.o\."
    r"|s\.? de r\.?l\.? de c\.?v\.?|s\.?a\.? de c\.?v\.?|spolka akcyjna|a/s|oy|oyj|kft|d\.o\.o\.|ag|se|nv|bv|sas|lda|ltda\.?|eireli|me|epp)$", re.I)


def display_name(asn: int, handle: str, description: str) -> str:
    if asn in KNOWN:
        return KNOWN[asn]
    if description:
        name = description.strip()
        short = re.search(r"\(([A-Za-z][A-Za-z0-9 .&-]{2,24})\)\s*$", name)
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name) if short else name      # "Long Name (Short)" -> keep the long form without the tail
        for _ in range(2):                         # "Foo Bar Co., Ltd." -> "Foo Bar"
            name = _LEGAL.sub("", name).strip(" ,")
        if name.isupper() and len(name) > 4:
            name = name.title()
        if name:
            return name[:60]
    base = _SUFFIX.sub("", handle).replace("-", " ").replace("_", " ").strip() or handle
    return base.title() if base.isupper() and len(base) > 4 else base


def parse_line(line: str):
    """-> (asn, handle, name, country) or None for anything malformed."""
    line = line.strip()
    num, sep, rest = line.partition(" ")
    if not sep or not num.isdigit():
        return None
    body, comma, cc = rest.rpartition(", ")
    if not comma:
        body, cc = rest, ""
    cc = cc.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", cc):
        cc = None
    body = body.strip()
    if " - " in body:                               # "HANDLE - Full Name" (handle may contain spaces)
        handle, _, description = body.partition(" - ")
        handle = handle.strip().replace(" ", "-")
    elif body.startswith("- "):                     # "- Full Name" (no handle registered)
        handle, description = "", body[2:]
    else:
        handle, _, description = body.partition(" ")
    description = description.strip(" -")
    if not handle and description:
        handle = re.sub(r"[^A-Za-z0-9]+", "-", description).strip("-").upper()[:40]
    if not handle or handle.startswith("-"):       # "-Reserved AS-" etc.
        return None
    asn = int(num)
    return asn, handle[:80], display_name(asn, handle, description), cc
