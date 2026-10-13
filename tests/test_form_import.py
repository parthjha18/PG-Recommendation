"""
Run:  ml-service/venv/bin/python -m unittest tests.test_form_import -v

Fully offline: location lookups are stubbed. The fixture rows are TEST DATA
(one is the co-partner's sample entry with a placeholder Maps link) and are
never loaded by the app.
"""
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.form_import import (  # noqa: E402
    build_real_dataset, coords_from_text, parse_curfew, parse_rent, REAL_ID_BASE,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "form_responses_sample.csv")


def fake_resolver(maps_url, address):
    from src.form_import import coords_from_text as c
    hit = c(maps_url)
    return {"lat": hit[0], "lon": hit[1], "how": "test"} if hit else None


class ParserTests(unittest.TestCase):
    def test_coords_from_various_maps_urls(self):
        self.assertEqual(coords_from_text("https://www.google.com/maps/place/X/@13.0382,77.5919,17z"), (13.0382, 77.5919))
        self.assertEqual(coords_from_text("https://maps.google.com/?q=13.035,77.597"), (13.035, 77.597))
        self.assertEqual(coords_from_text("https://x/data=!3d12.9697!4d77.7499"), (12.9697, 77.7499))
        self.assertIsNone(coords_from_text("https://maps.app.goo.gl/abc123"))
        self.assertIsNone(coords_from_text("https://www.google.com/maps?q=1.0,2.0"))   # not in India

    def test_rent(self):
        self.assertEqual(parse_rent("₹10,000"), 10000)
        self.assertEqual(parse_rent("8000"), 8000)
        self.assertIsNone(parse_rent(""))
        self.assertIsNone(parse_rent("Not available"))
        self.assertIsNone(parse_rent(float("nan")))

    def test_curfew(self):
        self.assertEqual(parse_curfew("11 PM"), "11:00 PM")
        self.assertEqual(parse_curfew("9 PM"), "9:00 PM")
        self.assertEqual(parse_curfew("No curfew"), "No Curfew")
        self.assertEqual(parse_curfew("10:30 PM"), "10:00 PM")
        self.assertEqual(parse_curfew("8 PM"), "9:00 PM")
        self.assertIsNone(parse_curfew(""))
        self.assertIsNone(parse_curfew("whenever"))


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        responses = pd.read_csv(FIXTURE, dtype=str)
        cls.out, cls.warnings = build_real_dataset(
            responses, dayfirst=True, resolver=fake_resolver, locality_lookup=lambda a, b: "brookefield")

    def test_one_row_per_sharing_type(self):
        girls = self.out[self.out["PG_Name"].str.startswith("Sri Lakshmi")]
        self.assertEqual(sorted(girls["Sharing"]), ["Double", "Triple"])
        self.assertEqual(sorted(girls["Rent"]), [8000, 10000])
        edge = self.out[self.out["PG_Name"].str.startswith("TEST")]
        self.assertEqual(sorted(edge["Sharing"]), ["Quad", "Single"])   # blank rents skipped

    def test_ids_are_in_real_range_and_unique(self):
        self.assertTrue((self.out["PG_ID"] > REAL_ID_BASE).all())
        self.assertTrue(self.out["PG_ID"].is_unique)

    def test_values_mapped_to_dataset_schema(self):
        r = self.out[(self.out["PG_Name"].str.startswith("Sri")) & (self.out["Sharing"] == "Double")].iloc[0]
        self.assertEqual(r["Gender"], "Girls")
        self.assertEqual(r["Meals_Per_Day"], 3)
        self.assertEqual((r["WiFi"], r["AC"], r["Laundry"], r["Security"], r["CCTV"]), ("Yes", "No", "Yes", "No", "Yes"))
        self.assertEqual((r["Pets_Allowed"], r["Visitors_Allowed"]), ("No", "No"))
        self.assertEqual(r["Curfew_Time"], "11:00 PM")
        self.assertEqual(r["Floors"], 6)
        self.assertEqual(r["Location"], "brookefield")        # 'Other' area -> looked up
        self.assertEqual(r["Food_Type"], "Both")
        self.assertEqual(r["Weekend_Food"], "Yes")

    def test_availability_is_per_sharing_type(self):
        girls = self.out[self.out["PG_Name"].str.startswith("Sri")].set_index("Sharing")
        self.assertEqual(girls.loc["Double", "Availability"], "Available")
        self.assertEqual(girls.loc["Triple", "Availability"], "Available")
        edge = self.out[self.out["PG_Name"].str.startswith("TEST")]
        self.assertTrue((edge["Availability"] == "Full").all())

    def test_edge_case_row(self):
        r = self.out[self.out["PG_Name"].str.startswith("TEST")].iloc[0]
        self.assertEqual(r["Location"], "hebbal")             # dropdown value lower-cased
        self.assertEqual(r["Curfew_Time"], "10:00 PM")        # 10:30 PM -> nearest modelled bucket
        self.assertEqual(r["Available_From"], "2026-11-20")   # DD/MM/YYYY parsed
        self.assertEqual(r["Meals_Per_Day"], 0)
        self.assertLess(r["Distance_From_Center_KM"], 1.0)    # ~Hebbal centre

    def test_unresolvable_location_is_skipped_not_guessed(self):
        responses = pd.read_csv(FIXTURE, dtype=str)
        out, warns = build_real_dataset(responses, resolver=lambda u, a: None,
                                        locality_lookup=lambda a, b: "x")
        self.assertTrue(out.empty)
        self.assertEqual(sum("SKIPPED" in w for w in warns), 2)

    def test_missing_columns_raise(self):
        with self.assertRaises(ValueError):
            build_real_dataset(pd.DataFrame({"PG Name": ["x"]}))


if __name__ == "__main__":
    unittest.main()
