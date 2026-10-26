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
from landscape_engine import DEFAULT_SPEEDS, annual_probabilities, landscape, travel, inputs as landscape_inputs


class ModelTests(unittest.TestCase):
    def test_default_reference(self):
        for mode in ("monte_carlo", "analytic"):
            r = run({"mode": mode})
            self.assertEqual((r["nidi"], r["baseline_count"], r["added"], r["reached"]),
                             (2, 1358, 164, 1522))
            self.assertEqual([(s["index"], s["year"]) for s in r["seeds"]], [(149, 11), (3017, 14)])

    def test_transport_and_threshold_controls(self):
        for parameters in ({"observed_per_year": 0}, {"receipt_cutoff": 1}, {"receptivity_cutoff": 1}):
            r = run(parameters)
            self.assertEqual((r["nidi"], r["added"]), (0, 0))
        self.assertNotEqual(run({"receptivity_cutoff": .5})["added"], 164)

    def test_annual_probabilities_and_reproducibility(self):
        first = run({})
        self.assertEqual(first, run({}))
        self.assertNotEqual(first["p_receipt"], run({"random_seed": 42})["p_receipt"])
        previous = np.zeros(len(first["arrival"]))
        for y in range(1, 21):
            p = np.asarray(run({"horizon": y})["p_receipt"])
            self.assertTrue(np.all(p >= previous))
            previous = p

    def test_county_map_totals_match_annual_analysis(self):
        r = run({})
        arrival = np.asarray(r["arrival"])
        baseline = np.asarray(r["baseline_arrival"])
        for row in r["annual"]:
            reached = (arrival >= 0) & (arrival <= row["year"])
            base = (baseline >= 0) & (baseline <= row["year"])
            self.assertEqual(int(reached.sum()), row["reached"])
            self.assertEqual(int((reached & ~base).sum()), row["added"])

    def test_invalid_inputs(self):
        for parameters in ({"detection_probability": 0}, {"horizon": 1.5}, {"mode": "bad"},
                           {"random_seed": -1}, {"receipt_cutoff": float("nan")}, []):
            with self.assertRaises(ValueError):
                run(parameters)

    def test_recalculated_landscape_defaults_and_speed_response(self):
        r = run({"landscape_mode": "rebuild"})
        self.assertEqual((r["baseline_count"], r["nidi"], r["added"]), (1373, 2, 157))
        normal = landscape(DEFAULT_SPEEDS)["baseline"]
        half = landscape((0., 5., 12.5, 25.))["baseline"]
        finite = np.isfinite(normal)
        np.testing.assert_array_equal(finite, np.isfinite(half))
        np.testing.assert_allclose(half[finite], 2 * normal[finite], rtol=1e-6)
        slower = run({"speed_low": 5, "speed_moderate": 12.5, "speed_high": 25})
        self.assertEqual(slower["inputs"]["landscape_mode"], "rebuild")
        self.assertLess(slower["baseline_count"], r["baseline_count"])
        self.assertNotEqual(slower["p_receipt"], r["p_receipt"])

    def test_no_very_low_category_can_be_activated(self):
        inactive = landscape(DEFAULT_SPEEDS)
        active = landscape((5., 10., 25., 50.))
        self.assertGreater(active["graph"].nnz, inactive["graph"].nnz)
        self.assertGreater(int(np.sum(active["baseline"] <= 20)), int(np.sum(inactive["baseline"] <= 20)))

    def test_zero_speeds_stop_natural_spread(self):
        r = run(dict(speed_very_low=0, speed_low=0, speed_moderate=0, speed_high=0))
        self.assertEqual(r["baseline_count"], 877)
        self.assertEqual(r["reached"], 877 + r["nidi"])
        with self.assertRaises(ValueError):
            run({"landscape_mode": "reference", "speed_low": 12})
        with self.assertRaises(ValueError):
            run({"speed_high": -1})

    def test_dynamic_origin_kernels_match_original_probabilities(self):
        from model_engine import data
        a = data()
        q = annual_probabilities(a["baseline"], 20)
        np.testing.assert_allclose(q[0], a["short"], atol=1e-8, rtol=1e-6)
        np.testing.assert_allclose(q[1], a["long"], atol=1e-8, rtol=1e-6)
        for i in (149, 3017):
            row = int(np.flatnonzero(a["road_global"] == i)[0])
            np.testing.assert_array_equal(travel(DEFAULT_SPEEDS, i), a["travel"][row])


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
            self.assertEqual(json.load(response)["added"], 164)
        for route, expected in (("/", b'data-tab="methods"'), ("/methods.html", b'Binomial'),
                                ("/app.js", b'queueCalculation'), ("/counties.svg", b'data-i=')):
            with urllib.request.urlopen(self.base + route) as response:
                self.assertIn(expected, response.read())
        with self.post("/api/scenario", {"speed_low": 5}) as response:
            data = json.load(response)
            self.assertEqual(data["inputs"]["speed_low"], 5)
            self.assertEqual(data["inputs"]["landscape_mode"], "rebuild")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/scenario", {"detection_probability": 0})
        self.assertEqual(caught.exception.code, 400)

    def test_expert_capture_and_protected_export(self):
        payload = {"name": "Test", "inputs": {"receipt_cutoff": {
            "central": ".5", "low": ".3", "high": ".7", "evidence": "QA example"}}}
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
