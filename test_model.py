"""Run with: python -m unittest -v test_model.py"""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np

import server
from model_engine import run



class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run({})

    def test_accepted_reference(self):
        r = self.result
        reference = json.loads((Path(__file__).parent / "provenance/shifted_exponential_scenario_reference.json").read_text())
        for key in ("arrival", "baseline_arrival", "p_receipt", "receipt_probability_history", "seeds"):
            self.assertEqual(r[key], reference[key], key)
        self.assertEqual(len(r["annual"]), len(reference["annual"]))
        for actual, expected in zip(r["annual"], reference["annual"]):
            self.assertEqual(actual.keys(), expected.keys())
            for field in actual:
                if field in ("assigned_mean_distance_km", "assigned_long_share"):
                    # BLAS reduction order varies across platforms at the last
                    # floating-point bit. Keep all modeled events/counts exact.
                    np.testing.assert_allclose(actual[field], expected[field], rtol=1e-14, atol=1e-12)
                else:
                    self.assertEqual(actual[field], expected[field], field)
        self.assertEqual((r["baseline_count"], r["reached"], r["added"], r["nidi"]), (1908, 2003, 95, 5))
        self.assertEqual([(s["index"], s["year"]) for s in r["seeds"]], [(149,9),(733,9),(2922,11),(3017,11),(1461,19)])

    def test_annual_feedback_and_prefix(self):
        r = self.result
        previous = 877
        for a in r["annual"]:
            self.assertEqual(a["endemic_counties_at_start"], previous)
            self.assertAlmostEqual(a["annual_infectious_transport_mean"], 20 * previous / 877)
            previous = a["reached"]
        short = run({"horizon":10})
        self.assertEqual(short["annual"], r["annual"][:10])
        self.assertEqual(short["receipt_probability_history"], r["receipt_probability_history"][:10])

    def test_transport_rate_anchor_and_no_transport(self):
        shorter=run({"mean_transport_km":1000})
        self.assertEqual(shorter["annual"][0]["annual_infectious_transport_mean"],20)
        self.assertEqual(self.result["annual"][0]["annual_infectious_transport_mean"],20)
        self.assertNotEqual(shorter["p_receipt"],self.result["p_receipt"])
        fixed=run({"scale_transport_with_burden":False,"include_nidi_as_origins":False})
        self.assertTrue(all(a["annual_infectious_transport_mean"]==20 for a in fixed["annual"]))
        zero=run({"observed_per_year":0})
        self.assertEqual((zero["reached"],zero["added"],zero["nidi"]),(1908,0,0))
        self.assertTrue(all(p==0 for p in zero["p_receipt"]))

    def test_shifted_exponential_distribution_and_95_range(self):
        from transport_engine import distribution
        for mean in (102,1000,2268,10000):
            d=distribution(mean);scale=mean-100
            self.assertAlmostEqual(sum(d["band_weights"]),1)
            for value,expected in ((d["central_95_lower_km"],.025),(d["central_95_upper_km"],.975)):
                self.assertAlmostEqual(1-np.exp(-(value-100)/scale),expected)
            self.assertAlmostEqual(d["nominal_long_share"],np.exp(-(1207.008-100)/scale))
        self.assertLess(distribution(1000)["nominal_long_share"],distribution(2268)["nominal_long_share"])
        self.assertEqual(distribution(1000)["band_edges_km"][0],100)
        self.assertIsNone(distribution(1000)["band_edges_km"][-1])

    def test_every_assigned_route_meets_minimum_and_direction(self):
        from transport_engine import routes,kernel
        a=routes();d=a["distance_km"];road=a["road_global"]
        for mean in (102,1000,2268,10000):
            k=kernel(mean);coo=k["matrix"][:,road].tocoo();positive=coo.data>0
            i,j=coo.row[positive],coo.col[positive]
            self.assertTrue(np.all(d[i,j]>=100))
            self.assertTrue(np.all(a["longitude"][j]<a["longitude"][i]))
            mass=np.asarray(k["matrix"].sum(axis=1)).ravel()
            np.testing.assert_allclose(mass[a["has_destination"]],1,atol=1e-12)
            self.assertTrue(np.all(mass[~a["has_destination"]]==0))
        for row in self.result["annual"]:
            self.assertAlmostEqual(row["annual_assigned_transport_mean"]+row["annual_unassigned_transport_mean"],row["annual_infectious_transport_mean"])
            self.assertGreaterEqual(row["assigned_mean_distance_km"],100)

    def test_map_year_counts_and_probabilities(self):
        r = self.result
        arrival = np.asarray(r["arrival"])
        baseline = np.asarray(r["baseline_arrival"])
        for a in r["annual"]:
            reached = (arrival>=0)&(arrival<=a["year"])
            natural = (baseline>=0)&(baseline<=a["year"])
            self.assertEqual(int(reached.sum()),a["reached"])
            self.assertEqual(int((reached&~natural).sum()),a["added"])
        history = np.asarray(r["receipt_probability_history"])
        self.assertTrue(np.all(np.diff(history,axis=0)>=0))
        self.assertEqual(run({}),r)

    def test_speed_changes_rebuild_the_landscape(self):
        slower=run({"speed_low":8,"speed_moderate":20,"speed_high":40})
        self.assertLess(slower["baseline_count"],self.result["baseline_count"])
        self.assertNotEqual(slower["p_receipt"],self.result["p_receipt"])
        self.assertEqual(slower["inputs"]["landscape_mode"],"rebuild")

    def test_metric_units_and_physical_conversion(self):
        from landscape_engine import landscape
        # Exact conversion of the historical speeds preserves the physical graph.
        old = json.loads((Path(__file__).parent / "provenance/historical_accepted_scenario_reference.json").read_text())
        old_arrival = np.array(old["baseline_arrival"])
        converted = landscape(tuple(v*1.609344 for v in (0,10,25,50)))["baseline"]
        valid = old_arrival >= 0
        np.testing.assert_allclose(converted[valid],old_arrival[valid],rtol=1e-5,atol=1e-4)
        self.assertEqual(int((converted<=20).sum()),1917)
        self.assertEqual(self.result["inputs"]["speed_unit"],"km/year")
        self.assertEqual(self.result["inputs"]["speed_step"],2)
        self.assertEqual([self.result["inputs"][k] for k in ("speed_very_low","speed_low","speed_moderate","speed_high")],[0,16,40,80])
        html=(Path(__file__).parent/"index.html").read_text()
        import re
        controls=re.findall(r'<input id="speed_[^>]+>',html)
        self.assertEqual(len(controls),4)
        self.assertTrue(all('step="2"' in tag and 'max="400"' in tag for tag in controls))

    def test_invalid_inputs(self):
        for p in ({"detection_probability":0},{"horizon":1.5},{"mode":"bad"},{"random_seed":-1},
                  {"receipt_cutoff":float("nan")},{"speed_high":-1},{"scale_transport_with_burden":"yes"},{"speed_low":17},{"speed_high":402},{"mean_transport_km":100},{"mean_transport_km":float("nan")},{"long_share":.6},[]):
            with self.assertRaises(ValueError): run(p)


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        server.DB = Path(cls.tmp.name) / "test.sqlite3"
        server.initialize()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()
        cls.tmp.cleanup()

    def post(self, route, payload):
        return urllib.request.urlopen(urllib.request.Request(
            self.base + route, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}))

    def test_http_scenario_and_methods(self):
        with self.post("/api/scenario", {}) as response:
            self.assertEqual(json.load(response)["added"], 95)
        for route, expected in (("/", b'data-tab="delivery"'), ("/methods.html", b'Binomial'),
                                ("/app.js", b'queueCalculation'), ("/counties.svg", b'data-i='), ("/map_style.js", b'#cf704b'), ("/model_info.json", b'2003')):
            with urllib.request.urlopen(self.base + route) as response:
                self.assertIn(expected, response.read())
        with self.post("/api/scenario", {"speed_low": 18}) as response:
            data = json.load(response)
            self.assertEqual(data["inputs"]["speed_low"], 18)
            self.assertEqual(data["inputs"]["landscape_mode"], "rebuild")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/scenario", {"detection_probability": 0})
        self.assertEqual(caught.exception.code, 400)

    def test_expert_capture_and_protected_export(self):
        payload = {"name": "Test", "inputs": {"mean_transport_km": {
            "central": "2268", "low": ".3", "high": ".7", "evidence": "QA example"}}}
        with self.post("/api/submissions", payload) as response:
            self.assertTrue(json.load(response)["saved"])
        old_token = os.environ.get("RRV_ADMIN_TOKEN")
        os.environ["RRV_ADMIN_TOKEN"] = "test-only-token"
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(self.base + "/api/submissions.csv")
            self.assertEqual(caught.exception.code, 403)
            request = urllib.request.Request(self.base + "/api/submissions.csv",
                                            headers={"Authorization": "Bearer test-only-token"})
            with urllib.request.urlopen(request) as response:
                self.assertIn(b"QA example", response.read())
        finally:
            if old_token is None:
                os.environ.pop("RRV_ADMIN_TOKEN", None)
            else:
                os.environ["RRV_ADMIN_TOKEN"] = old_token


if __name__ == "__main__":
    unittest.main()
