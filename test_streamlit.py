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
        self.assertEqual([m.value for m in self.app.metric][:3], ["1,522", "1,358", "164"])
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
        from streamlit_app import county_table, map_svg, county_names
        result = self.app.session_state.result
        frame = county_table(result)
        self.assertEqual(int(frame.reached_at_horizon.sum()), result["reached"])
        self.assertEqual(int(frame.added_at_horizon.sum()), result["added"])
        root = ET.fromstring(map_svg(result, 20))
        paths = list(root.iter("{http://www.w3.org/2000/svg}path"))
        self.assertEqual(len(paths), len(county_names()))
        self.assertEqual(sum(p.attrib["fill"] == "#a94932" for p in paths), 2)


if __name__ == "__main__":
    unittest.main()
