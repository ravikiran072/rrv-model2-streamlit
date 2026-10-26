"""Streamlit interaction checks: python -m unittest -v test_streamlit.py."""
import json
import os
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class StreamlitTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"RRV_DB": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = AppTest.from_file("streamlit_app.py", default_timeout=60).run()
        self.assertFalse(self.app.exception)

    def widget(self, kind, label):
        return next(x for x in getattr(self.app, kind) if x.label == label)

    def apply(self):
        self.widget("button", "Apply scenario").click().run()
        self.assertFalse(self.app.exception)

    def test_default_map_year_and_county_selection(self):
        self.assertEqual([m.value for m in self.app.metric], ["2,006", "1,917", "89", "5"])
        original = self.app.session_state.result
        self.widget("slider", "Map year").set_value(0).run()
        self.assertEqual(self.app.metric[2].value, "0")
        self.assertEqual(self.app.session_state.result, original)
        self.widget("selectbox", "Inspect a county").select(149).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.dataframe[0].value.iloc[0]["name"], "Pulaski County")

    def test_applied_scenarios_invalid_input_and_speed_mode(self):
        self.widget("number_input", "Detected transported rabid raccoons / year").set_value(0.)
        self.apply()
        self.assertEqual(self.app.metric[2].value, "0")
        self.widget("number_input", "Detected transported rabid raccoons / year").set_value(20.)
        self.widget("number_input", "Detection probability (%)").set_value(.01)
        self.apply()
        self.assertTrue(self.app.error)
        self.assertEqual(self.app.session_state.result["inputs"]["observed_per_year"], 0.)
        self.widget("number_input", "Detected transported rabid raccoons / year").set_value(.2)
        self.widget("number_input", "Detection probability (%)").set_value(1.)
        self.widget("number_input", "High habitat (miles/year)").set_value(40.)
        self.widget("slider", "Horizon (years)").set_value(5)
        self.apply()
        self.assertEqual(self.app.session_state.result["inputs"]["landscape_mode"], "rebuild")
        self.assertEqual(self.widget("slider", "Map year").value, 5)
        self.assertFalse(self.app.error)

    def test_expert_response_download_and_storage(self):
        self.widget("button", "Prepare response").click().run()
        self.assertTrue(self.app.error)
        self.app.session_state["expert_estimates"] = {"edited_rows": {0: {"central": "5", "evidence": "Expert estimate"}}, "added_rows": [], "deleted_rows": []}
        self.widget("button", "Prepare response").click().run()
        self.assertFalse(self.app.exception)
        payload = self.app.session_state.expert_response
        self.assertEqual(payload["inputs"]["observed_event_interval"]["central"], "5")
        from streamlit_app import save_expert
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "expert.sqlite3"
            self.assertEqual(save_expert(payload, path), 1)
            with closing(sqlite3.connect(path)) as con:
                saved = json.loads(con.execute("SELECT inputs_json FROM submissions").fetchone()[0])
            self.assertEqual(saved, payload["inputs"])

    def test_map_and_county_download_consistency(self):
        import base64
        from streamlit_app import county_table, map_svg, county_names
        result = self.app.session_state.result
        frame = county_table(result)
        self.assertEqual(int(frame.reached_at_horizon.sum()), result["reached"])
        self.assertEqual(int(frame.added_at_horizon.sum()), result["added"])
        root = ET.fromstring(map_svg(result, 20))
        paths = list(root.iter("{http://www.w3.org/2000/svg}path"))
        self.assertEqual(sum("data-i" in p.attrib for p in paths), len(county_names()))
        self.assertGreater(sum("data-i" not in p.attrib for p in paths), 0)
        self.assertEqual(len(list(root.iter("{http://www.w3.org/2000/svg}polygon"))), 5)
        # Check the actual UI output, since valid SVG alone cannot catch HTML
        # sanitization removing a map in the visitor's browser.
        images = self.app.get("imgs")
        self.assertEqual(len(images), 1)
        url = images[0].proto.imgs[0].url
        self.assertTrue(url.startswith("data:image/svg+xml;base64,"))
        displayed = ET.fromstring(base64.b64decode(url.split(",", 1)[1]))
        self.assertEqual(len(list(displayed.iter("{http://www.w3.org/2000/svg}path"))), len(paths))

    def test_feedback_controls_and_analytic_mode(self):
        self.widget("checkbox", "Scale transports with county burden").uncheck()
        self.widget("checkbox", "Earlier nidi become transport origins").uncheck()
        self.apply()
        self.assertEqual([m.value for m in self.app.metric][:3], ["1,935", "1,917", "18"])
        self.assertTrue(all(a["annual_infectious_transport_mean"] == 20 for a in self.app.session_state.result["annual"]))
        self.widget("checkbox", "Scale transports with county burden").check()
        self.widget("checkbox", "Earlier nidi become transport origins").check()
        self.widget("selectbox", "Calculation").select("analytic")
        self.apply()
        self.assertEqual([m.value for m in self.app.metric][:3], ["2,014", "1,917", "97"])

    def test_accepted_map_attribution_shading_and_year_probabilities(self):
        from streamlit_app import source_code, shade, county_table, SOURCE_COLORS
        result = self.app.session_state.result
        counts = [sum(source_code(result, i, 20) == code for i in range(len(result["arrival"]))) for code in range(4)]
        self.assertEqual(counts, [1090, 877, 815, 314])
        for code, color in enumerate(SOURCE_COLORS):
            self.assertEqual(shade(code, 0), "#ffffff")
            self.assertEqual(shade(code, 1), color)
        self.assertEqual(source_code(result, 149, 8), 0)
        self.assertEqual(source_code(result, 149, 9), 3)
        frame = county_table(result, 9)
        self.assertEqual(frame.iloc[149].delivery_probability_by_map_year, result["receipt_probability_history"][8][149])
        self.assertEqual(int(frame.additional_at_map_year.sum()), result["annual"][8]["added"])
        self.assertTrue((county_table(result, 0).delivery_probability_by_map_year == 0).all())
        self.widget("slider", "Map year").set_value(9).run()
        self.widget("selectbox", "Inspect a county").select(149).run()
        self.assertFalse(self.app.exception)
        displayed = self.app.dataframe[0].value.iloc[0]
        self.assertEqual(displayed.delivery_probability_by_map_year, result["receipt_probability_history"][8][149])


if __name__ == "__main__":
    unittest.main()
