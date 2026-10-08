"""Offline fixtures are technical test data, never political claims or news output."""
import copy
import datetime as dt
from email.message import Message
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "automation"))
import collect_headlines as collector
import validate_observatory as validator

NOW = dt.datetime(2026, 10, 8, 12, tzinfo=dt.timezone.utc)


def seed():
    """Minimal structural fixture; no real person, invented politician or event."""
    data = {key: [] for key in validator.REQUIRED_ARRAYS}
    data.update({key: {} for key in validator.REQUIRED_OBJECTS})
    data.update(schemaVersion=1, editorialReviewedAt="2026-10-08", updatePolicy="Technical fixture only",
                states={uf: uf for uf in validator.UF_CODES})
    data["lead"] = {"headline": "Technical fixture", "summary": "Not an event or political claim"}
    for section in ("mendonca", "democracy", "congressBalance", "pollAgenda"):
        data[section] = {"id": "fixture", "headline": "Technical fixture", "summary": "Not a claim",
                         "kind": "fixture", "limitations": "No factual content", "sources": [{"url": "https://example.org/fixture", "publisher": "Fixture"}]}
    data["election"] = {"source": "https://example.org/fixture", "candidates": [{"name": "Technical fixture field", "percent": 0, "votes": 0}]}
    data["video"] = {"id": "fixture0000", "title": "Technical fixture", "channel": "Fixture", "url": "https://example.org/fixture"}
    data["layers"] = [{"id": "fixture", "title": "Fixture", "publisher": "Fixture", "unit": "technical values",
                       "period": "fixture only", "note": "Not factual data", "total": 3,
                       "source": "https://example.org/fixture", "byUf": dict.fromkeys(validator.UF_CODES)}]
    data["layers"][0]["byUf"].update(SP=3, TO=0)
    return data


def graph():
    provenance = {"status": "declaracao_atribuida", "statusAsOf": "2026-10-08",
                  "sources": [{"url": "https://example.org/fixture", "publisher": "Technical fixture"}]}
    return {"nodes": [dict(provenance, id="fixture-a", label="Fixture A", categoria="fixture", foto=None),
                      dict(provenance, id="fixture-b", label="Fixture B", categoria="fixture", foto=None)],
            "edges": [dict(provenance, source="fixture-a", target="fixture-b", label="Technical relation; no actual allegation")]}


def rss_item(title="Eleição (fixture técnica, não publicar)", link=None, date="Thu, 08 Oct 2026 10:00:00 +0000"):
    link = link or "https://agenciabrasil.ebc.com.br/politica/noticia/2026-10/fixture"
    return f"<item><title><![CDATA[{title}]]></title><link>{link.replace('&', '&amp;')}</link><pubDate>{date}</pubDate></item>"


def rss(*items):
    return ("<rss version='2.0'><channel>" + "".join(items) + "</channel></rss>").encode()


class FakeResponse:
    status = 200

    def __init__(self, payload, url, headers=None):
        self.buffer = io.BytesIO(payload)
        self.url = url
        self.headers = Message()
        self.headers["Content-Type"] = "application/rss+xml"
        for key, value in (headers or {}).items():
            self.headers[key] = value

    def geturl(self):
        return self.url

    def read(self, size):
        return self.buffer.read(size)

    read1 = read

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.buffer.close()


class FakeOpener:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        return self.response


class ValidatorTests(unittest.TestCase):
    def test_core_objects_and_poll_denominator_cannot_be_empty(self):
        data = seed()
        data["lead"] = {}
        self.assertFalse(validator.validate_data(data, NOW)["valid"])
        data = seed()
        data["polls"] = [{"id": "fixture", "institute": "Technical fixture", "method": "Fixture",
                          "population": "Fixture", "registration": "BR-00000/2026", "scope": "BR",
                          "publicationDate": "2026-10-08", "fieldStart": "2026-10-07", "fieldEnd": "2026-10-08",
                          "sample": 1, "marginOfErrorPP": 0, "confidencePercent": 95,
                          "source": "https://example.org/fixture", "scenarios": [{"round": 2, "denominator": "total", "type": "fixture", "candidates": [{"name": "Technical fixture field", "percent": 0}]}]}]
        self.assertTrue(validator.validate_data(data, NOW)["valid"])
        for mutation in (lambda poll: poll["scenarios"][0].update(denominator="unknown"),
                         lambda poll: poll.update(confidencePercent=0),
                         lambda poll: poll.update(source=None),
                         lambda poll: poll["scenarios"][0]["candidates"][0].update(percent=float("inf")),
                         lambda poll: poll["scenarios"][0]["candidates"][0].update(percent=10**400),
                         lambda poll: poll.update(fieldStart="2026-10-08T12:00:00+00:00", fieldEnd="2026-10-08T13:00:00+03:00", publicationDate="2026-10-08T14:00:00+00:00")):
            broken = copy.deepcopy(data)
            mutation(broken["polls"][0])
            self.assertFalse(validator.validate_data(broken, NOW)["valid"])

    def test_nulls_zero_subtotals_and_input_are_preserved(self):
        data = seed()
        original = copy.deepcopy(data)
        result = validator.validate_data(data, NOW)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(data, original)
        self.assertEqual(result["layerCoverage"][0]["nullUfCount"], 25)
        self.assertEqual(result["layerCoverage"][0]["knownUfSubtotal"], 3)
        self.assertEqual(data["layers"][0]["byUf"]["TO"], 0)
        self.assertIsNone(data["layers"][0]["byUf"]["BA"])
        self.assertNotIn("combinedTotal", result)

    def test_missing_uf_boolean_or_underreported_total_fail(self):
        for mutation in (lambda item: item["byUf"].pop("BA"),
                         lambda item: item["byUf"].update(BA=True),
                         lambda item: item.update(total=2)):
            with self.subTest(mutation=mutation):
                data = seed()
                mutation(data["layers"][0])
                self.assertFalse(validator.validate_data(data, NOW)["valid"])

    def test_graph_requires_sources_status_and_valid_endpoints(self):
        data = seed()
        data["networkGraph"] = graph()
        self.assertTrue(validator.validate_data(data, NOW)["valid"])
        for key, value in (("target", "missing"), ("source", ["fixture-a"]), ("sources", []), ("status", "guilty"),
                           ("statusAsOf", "2026-10-08T12:00:00Z"), ("eventDate", "2026-02-30")):
            with self.subTest(key=key):
                broken = copy.deepcopy(data)
                broken["networkGraph"]["edges"][0][key] = value
                self.assertFalse(validator.validate_data(broken, NOW)["valid"])

    def test_graph_duplicate_ids_and_unsafe_photos_fail(self):
        for mutation in (lambda item: item["nodes"][1].update(id="fixture-a"),
                         lambda item: item["nodes"][0].update(foto="javascript:alert(1)")):
            data = seed()
            data["networkGraph"] = graph()
            mutation(data["networkGraph"])
            self.assertFalse(validator.validate_data(data, NOW)["valid"])

    def test_graph_limit_matches_browser_capacity(self):
        data = seed()
        data["networkGraph"] = graph()
        node = data["networkGraph"]["nodes"][0]
        data["networkGraph"]["nodes"] = [dict(node, id=f"fixture-{index}") for index in range(60)]
        edge = data["networkGraph"]["edges"][0]
        data["networkGraph"]["edges"] = []
        for index in range(120):
            source, target = index // 59, index % 59
            if target >= source:
                target += 1
            data["networkGraph"]["edges"].append(dict(edge, source=f"fixture-{source}", target=f"fixture-{target}"))
        self.assertTrue(validator.validate_data(data, NOW)["valid"])
        data["networkGraph"]["nodes"].append(dict(node, id="fixture-60"))
        self.assertFalse(validator.validate_data(data, NOW)["valid"])
        data["networkGraph"]["nodes"].pop()
        data["networkGraph"]["edges"].append(dict(edge, source="fixture-2", target="fixture-3"))
        self.assertFalse(validator.validate_data(data, NOW)["valid"])

    def test_live_requires_exact_proof_and_stale_proof_warns(self):
        data = seed()
        record = {"id": "fixture", "state": "live", "videoId": "abcdefghijk", "verification": None}
        data["liveStreams"] = [record]
        self.assertFalse(validator.validate_data(data, NOW)["valid"])
        record["verification"] = {"method": "public_broadcast_status", "isLive": True,
                                  "source": "https://www.youtube.com/watch?v=abcdefghijk", "checkedAt": "2026-10-08T11:50:00Z"}
        result = validator.validate_data(data, NOW)
        self.assertTrue(result["valid"])
        self.assertTrue(any("5-minute" in warning for warning in result["warnings"]))
        record["verification"]["source"] = "https://www.youtube.com/watch?v=xxxxxxxxxxx"
        self.assertFalse(validator.validate_data(data, NOW)["valid"])

    def test_duplicate_json_keys_and_nonfinite_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "seed.json"
            for payload in ('{"schemaVersion":1,"schemaVersion":2}', '{"value":NaN}'):
                path.write_text(payload, encoding="utf-8")
                with self.assertRaises(ValueError):
                    validator.load_json(path)

    def test_report_cannot_overwrite_editorial_input(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "seed.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                validator.atomic_json(path, {"modified": True}, path)
            self.assertEqual(path.read_text(), "{}")


class CollectionTests(unittest.TestCase):
    def test_metadata_dates_origin_and_no_map_or_editorial_mutation(self):
        items, rejected = collector.parse_feed(rss(rss_item()), collector.FEEDS[0], NOW)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["publishedAt"], "2026-10-08T10:00:00Z")
        self.assertEqual(items[0]["origins"][0]["feedUrl"], collector.FEEDS[0]["url"])
        self.assertEqual(items[0]["ufs"], [])
        self.assertFalse(items[0]["includeInIncidentTotal"])
        self.assertEqual(items[0]["editorialStatus"], "pending_review")

    def test_mega_sena_is_excluded_from_latest_feed(self):
        items, rejected = collector.parse_feed(rss(rss_item("Mega-Sena (fixture técnica, não notícia)"), rss_item()), collector.FEEDS[2], NOW)
        self.assertEqual(len(items), 1)
        self.assertEqual(rejected["irrelevant"], 1)

    def test_unsafe_urls_invalid_old_future_or_naive_dates_are_rejected(self):
        payload = rss(rss_item(link="https://agenciabrasil.ebc.com.br.evil.test/noticia/x"),
                      rss_item(link="https://user:password@agenciabrasil.ebc.com.br/politica/noticia/x"),
                      rss_item(date="Wed, 30 Sep 2026 10:00:00 +0000"),
                      rss_item(date="Fri, 09 Oct 2026 10:00:00 +0000"),
                      rss_item(date="invalid"), rss_item(date="Thu, 08 Oct 2026 10:00:00"))
        items, rejected = collector.parse_feed(payload, collector.FEEDS[0], NOW)
        self.assertEqual(items, [])
        self.assertEqual(rejected, {"missing": 0, "url": 2, "date": 2, "window": 2, "irrelevant": 0})

    def test_dtd_entities_utf16_and_oversized_xml_are_rejected(self):
        for payload in (b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///secret">]><rss><channel/></rss>',
                        b'<rss><channel/></rss>'.decode().encode("utf-16"), b"x" * (collector.MAX_PAYLOAD_BYTES + 1)):
            with self.subTest(size=len(payload)):
                with self.assertRaises(collector.FeedError):
                    collector.parse_feed(payload, collector.FEEDS[0], NOW)

    def test_plain_text_strips_markup_and_script_without_rendering(self):
        items, _ = collector.parse_feed(rss(rss_item("<b>Eleição</b><script>do not emit</script> (fixture)")), collector.FEEDS[0], NOW)
        self.assertNotIn("<", items[0]["title"])
        self.assertNotIn("do not emit", items[0]["title"])

    def test_duplicate_article_merges_feed_origins_tracking_urls(self):
        first, _ = collector.parse_feed(rss(rss_item()), collector.FEEDS[0], NOW)
        second, _ = collector.parse_feed(rss(rss_item(link=first[0]["source"] + "?utm_source=fixture")), collector.FEEDS[2], NOW)
        result = collector.merge_items(first + second)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["origins"]), 2)
        self.assertEqual(len(result[0]["originalUrls"]), 2)

    def test_partial_and_integral_failure_are_explicit(self):
        def partial(feed):
            if feed["id"] == collector.FEEDS[0]["id"]:
                return rss(rss_item())
            raise TimeoutError("technical fixture")
        result = collector.collect(NOW, partial)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["items"]), 1)
        unavailable = collector.collect(NOW, lambda feed: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(unavailable["status"], "unavailable")
        self.assertEqual(unavailable["items"], [])
        self.assertTrue(all(state["checkedAt"] is None for state in unavailable["states"]))
        self.assertFalse(unavailable["published"])

    def test_cutoff_brt_and_offline_never_fetch(self):
        def forbidden(feed):
            self.fail("fetch must not run")
        for moment in (collector.WINDOW_START - dt.timedelta(seconds=1), collector.WINDOW_END, collector.WINDOW_END + dt.timedelta(days=366)):
            self.assertEqual(collector.collect(moment, forbidden)["status"], "skipped")
        self.assertEqual(collector.collect(NOW, forbidden, offline=True)["status"], "skipped")
        self.assertTrue(collector.window_open(collector.WINDOW_END - dt.timedelta(seconds=1)))

    def test_fetch_only_allowlist_and_limits_payload(self):
        with self.assertRaises(collector.FeedError):
            collector.fetch_feed(dict(collector.FEEDS[0], url="https://evil.test/rss"))
        response = FakeResponse(b"x", collector.FEEDS[0]["url"], {"Content-Length": str(collector.MAX_PAYLOAD_BYTES + 1)})
        with self.assertRaises(collector.FeedError):
            collector.fetch_feed(collector.FEEDS[0], FakeOpener(response))
        response = FakeResponse(b"x" * 41, collector.FEEDS[0]["url"])
        with patch.object(collector, "MAX_PAYLOAD_BYTES", 40), self.assertRaises(collector.FeedError):
            collector.fetch_feed(collector.FEEDS[0], FakeOpener(response))

    def test_redirect_compression_and_read_deadline_are_rejected(self):
        with self.assertRaises(collector.FeedError):
            collector.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.test/")
        response = FakeResponse(b"x", collector.FEEDS[0]["url"], {"Content-Encoding": "gzip"})
        with self.assertRaises(collector.FeedError):
            collector.fetch_feed(collector.FEEDS[0], FakeOpener(response))
        response = FakeResponse(b"x", collector.FEEDS[0]["url"])
        ticks = iter((0, 16))
        with self.assertRaises(collector.FeedError):
            collector.fetch_feed(collector.FEEDS[0], FakeOpener(response), lambda: next(ticks))

    def test_collection_cap_sort_and_atomic_draft_are_meaningful(self):
        payload = rss(*(rss_item(link=f"https://agenciabrasil.ebc.com.br/politica/noticia/2026-10/fixture-{index}") for index in range(60)))
        result = collector.collect(NOW, lambda feed: payload)
        self.assertEqual(len(result["items"]), collector.MAX_ITEMS)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "draft.json"
            validator.atomic_json(path, result)
            saved = validator.load_json(path)
            self.assertEqual(saved["items"], result["items"])
            self.assertFalse(saved["editorialSeedModified"])


if __name__ == "__main__":
    unittest.main()
