#!/usr/bin/env python3
"""Collect allowlisted EBC RSS metadata into an unpublished review draft; stdlib."""
import argparse
import datetime as dt
from email.utils import parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re
import ssl
import sys
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import build_opener, HTTPRedirectHandler, HTTPSHandler, Request
import xml.etree.ElementTree as ET

from validate_observatory import MAX_JSON_BYTES, atomic_json, decode_json, iso_now, iso_z, safe_https, validate_data

FEEDS = (
    {"id": "agency-politics", "name": "Agência Brasil · política", "url": "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml", "path": "/politica/noticia/", "politics": True},
    {"id": "radio-politics", "name": "Radioagência Nacional · política", "url": "https://agenciabrasil.ebc.com.br/radioagencia-nacional/rss/politica/feed.xml", "path": "/radioagencia-nacional/", "politics": True},
    {"id": "agency-latest", "name": "Agência Brasil · últimas notícias", "url": "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml", "path": "/", "politics": False},
    {"id": "radio-latest", "name": "Radioagência Nacional · últimas notícias", "url": "https://agenciabrasil.ebc.com.br/radioagencia-nacional/rss/ultimasnoticias/feed.xml", "path": "/radioagencia-nacional/", "politics": False},
)
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 48
SOCKET_TIMEOUT_SECONDS = 6
FEED_DEADLINE_SECONDS = 15
WINDOW_START = dt.datetime(2026, 10, 8, 3, tzinfo=dt.timezone.utc)
WINDOW_END = dt.datetime(2026, 10, 26, 3, tzinfo=dt.timezone.utc)  # exclusive: 26/10 00:00 BRT
RELEVANCE = re.compile(r"eleic|eleitor|segundo turno|campanha|candidat|bolsonaro|lula|congresso|senado|camara|deputad|senador|stf|supremo|democrac|golpe|violencia politica|racismo|homofob|transfob|xenofob|intolerancia religiosa|misogin|escala 6x1|banco master")


class FeedError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FeedError("redirect rejected; feed allowlist must be reviewed explicitly")


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain_text(value):
    parser = PlainText()
    parser.feed(value)
    parser.close()
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def normalized(value):
    return "".join(character for character in unicodedata.normalize("NFD", value) if not unicodedata.combining(character)).lower()


def window_open(now):
    return WINDOW_START <= now < WINDOW_END


def allowlisted_feed(feed):
    return isinstance(feed, dict) and any(feed == item for item in FEEDS)


def article_link(value, feed):
    if not safe_https(value):
        return False
    parsed = urlsplit(value)
    return parsed.hostname == "agenciabrasil.ebc.com.br" and not parsed.fragment and parsed.path.startswith(feed["path"])


def fetch_feed(feed, opener=None, clock=time.monotonic):
    """No custom URLs, redirects, compression, credential headers or retries."""
    if not allowlisted_feed(feed):
        raise FeedError("feed is not allowlisted")
    opener = opener or build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(feed["url"], headers={"Accept": "application/rss+xml, application/xml, text/xml", "Accept-Encoding": "identity", "User-Agent": "BrasilDemocracia2026-draft-research/1.0"})
    deadline = clock() + FEED_DEADLINE_SECONDS
    with opener.open(request, timeout=SOCKET_TIMEOUT_SECONDS) as response:
        if response.status != 200 or response.geturl() != feed["url"]:
            raise FeedError("unexpected HTTP status or feed URL")
        if response.headers.get("Content-Encoding", "identity").lower() not in ("", "identity"):
            raise FeedError("compressed response rejected")
        media_type = response.headers.get_content_type()
        if media_type not in ("application/rss+xml", "application/xml", "text/xml"):
            raise FeedError("non-XML response rejected")
        length = response.headers.get("Content-Length")
        if length is not None:
            try:
                if int(length) < 0 or int(length) > MAX_PAYLOAD_BYTES:
                    raise FeedError("response exceeds 2 MiB")
            except ValueError as exception:
                raise FeedError("invalid/oversized Content-Length") from exception
        pieces, size = [], 0
        # HTTPResponse.read1 returns available data instead of waiting to fill a large buffer.
        read = getattr(response, "read1", response.read)
        while True:
            if clock() > deadline:
                raise FeedError("feed deadline exceeded")
            chunk = read(min(16384, MAX_PAYLOAD_BYTES - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_PAYLOAD_BYTES:
                raise FeedError("response exceeds 2 MiB")
            pieces.append(chunk)
        if clock() > deadline:
            raise FeedError("feed deadline exceeded")
    return b"".join(pieces)


def parse_feed(payload, feed, now):
    if not allowlisted_feed(feed):
        raise FeedError("feed is not allowlisted")
    if len(payload) > MAX_PAYLOAD_BYTES or b"\x00" in payload or re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", payload, re.I):
        raise FeedError("oversized payload, NUL or XML DTD/entities rejected")
    try:
        xml = payload.decode("utf-8-sig")
        root = ET.fromstring(xml)
    except (UnicodeError, ET.ParseError) as exception:
        raise FeedError("invalid UTF-8 RSS XML") from exception
    if root.tag != "rss" or root.find("channel") is None:
        raise FeedError("RSS channel required; Atom/HTML is outside this recipe")
    elements, stack = 0, [(root, 0)]
    while stack:
        element, depth = stack.pop()
        elements += 1
        if elements > 10000 or depth > 30:
            raise FeedError("XML node/depth limit exceeded")
        stack.extend((child, depth + 1) for child in element)
    items, rejected = [], {"missing": 0, "url": 0, "date": 0, "window": 0, "irrelevant": 0}
    for element in root.findall("./channel/item")[:2000]:
        title = plain_text(element.findtext("title", ""))
        source = element.findtext("link", "").strip()
        if not title or not source:
            rejected["missing"] += 1
            continue
        if not article_link(source, feed):
            rejected["url"] += 1
            continue
        try:
            published = parsedate_to_datetime(element.findtext("pubDate", "").strip())
            if published is None or published.tzinfo is None:
                raise ValueError("ambiguous publication timezone")
            published = published.astimezone(dt.timezone.utc)
        except (ValueError, TypeError, OverflowError):
            rejected["date"] += 1
            continue
        if published > now + dt.timedelta(minutes=5) or published < now - dt.timedelta(days=7):
            rejected["window"] += 1
            continue
        if not feed["politics"] and not RELEVANCE.search(normalized(title)):
            rejected["irrelevant"] += 1
            continue
        parsed = urlsplit(source)
        # EBC articles have path identities; preserve original URLs separately.
        canonical = urlunsplit(("https", parsed.hostname, parsed.path, "", ""))
        items.append({"id": hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20], "title": title[:220],
                      "source": canonical, "originalUrls": [source], "publisher": feed["name"].split(" · ")[0],
                      "publishedAt": iso_z(published), "observedAt": iso_z(now),
                      "category": "Política · agência" if feed["politics"] else "Notícias · agência",
                      "origins": [{"feedId": feed["id"], "feedUrl": feed["url"], "feedName": feed["name"]}],
                      "editorialStatus": "pending_review", "automatic": True, "ufs": [],
                      "geographyMethod": "Não inferida: exige revisão editorial; nenhum mapa alterado.",
                      "summary": "", "includeInIncidentTotal": False})
    return items, rejected


def merge_items(items):
    merged = {}
    for item in items:
        source = item["source"]
        if source not in merged:
            merged[source] = dict(item, originalUrls=list(item["originalUrls"]), origins=list(item["origins"]))
            continue
        previous = merged[source]
        for url in item["originalUrls"]:
            if url not in previous["originalUrls"]:
                previous["originalUrls"].append(url)
        for origin in item["origins"]:
            if origin not in previous["origins"]:
                previous["origins"].append(origin)
        if item["publishedAt"] != previous["publishedAt"]:
            previous["metadataConflict"] = "Publication timestamps differ across feeds; review original before use."
        if item["title"] != previous["title"]:
            previous["metadataConflict"] = "Title/timestamp variants across feeds; review original before use."
    return sorted(merged.values(), key=lambda item: (item["publishedAt"], item["source"]), reverse=True)[:MAX_ITEMS]


def collect(now=None, fetcher=fetch_feed, offline=False):
    now = now or iso_now()
    items, states = [], []
    skipped = "offline_requested" if offline else "outside_collection_window" if not window_open(now) else None
    for feed in FEEDS:
        state = {"feedId": feed["id"], "name": feed["name"], "url": feed["url"], "attemptedAt": iso_z(now)}
        if skipped:
            states.append(dict(state, status="skipped", reason=skipped, checkedAt=None))
            continue
        try:
            found, rejected = parse_feed(fetcher(feed), feed, now)
            items.extend(found)
            states.append(dict(state, status="ok", checkedAt=iso_z(now), accepted=len(found), rejected=rejected))
        except (FeedError, OSError, HTTPError, URLError, TimeoutError, ValueError) as exception:
            # No source payload, authorization headers or secrets in failure output.
            states.append(dict(state, status="unavailable", checkedAt=None, errorType=type(exception).__name__))
    success = sum(state["status"] == "ok" for state in states)
    status = "skipped" if skipped else "complete" if success == len(FEEDS) else "partial" if success else "unavailable"
    return {"draftSchemaVersion": 1, "status": status, "generatedAt": iso_z(now),
            "requiresEditorialReview": True, "published": False, "items": merge_items(items), "states": states,
            "collectionWindow": {"startInclusive": iso_z(WINDOW_START), "endExclusive": iso_z(WINDOW_END), "timezone": "America/Sao_Paulo"},
            "limits": {"maxPayloadBytesPerFeed": MAX_PAYLOAD_BYTES, "socketTimeoutSeconds": SOCKET_TIMEOUT_SECONDS,
                       "feedDeadlineSeconds": FEED_DEADLINE_SECONDS, "maxItems": MAX_ITEMS, "ageDays": 7},
            "editorialSeedModified": False, "limitations": [
                "Titles/dates are attributed feed metadata, not independently verified facts.",
                "No text body, transcript, politician, territorial violence case, legal status or aggregate is generated.",
                "Failures remain explicit; this draft does not replace the site's retained public data.",
                "Heuristic title filtering can omit relevant content or retain irrelevant content; review is required."
            ]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="read-only observatory-data.json")
    parser.add_argument("--output", type=Path, default=Path("out/observatory-news-draft.json"))
    parser.add_argument("--offline", action="store_true", help="produce an explicit skipped draft without network")
    args = parser.parse_args(argv)
    try:
        with args.data.open("rb") as stream:
            input_payload = stream.read(MAX_JSON_BYTES + 1)
        seed = decode_json(input_payload)
        validation = validate_data(seed)
        if not validation["valid"]:
            raise ValueError("editorial seed failed validation; collection not attempted")
        if args.output.resolve() == args.data.resolve():
            raise ValueError("output must not replace the editorial input")
        draft = collect(offline=args.offline)
        draft["inputSha256"] = hashlib.sha256(input_payload).hexdigest()
        draft["editorialReviewedAt"] = seed["editorialReviewedAt"]
        atomic_json(args.output, draft, args.data)
        print(f"draft={args.output} status={draft['status']} items={len(draft['items'])}; no publication")
        return 2 if draft["status"] == "unavailable" else 0
    except (ValueError, OSError, UnicodeError, RecursionError) as exception:
        print(f"collection stopped: {exception}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
