"""
Run:  ml-service/venv/bin/python -W ignore -m unittest tests.test_form_sync -v

Serves the fixture CSV from a throwaway local HTTP server (no internet) and
checks the sync behaviours that matter for a live, repeatedly-refreshed sheet.
"""
import functools
import http.server
import os
import shutil
import sys
import tempfile
import threading
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.form_import import CachedLocator  # noqa: E402
from src.form_sync import fetch_responses, sync_real_data  # noqa: E402
from tests.test_form_import import FIXTURE, fake_resolver  # noqa: E402


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        shutil.copy(FIXTURE, os.path.join(self.dir, "responses.csv"))
        with open(os.path.join(self.dir, "page.html"), "w") as f:
            f.write("<!DOCTYPE html><html><body>sign in</body></html>")
        handler = functools.partial(_Quiet, directory=self.dir)
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.out = os.path.join(self.dir, "real_pgs.csv")
        self.cache = os.path.join(self.dir, "cache.json")

    def tearDown(self):
        self.httpd.shutdown()
        shutil.rmtree(self.dir, ignore_errors=True)

    def locator(self):
        return CachedLocator(self.cache, resolver=fake_resolver, locality_lookup=lambda a, b: "brookefield")

    def test_sync_from_url_writes_dataset(self):
        r = sync_real_data(f"{self.base}/responses.csv", output=self.out, locator=self.locator())
        self.assertEqual((r["responses"], r["rows"], r["pgs"]), (2, 4, 2))
        self.assertEqual(len(pd.read_csv(self.out)), 4)

    def test_new_responses_appear_on_next_sync_and_old_ones_are_not_regeocoded(self):
        sync_real_data(f"{self.base}/responses.csv", output=self.out, locator=self.locator())

        # a friend submits a third response -> the sheet's CSV grows by one row
        df = pd.read_csv(FIXTURE, dtype=str)
        extra = df.iloc[[1]].copy()
        extra["PG Name"] = "Third PG"
        extra["Timestamp"] = "15/10/2026 10:00:00"
        extra["Google Maps Link"] = "https://www.google.com/maps/place/y/@13.0500,77.6400,17z"
        pd.concat([df, extra]).to_csv(os.path.join(self.dir, "responses.csv"), index=False)

        loc = self.locator()
        r = sync_real_data(f"{self.base}/responses.csv", output=self.out, locator=loc)
        self.assertEqual((r["responses"], r["pgs"]), (3, 3))
        self.assertEqual(loc.lookups, 1)     # only the NEW response was looked up (the 2 old ones came from cache)
        self.assertIn("Third PG", set(pd.read_csv(self.out)["PG_Name"]))

    def test_ids_stay_stable_when_responses_are_added(self):
        sync_real_data(f"{self.base}/responses.csv", output=self.out, locator=self.locator())
        before = pd.read_csv(self.out).set_index("PG_Name")["PG_ID"].to_dict()
        df = pd.read_csv(FIXTURE, dtype=str)
        extra = df.iloc[[1]].copy()
        extra["PG Name"], extra["Timestamp"] = "Later PG", "20/10/2026 10:00:00"
        pd.concat([df, extra]).to_csv(os.path.join(self.dir, "responses.csv"), index=False)
        sync_real_data(f"{self.base}/responses.csv", output=self.out, locator=self.locator())
        after = pd.read_csv(self.out).drop_duplicates("PG_Name").set_index("PG_Name")["PG_ID"].to_dict()
        for name in before:
            self.assertEqual(before[name] // 10, after[name] // 10)   # same response slot -> same ID

    def test_failed_download_keeps_last_good_data(self):
        sync_real_data(f"{self.base}/responses.csv", output=self.out, locator=self.locator())
        good = open(self.out).read()
        with self.assertRaises(Exception):
            sync_real_data(f"{self.base}/does-not-exist.csv", output=self.out, locator=self.locator())
        self.assertEqual(open(self.out).read(), good)

    def test_unusable_result_keeps_last_good_data(self):
        sync_real_data(f"{self.base}/responses.csv", output=self.out, locator=self.locator())
        good = open(self.out).read()
        nowhere = CachedLocator(None, resolver=lambda u, a: None, locality_lookup=lambda a, b: "x")
        with self.assertRaises(ValueError):
            sync_real_data(f"{self.base}/responses.csv", output=self.out, locator=nowhere)
        self.assertEqual(open(self.out).read(), good)

    def test_html_page_instead_of_csv_gives_a_helpful_error(self):
        with self.assertRaises(ValueError) as cm:
            fetch_responses(f"{self.base}/page.html")
        self.assertIn("Publish to web", str(cm.exception))

    def test_no_source_configured(self):
        old = os.environ.pop("FORM_RESPONSES_URL", None)
        try:
            from src import form_sync
            orig = form_sync.get_source
            form_sync.get_source = lambda: None
            with self.assertRaises(ValueError):
                sync_real_data(None, output=self.out)
        finally:
            form_sync.get_source = orig
            if old:
                os.environ["FORM_RESPONSES_URL"] = old


if __name__ == "__main__":
    unittest.main()
