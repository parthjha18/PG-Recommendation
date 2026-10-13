"""
Run:  ml-service/venv/bin/python -W ignore -m unittest tests.test_small_dataset -v

Guards the "real data is only a handful of PGs" case: a dataset where every
PG serves the same meals, and where min-max normalising a tiny pool would
otherwise score (and hide) the weakest PG as 0.
"""
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.form_import import build_real_dataset  # noqa: E402
from src.preprocessor import build_user_normalized, preprocess  # noqa: E402
from src.recommender import recommend  # noqa: E402
from tests.test_form_import import FIXTURE, fake_resolver  # noqa: E402


class SmallDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw, _ = build_real_dataset(pd.read_csv(FIXTURE, dtype=str), resolver=fake_resolver,
                                    locality_lookup=lambda a, b: "brookefield")
        cls.df, _ = preprocess(raw)

    def test_meals_use_fixed_scale_not_dataset_range(self):
        by_name = self.df.groupby("PG_Name")["Meals_Per_Day"].first()
        self.assertEqual(by_name["Sri Lakshmi Venkateshwara Girls PG"], 1.0)   # 3 meals
        self.assertEqual(by_name["TEST edge-case PG"], 0.0)                    # 0 meals -> clipped

    def test_weakest_pg_is_not_hidden_by_relevance_threshold(self):
        # Two different PGs where one clearly scores worse. Min-max over this
        # pool would score the weaker one 0.0 and the old >= 0.5 cut would drop it.
        raw, _ = build_real_dataset(pd.read_csv(FIXTURE, dtype=str), resolver=fake_resolver,
                                    locality_lookup=lambda a, b: "brookefield")
        girls = raw[raw["Sharing"] == "Double"].iloc[[0]].copy()
        better = girls.copy()
        better["PG_ID"] = 99999
        better["PG_Name"] = "Better-amenities copy"
        better["AC"] = "Yes"
        better["Laundry"] = "Yes"
        better["Sharing"] = "Triple"
        df, _ = preprocess(pd.concat([girls, better], ignore_index=True))

        user = {"budget": 12000, "gender": 1, "sharing": "Any", "meals": 3, "wifi": 1, "ac": 1, "laundry": 1}
        res = recommend(df, build_user_normalized(user), "", 12000.0, 1, sharing="Any")
        self.assertFalse(isinstance(res, str))
        self.assertEqual(len(res), 2)                       # both PGs returned
        self.assertEqual(int(res.iloc[0]["PG_ID"]), 99999)  # better one ranks first

    def test_single_row_pool_still_works(self):
        user = {"budget": 9000, "gender": 1, "sharing": "Triple", "meals": 3}
        res = recommend(self.df, build_user_normalized(user), "", 9000.0, 1, sharing="Triple")
        self.assertEqual(len(res), 1)
        self.assertEqual(int(res.iloc[0]["Original_Rent"]), 8000)


if __name__ == "__main__":
    unittest.main()
