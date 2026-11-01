#!/usr/bin/env python3
"""
Tag every six-month EClog client with the crawler family of its bot-labelled requests (protocol v1.1).

  python tag_bot_family.py [--input ml_pipeline/data/eclog.zip] [--out ml_pipeline/data/eclog6m_bot_family.csv]

Family = the label_eclog.py bot pattern that matched the user agent (lower-cased, version stripped), e.g.
googlebot, semrushbot, python-requests. For the generic patterns (crawler, spider, bot.html) the family is
the user agent's product token containing bot/crawler/spider (e.g. "facebookexternalhit" stays generic).
A client's family is the most frequent family among its bot-labelled requests; purity = that share.
"""

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_eclog_sessions import open_rows  # noqa: E402
from label_eclog import BOT_UA_PATTERNS, PROGRAMMATIC_UA_PATTERNS, get_label_and_confidence  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
GENERIC = {"crawler", "spider", "bot.html"}
TOKEN = re.compile(r"([A-Za-z][A-Za-z0-9_.\-]*(?:bot|crawler|spider)[A-Za-z0-9_\-]*)", re.IGNORECASE)


def family(ua):
    label, _ = get_label_and_confidence(ua)
    if label != "bot":
        return None
    m = BOT_UA_PATTERNS.search(ua)
    if m:
        f = m.group(1).lower()
        if f in GENERIC:
            tokens = [t.lower() for t in TOKEN.findall(ua) if t.lower() not in ("bot.html",)]
            f = ("generic:" + tokens[0].split("/")[0]) if tokens else "generic:" + f
        return f
    m = PROGRAMMATIC_UA_PATTERNS.search(ua)
    return m.group(1).lower().rstrip("/") if m else "unattributed"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=str(REPO / "ml_pipeline" / "data" / "eclog.zip"))
    ap.add_argument("--out", default=str(REPO / "ml_pipeline" / "data" / "eclog6m_bot_family.csv"))
    args = ap.parse_args()

    cache, per_client = {}, defaultdict(Counter)
    for row in open_rows(args.input):
        ua = row["UserAgent"]
        if ua not in cache:
            cache[ua] = family(ua)
        f = cache[ua]
        if f is not None:
            per_client[row["IpId"]][f] += 1
    with open(args.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["IpId", "family", "bot_rows", "purity"])
        for ip, c in sorted(per_client.items()):
            fam, n = c.most_common(1)[0]
            total = sum(c.values())
            w.writerow([ip, fam, total, round(n / total, 6)])
    fams = Counter(c.most_common(1)[0][0] for c in per_client.values())
    print(f"{len(per_client):,} clients with bot-labelled requests; families: {fams.most_common(25)}")


if __name__ == "__main__":
    main()
