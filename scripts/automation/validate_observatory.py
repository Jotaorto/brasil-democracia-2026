#!/usr/bin/env python3
"""Read-only structural validator for the observatory seed. Python 3.13+, stdlib."""
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit, parse_qs

UF_CODES = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
MAX_JSON_BYTES = 2 * 1024 * 1024
CARD_ARRAYS = ("cases", "historical", "rightsCards", "campaign", "dossiers", "congress", "international", "influencers")
REQUIRED_ARRAYS = CARD_ARRAYS + ("layers", "rightsMetrics", "polls", "programComparison", "images", "sourceDirectory", "editorialRules", "liveStreams")
REQUIRED_OBJECTS = ("states", "lead", "election", "mendonca", "democracy", "congressBalance", "pollAgenda", "video")
GRAPH_STATUSES = frozenset(("confirmado_documentalmente", "declaracao_atribuida", "alegacao_em_disputa", "analise_atribuida"))
URL_KEYS = frozenset(("url", "source", "reportSource", "articleSource", "channelUrl", "userUrl", "authorUrl", "sourcePage", "originalSource", "fileUrl", "licenseUrl"))


def iso_now():
    return dt.datetime.now(dt.timezone.utc)


def iso_z(value):
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_instant(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp requires a timezone")
    return parsed.astimezone(dt.timezone.utc)


def valid_civil_date(value, partial=False):
    if not isinstance(value, str):
        return False
    try:
        if partial and re.fullmatch(r"\d{4}", value):
            return 1 <= int(value) <= 9999
        if partial and re.fullmatch(r"\d{4}-\d{2}", value):
            dt.date.fromisoformat(value + "-01")
            return True
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            dt.date.fromisoformat(value)
            return True
        parse_instant(value)
        return True
    except (ValueError, OverflowError):
        return False


def safe_https(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 1500:
        return False
    if re.search(r"[\x00-\x20\x7f\\]", value):
        return False
    try:
        url = urlsplit(value)
        return url.scheme == "https" and bool(url.hostname) and not url.username and not url.password and url.port is None
    except ValueError:
        return False


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def decode_json(payload):
    if len(payload) > MAX_JSON_BYTES:
        raise ValueError("JSON exceeds 2 MiB")
    return json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unique_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite JSON value: {value}")))


def load_json(path):
    with Path(path).open("rb") as stream:
        return decode_json(stream.read(MAX_JSON_BYTES + 1))


def atomic_json(path, value, input_path=None):
    destination = Path(path).resolve()
    if input_path is not None and destination == Path(input_path).resolve():
        raise ValueError("output must not replace the editorial input")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_data(data, now=None):
    """Validate structure and provenance; never alter data or certify factual truth."""
    now = now or iso_now()
    errors, warnings, coverage = [], [], []

    def error(path, message):
        errors.append(f"{path}: {message}")

    def text(value, path, maximum=10000):
        if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
            error(path, f"requires nonempty string, at most {maximum} characters")

    def count(value, path):
        if type(value) is not int or not 0 <= value <= 9007199254740991:
            error(path, "requires nonnegative JSON/JavaScript-safe integer, not boolean/null")

    def percentage(value, path):
        if type(value) not in (int, float) or not 0 <= value <= 100:
            error(path, "requires finite percentage between 0 and 100")

    def sources(value, path):
        if not isinstance(value, list) or not 1 <= len(value) <= 50:
            error(path, "requires 1..50 attributed source objects")
            return
        for index, source in enumerate(value):
            key = f"{path}[{index}]"
            if not isinstance(source, dict):
                error(key, "requires object")
                continue
            if not safe_https(source.get("url")):
                error(key + ".url", "requires absolute HTTPS URL without credentials/port")
            text(source.get("publisher"), key + ".publisher", 300)

    def walk(value, path="$", depth=0):
        if depth > 30:
            error(path, "nesting exceeds 30")
            return
        if isinstance(value, dict):
            for key, child in value.items():
                graph_endpoint = key == "source" and path.startswith("$.networkGraph.edges[")
                if key in URL_KEYS and isinstance(child, str) and not graph_endpoint and not safe_https(child):
                    error(path + "." + key, "invalid HTTPS source URL")
                walk(child, path + "." + key, depth + 1)
        elif isinstance(value, list):
            if len(value) > 10000:
                error(path, "array exceeds 10000 elements")
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]", depth + 1)
        elif isinstance(value, float) and not math.isfinite(value):
            error(path, "non-finite value")
        elif isinstance(value, str) and (len(value) > 100000 or "\x00" in value):
            error(path, "oversized string or NUL")

    if not isinstance(data, dict):
        return {"valid": False, "errors": ["$: requires object"], "warnings": [], "layerCoverage": []}
    if type(data.get("schemaVersion")) is not int or data.get("schemaVersion") != 1:
        error("schemaVersion", "only schemaVersion 1 is supported")
    if not valid_civil_date(data.get("editorialReviewedAt")):
        error("editorialReviewedAt", "invalid review date")
    for key in REQUIRED_ARRAYS:
        if not isinstance(data.get(key), list):
            error(key, "required array missing")
    for key in REQUIRED_OBJECTS:
        if not isinstance(data.get(key), dict):
            error(key, "required object missing")
    if not isinstance(data.get("updatePolicy"), str):
        error("updatePolicy", "required string missing")
    if not isinstance(data.get("states"), dict) or set(data["states"]) != UF_CODES:
        error("states", "must contain exactly the 27 UF codes")
    else:
        for uf, name in data["states"].items():
            text(name, f"states.{uf}", 100)
    walk(data)

    lead = data.get("lead")
    if isinstance(lead, dict):
        text(lead.get("headline"), "lead.headline", 500)
        text(lead.get("summary"), "lead.summary", 15000)
    for section in ("mendonca", "democracy", "congressBalance", "pollAgenda"):
        card = data.get(section)
        if not isinstance(card, dict):
            continue
        for key in ("id", "headline", "summary", "kind", "limitations"):
            text(card.get(key), section + "." + key, 15000)
        sources(card.get("sources"), section + ".sources")
        for key in ("eventDate", "publicationDate"):
            if key in card and card[key] is not None and not valid_civil_date(card[key], partial=True):
                error(section + "." + key, "invalid date/precision")
    election = data.get("election")
    if isinstance(election, dict):
        if not safe_https(election.get("source")):
            error("election.source", "requires institutional HTTPS reference")
        candidates = election.get("candidates")
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= 100:
            error("election.candidates", "requires 1..100 attributed candidate records")
        else:
            for index, candidate in enumerate(candidates):
                path = f"election.candidates[{index}]"
                if not isinstance(candidate, dict):
                    error(path, "requires object")
                    continue
                text(candidate.get("name"), path + ".name", 300)
                percentage(candidate.get("percent"), path + ".percent")
                if "votes" in candidate:
                    count(candidate["votes"], path + ".votes")
    video = data.get("video")
    if isinstance(video, dict):
        for key in ("id", "title", "channel"):
            text(video.get(key), "video." + key, 500)
        if not safe_https(video.get("url")):
            error("video.url", "requires HTTPS reference")
        if video.get("date") is not None and not valid_civil_date(video["date"]):
            error("video.date", "invalid reference date")
    for index, rule in enumerate(data.get("editorialRules", []) if isinstance(data.get("editorialRules"), list) else []):
        text(rule, f"editorialRules[{index}]", 15000)

    for section in CARD_ARRAYS:
        seen = set()
        for index, card in enumerate(data.get(section, []) if isinstance(data.get(section), list) else []):
            path = f"{section}[{index}]"
            if not isinstance(card, dict):
                error(path, "requires card object")
                continue
            text(card.get("id"), path + ".id", 200)
            identifier = card.get("id")
            if isinstance(identifier, str):
                if identifier in seen:
                    error(path + ".id", "duplicate ID within section")
                seen.add(identifier)
            text(card.get("headline", card.get("title")), path + ".headline/title", 500)
            text(card.get("summary", card.get("facts")), path + ".summary/facts", 15000)
            text(card.get("kind"), path + ".kind", 200)
            if card.get("limitations") is None or card.get("limitations") == "":
                warnings.append(path + ": limitations are absent in this schema record; review before publication")
            else:
                text(card.get("limitations"), path + ".limitations", 15000)
            sources(card.get("sources"), path + ".sources")
            for date_key in ("eventDate", "date", "publicationDate", "publishedAt", "statusAsOf", "statusCheckedAt"):
                if date_key in card and card[date_key] is not None and not valid_civil_date(card[date_key], partial=True):
                    error(path + "." + date_key, "invalid date/precision")
            for geo_key in ("uf", "geography"):
                if geo_key in card and (not isinstance(card[geo_key], str) or card[geo_key] not in UF_CODES | {"BR", "INT", "international"}):
                    error(path + "." + geo_key, "unknown geography")
            if "ufs" in card and (not isinstance(card["ufs"], list) or any(not isinstance(uf, str) or uf not in UF_CODES for uf in card["ufs"])):
                error(path + ".ufs", "requires array of known UFs")
            if "includeInIncidentTotal" in card and type(card["includeInIncidentTotal"]) is not bool:
                error(path + ".includeInIncidentTotal", "requires boolean")

    layer_ids = set()
    for index, layer in enumerate(data.get("layers", []) if isinstance(data.get("layers"), list) else []):
        path = f"layers[{index}]"
        if not isinstance(layer, dict):
            error(path, "requires object")
            continue
        for key in ("id", "title", "publisher", "unit", "period", "note"):
            text(layer.get(key), path + "." + key)
        identifier = layer.get("id")
        if isinstance(identifier, str):
            if identifier in layer_ids:
                error(path + ".id", "duplicate layer")
            layer_ids.add(identifier)
        count(layer.get("total"), path + ".total")
        if not safe_https(layer.get("source")):
            error(path + ".source", "invalid source URL")
        by_uf = layer.get("byUf")
        if not isinstance(by_uf, dict) or set(by_uf) != UF_CODES:
            error(path + ".byUf", "requires all 27 UFs, preserving missing values as null")
            continue
        known = {}
        for uf, value in by_uf.items():
            if value is not None:
                count(value, path + ".byUf." + uf)
                if type(value) is int and value >= 0:
                    known[uf] = value
        known_sum = sum(known.values())
        if type(layer.get("total")) is int and known_sum > layer["total"]:
            error(path + ".total", "known UF subtotal exceeds published total")
        coverage.append({"id": identifier, "unit": layer.get("unit"), "period": layer.get("period"),
                         "publishedTotal": layer.get("total"), "knownUfSubtotal": known_sum,
                         "numericUfCount": len(known), "nullUfCount": sum(value is None for value in by_uf.values())})
    # No sum across layers: their periods, units and methods differ.

    for index, poll in enumerate(data.get("polls", []) if isinstance(data.get("polls"), list) else []):
        path = f"polls[{index}]"
        if not isinstance(poll, dict):
            error(path, "requires object")
            continue
        for key in ("id", "institute", "method", "population", "registration", "scope"):
            text(poll.get(key), path + "." + key, 1000)
        if not isinstance(poll.get("scope"), str) or poll["scope"] not in UF_CODES | {"BR"}:
            error(path + ".scope", "unknown scope")
        for key in ("publicationDate", "fieldStart", "fieldEnd"):
            if not isinstance(poll.get(key), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", poll[key]) or not valid_civil_date(poll[key]):
                error(path + "." + key, "requires valid civil date YYYY-MM-DD, not timestamp")
        if all(isinstance(poll.get(key), str) for key in ("fieldStart", "fieldEnd", "publicationDate")):
            if not poll["fieldStart"] <= poll["fieldEnd"] <= poll["publicationDate"]:
                error(path, "fieldwork must end no later than publication")
        count(poll.get("sample"), path + ".sample")
        if poll.get("sample") == 0:
            error(path + ".sample", "sample must be positive")
        percentage(poll.get("marginOfErrorPP"), path + ".marginOfErrorPP")
        percentage(poll.get("confidencePercent"), path + ".confidencePercent")
        if poll.get("confidencePercent") == 0:
            error(path + ".confidencePercent", "confidence must be positive")
        if not safe_https(poll.get("source")):
            error(path + ".source", "invalid HTTPS source")
        registration = poll.get("registration")
        if not isinstance(registration, str) or not re.fullmatch(r"(?:BR|" + "|".join(sorted(UF_CODES)) + r")-\d{5}/\d{4}", registration):
            error(path + ".registration", "requires reported BR/UF registry code; validity is not certified")
        scenarios = poll.get("scenarios")
        if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 30:
            error(path + ".scenarios", "requires 1..30 scenarios")
            continue
        for number, scenario in enumerate(scenarios):
            key = f"{path}.scenarios[{number}]"
            if not isinstance(scenario, dict):
                error(key, "requires object")
                continue
            if type(scenario.get("round")) is not int or scenario["round"] not in (1, 2):
                error(key + ".round", "requires round 1 or 2")
            if scenario.get("denominator") not in ("total", "valid"):
                error(key + ".denominator", "total/valid must be explicit")
            text(scenario.get("type"), key + ".type", 100)
            candidates = scenario.get("candidates")
            if not isinstance(candidates, list) or not candidates:
                error(key + ".candidates", "requires candidates")
                continue
            for number, candidate in enumerate(candidates):
                location = f"{key}.candidates[{number}]"
                if not isinstance(candidate, dict):
                    error(location, "requires object")
                    continue
                text(candidate.get("name"), location + ".name", 300)
                percentage(candidate.get("percent"), location + ".percent")
        # Do not sum candidates: multi-seat/multiple-response scenarios may differ.

    for index, source in enumerate(data.get("sourceDirectory", []) if isinstance(data.get("sourceDirectory"), list) else []):
        path = f"sourceDirectory[{index}]"
        if not isinstance(source, dict):
            error(path, "requires object")
            continue
        text(source.get("name"), path + ".name", 500)
        text(source.get("note"), path + ".note", 5000)
        if not safe_https(source.get("url")):
            error(path + ".url", "invalid HTTPS URL")

    for index, record in enumerate(data.get("liveStreams", []) if isinstance(data.get("liveStreams"), list) else []):
        path = f"liveStreams[{index}]"
        if not isinstance(record, dict):
            error(path, "requires object")
            continue
        text(record.get("id"), path + ".id", 200)
        if record.get("state") not in ("scheduled", "replay", "live", "unknown", "offline", "reference"):
            error(path + ".state", "unknown state")
        if record.get("state") == "live":
            proof = record.get("verification")
            if not isinstance(proof, dict) or proof.get("method") != "public_broadcast_status" or proof.get("isLive") is not True:
                error(path + ".verification", "live requires explicit broadcast proof")
                continue
            try:
                checked = parse_instant(proof.get("checkedAt"))
                url = urlsplit(proof.get("source", ""))
                video_id = url.path.removeprefix("/live/") if url.path.startswith("/live/") else parse_qs(url.query).get("v", [None])[0] if url.path == "/watch" else None
                if not safe_https(proof.get("source")) or url.hostname not in ("youtube.com", "www.youtube.com") or not re.fullmatch(r"[\w-]{11}", str(video_id)) or video_id != record.get("videoId"):
                    error(path + ".verification.source", "proof must identify the exact YouTube video")
                age = (now - checked).total_seconds()
                if age < 0 or age > 300:
                    warnings.append(path + ": live proof is outside the 5-minute window; frontend must show unknown/reference")
            except (ValueError, TypeError):
                error(path + ".verification", "invalid timestamp or source")

    graph = data.get("networkGraph")
    if graph is not None:
        if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
            error("networkGraph", "requires nodes and edges arrays")
        else:
            if len(graph["nodes"]) > 60 or len(graph["edges"]) > 120:
                error("networkGraph", "maximum 60 nodes and 120 edges")
            ids = set()
            for kind in ("nodes", "edges"):
                for index, record in enumerate(graph[kind]):
                    path = f"networkGraph.{kind}[{index}]"
                    if not isinstance(record, dict):
                        error(path, "requires object")
                        continue
                    text(record.get("label"), path + ".label", 160 if kind == "nodes" else 180)
                    if not isinstance(record.get("status"), str) or record["status"] not in GRAPH_STATUSES:
                        error(path + ".status", "requires attributed/documented graph status")
                    status_date = record.get("statusAsOf")
                    if not isinstance(status_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", status_date) or not valid_civil_date(status_date):
                        error(path + ".statusAsOf", "requires status date")
                    sources(record.get("sources"), path + ".sources")
                    if isinstance(record.get("sources"), list):
                        for source_index, graph_source in enumerate(record["sources"]):
                            if not isinstance(graph_source, dict):
                                continue
                            source_path = f"{path}.sources[{source_index}]"
                            if graph_source.get("title") is not None:
                                text(graph_source["title"], source_path + ".title", 160)
                            source_date = graph_source.get("date")
                            if source_date is not None and (not isinstance(source_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", source_date) or not valid_civil_date(source_date)):
                                error(source_path + ".date", "requires civil date YYYY-MM-DD")
                    if kind == "nodes":
                        text(record.get("id"), path + ".id", 64)
                        text(record.get("categoria"), path + ".categoria", 80)
                        identifier = record.get("id")
                        if isinstance(identifier, str):
                            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", identifier):
                                error(path + ".id", "requires browser-compatible node ID")
                            if identifier in ids:
                                error(path + ".id", "duplicate node ID")
                            ids.add(identifier)
                        if "foto" not in record or record["foto"] is not None and not safe_https(record["foto"]):
                            error(path + ".foto", "requires HTTPS URL or explicit null; no image downloaded")
            edge_keys = set()
            for index, edge in enumerate(graph["edges"]):
                if not isinstance(edge, dict):
                    continue
                path = f"networkGraph.edges[{index}]"
                event_date = edge.get("eventDate")
                if event_date is not None and (not isinstance(event_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date) or not valid_civil_date(event_date)):
                    error(path + ".eventDate", "requires civil date YYYY-MM-DD")
                if not isinstance(edge.get("source"), str) or not isinstance(edge.get("target"), str) or edge["source"] not in ids or edge["target"] not in ids:
                    error(path, "edge endpoints must reference existing nodes")
                if edge.get("source") == edge.get("target"):
                    error(path, "self-relation requires another explicit contract")
                key = tuple(str(edge.get(field)) for field in ("source", "target", "label"))
                if key in edge_keys:
                    error(path, "duplicate directed relation")
                edge_keys.add(key)
            warnings.append("networkGraph: validation checks provenance structure, not truth, guilt, photo rights or causal relationships")

    for index, metric in enumerate(data.get("rightsMetrics", []) if isinstance(data.get("rightsMetrics"), list) else []):
        path = f"rightsMetrics[{index}]"
        if not isinstance(metric, dict):
            error(path, "requires object")
            continue
        count(metric.get("value"), path + ".value")
        text(metric.get("label"), path + ".label", 500)
        text(metric.get("note"), path + ".note", 5000)
        if not safe_https(metric.get("source")):
            error(path + ".source", "invalid HTTPS source")

    for index, comparison in enumerate(data.get("programComparison", []) if isinstance(data.get("programComparison"), list) else []):
        path = f"programComparison[{index}]"
        if not isinstance(comparison, dict):
            error(path, "requires object")
            continue
        for key in ("candidate", "plan", "comparison"):
            text(comparison.get(key), path + "." + key, 15000)
        if not safe_https(comparison.get("source")):
            error(path + ".source", "invalid HTTPS source")
        if comparison.get("speechSource") is not None and not safe_https(comparison["speechSource"]):
            error(path + ".speechSource", "invalid HTTPS source")
    # Nested campaign.comparison.speechSource is a source label in v34, not a URL.

    return {"valid": not errors, "schemaVersion": data.get("schemaVersion"), "checkedAt": iso_z(now),
            "errors": errors, "warnings": warnings, "layerCoverage": coverage,
            "limitations": "Structural validation only; no factual verification, URL fetch, editorial rewrite or cross-layer total."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_data(load_json(args.data))
        if args.report:
            atomic_json(args.report, result, args.data)
    except (ValueError, OSError, UnicodeError, RecursionError) as exception:
        result = {"valid": False, "errors": [str(exception)], "warnings": []}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
