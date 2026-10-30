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
        self.assertEqual([m.value for m in self.app.metric], ["2,003", "1,908", "95", "5"])
        original = self.app.session_state.result
        self.widget("slider", "Map year").set_value(0).run()
        self.assertEqual(self.app.metric[2].value, "0")
        self.assertEqual(self.app.session_state.result, original)
        self.widget("selectbox", "Inspect a county").select(149).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.dataframe[0].value.iloc[0]["name"], "Pulaski County")

    def test_old_result_schema_recovers_without_reboot(self):
        import copy
        # A previous imported engine can have produced old-schema results
        # stamped with the current revision during a live deployment.
        stale = copy.deepcopy(self.app.session_state.result)
        del stale["inputs"]["initial_annual_infectious_transports"]
        del stale["receipt_probability_history"]
        self.app.session_state.result = stale
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertIn("initial_annual_infectious_transports", self.app.session_state.result["inputs"])
        self.assertEqual(self.app.metric[0].value, "2,003")

    def test_cached_engine_is_reloaded_after_model_update(self):
        import model_engine
        with patch.object(model_engine, "run", side_effect=AssertionError("Old engine was retained")):
            with patch.object(model_engine, "_streamlit_revision", "previous-release"):
                # Changing an input ensures this exercises the calculation,
                # rather than returning a previously cached default scenario.
                self.widget("number_input", "Random seed").set_value(20261010)
                self.apply()
                self.assertEqual(self.app.session_state.result["inputs"]["random_seed"], 20261010)
                self.assertIn("initial_annual_infectious_transports", self.app.session_state.result["inputs"])

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
        self.widget("number_input", "High habitat (km/year)").set_value(40.)
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
        self.assertEqual(len(images), 2)
        url = images[0].proto.imgs[0].url
        self.assertTrue(url.startswith("data:image/svg+xml;base64,"))
        displayed = ET.fromstring(base64.b64decode(url.split(",", 1)[1]))
        self.assertEqual(len(list(displayed.iter("{http://www.w3.org/2000/svg}path"))), len(paths))

    def test_feedback_controls_and_analytic_mode(self):
        self.widget("checkbox", "Scale transports with county burden").uncheck()
        self.widget("checkbox", "Earlier nidi become transport origins").uncheck()
        self.apply()
        from model_engine import run
        reference = run({"scale_transport_with_burden": False, "include_nidi_as_origins": False})
        self.assertEqual(self.app.session_state.result["arrival"], reference["arrival"])
        self.assertTrue(all(a["annual_infectious_transport_mean"] == 20 for a in self.app.session_state.result["annual"]))
        self.widget("checkbox", "Scale transports with county burden").check()
        self.widget("checkbox", "Earlier nidi become transport origins").check()
        self.widget("selectbox", "Calculation").select("analytic")
        self.apply()
        self.assertEqual([m.value for m in self.app.metric][:3], ["2,003", "1,908", "95"])

    def test_accepted_map_attribution_shading_and_year_probabilities(self):
        from streamlit_app import source_code, shade, county_table, SOURCE_COLORS
        result = self.app.session_state.result
        counts = [sum(source_code(result, i, 20) == code for i in range(len(result["arrival"]))) for code in range(4)]
        self.assertEqual(counts, [1093, 877, 837, 289])
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

    def test_metric_speed_controls_and_export(self):
        import base64
        labels = ("No/very-low", "Low", "Moderate", "High")
        for label, default in zip(labels, (0., 16., 40., 80.)):
            widget = self.widget("number_input", f"{label} habitat (km/year)")
            self.assertEqual(widget.value, default)
            self.assertEqual((widget.proto.min, widget.proto.max, widget.proto.step), (0., 400., 2.))
        self.assertEqual(self.app.session_state.result["inputs"]["speed_unit"], "km/year")
        svg = base64.b64decode(self.app.get("imgs")[0].proto.imgs[0].url.split(",", 1)[1]).decode()
        self.assertIn("km/year", svg)
        self.widget("number_input", "Low habitat (km/year)").set_value(17.)
        self.apply()
        self.assertIn("multiples of 2 km/year", self.app.error[0].value)
        self.widget("number_input", "Low habitat (km/year)").set_value(18.)
        self.apply()
        self.assertFalse(self.app.error)
        self.assertEqual(self.app.session_state.result["inputs"]["speed_low"], 18.)

    def test_mean_distance_changes_distribution_and_routes(self):
        original = self.app.session_state.result
        self.assertEqual(original["inputs"]["mean_transport_km"], 2268.)
        self.assertFalse(any(x.label == "Long-haul share (%)" for x in self.app.slider))
        self.widget("number_input", "Mean total transport distance (km)").set_value(1000.)
        self.apply()
        result = self.app.session_state.result
        self.assertEqual(result["inputs"]["mean_transport_km"], 1000.)
        self.assertEqual([m.value for m in self.app.metric][:3], ["1,990", "1,908", "82"])
        self.assertLess(result["distance_distribution"]["nominal_long_share"], original["distance_distribution"]["nominal_long_share"])
        self.assertEqual(result["annual"][0]["annual_infectious_transport_mean"], 20.)
        self.assertNotEqual(result["p_receipt"], original["p_receipt"])
        self.assertTrue(any("central 95%" in x.value.lower() for x in self.app.markdown))

    def test_dropoff_map_year_sync_and_probabilities(self):
        import base64
        from streamlit_app import delivery_shade
        self.assertEqual(delivery_shade(0), "#ffffff")
        self.assertEqual(delivery_shade(1), "#174a7e")
        self.assertEqual(delivery_shade(.5), "#8ba5bf")
        original = self.app.session_state.result
        self.widget("slider", "Drop-off map year").set_value(0).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.widget("slider", "Map year").value, 0)
        self.assertEqual(self.app.session_state.result, original)
        svg = base64.b64decode(self.app.get("imgs")[1].proto.imgs[0].url.split(",", 1)[1]).decode()
        paths = [p for p in ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}path") if "data-i" in p.attrib]
        self.assertEqual(len(paths), 3096)
        self.assertTrue(all(p.attrib["fill"] == "#ffffff" for p in paths))
        self.widget("slider", "Map year").set_value(9).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.widget("slider", "Drop-off map year").value, 9)
        self.widget("selectbox", "Inspect delivery county").select(149).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.widget("selectbox", "Inspect a county").value, 149)
        delivery = next(x.value for x in self.app.dataframe if "delivery_probability_by_map_year" in x.value.columns and "receptivity" not in x.value.columns)
        self.assertEqual(delivery.iloc[0].delivery_probability_by_map_year, original["receipt_probability_history"][8][149])


if __name__ == "__main__":
    unittest.main()
