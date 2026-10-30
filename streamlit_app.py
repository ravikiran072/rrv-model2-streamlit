"""Public Streamlit interface. Run: python -m streamlit run streamlit_app.py."""
import json
import hashlib
import importlib
import math
import os
import sqlite3
import xml.etree.ElementTree as ET
from contextlib import closing
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

import model_engine
import model_utils
import landscape_engine

ROOT = Path(__file__).resolve().parent
SPEED_KEYS = ("speed_very_low", "speed_low", "speed_moderate", "speed_high")
MODEL_REVISION = hashlib.sha256(b"".join((ROOT / name).read_bytes() for name in
    ("model_info.json", "model_engine.py", "model_utils.py", "landscape_engine.py",
     "model_data.npz", "landscape_data.npz", "route_kernels.npz"))).hexdigest()
MODEL_INFO = json.loads((ROOT / "model_info.json").read_text(encoding="utf-8"))
DEFAULT_SPEEDS = tuple(float(value) for value in MODEL_INFO["default_speeds_km_per_year"])
# Streamlit reruns this script after a Git update, while Python can retain
# imported engines and their in-memory array caches from the previous release.
# Reload the dependent modules together when the bundled model changes.
if getattr(model_engine, "_streamlit_revision", None) != MODEL_REVISION:
    importlib.invalidate_caches()
    importlib.reload(model_utils)
    importlib.reload(landscape_engine)
    importlib.reload(model_engine)
    model_engine._streamlit_revision = MODEL_REVISION
SOURCE_COLORS = ("#a6b2bb", "#438bb5", "#e7a13e", "#cf704b")
SOURCE_LABELS = ("Not reached", "Endemic at year 0", "Spread from main enzootic area", "Spread from translocation nidi")
EXPERT_FIELDS = [
    ("observed_event_interval", "Detected transport interval", "Years per detected event at year zero; default 5", "Active"),
    ("detection_probability", "Detection probability", "Fraction; default 0.01", "Active"),
    ("receptivity_cutoff", "Habitat receptivity cutoff", "Score 0–1; default 0.7928484500378316 (year-zero median)", "Active"),
    ("receipt_cutoff", "County receipt cutoff", "Fraction; default 0.50", "Active"),
    ("long_haul_share", "Long-haul share", "Fraction ≥1,207.008 routed km; default 0.60", "Active"),
    ("spread_speed", "Spread speeds by habitat", "km/year; default 0 / 16 / 40 / 80; steps of 2", "Active"),
    ("burden_scaling", "Transport burden scaling", "Default on; proportional to start-of-year reached counties", "Active"),
    ("new_source_feedback", "Earlier nidi as transport origins", "Default on; beginning the following year", "Active"),
    ("long_haul_distance", "Distance bands", "Routed km / trip distribution", "Recorded only"),
    ("route_scope", "Interstate corridor scope", "Even-numbered one/two-digit, westbound", "Recorded only"),
    ("origin_destination_weights", "Origin and destination weighting", "Eligible Interstate km", "Recorded only"),
    ("water_barriers", "River and lake effects", "Fourfold river delay; lakes blocked", "Recorded only"),
]


@st.cache_data
def county_names(revision=MODEL_REVISION):
    """County metadata from the accepted sewer-inclusive habitat package."""
    return json.loads((ROOT / "county_names.json").read_text(encoding="utf-8"))


@st.cache_data(max_entries=16, show_spinner=False)
def calculate(params, revision):
    result = model_engine.run(params)
    result["model_revision"] = revision
    return result


def current_result(result):
    """Reject old session results even if they have a new revision label."""
    if not isinstance(result, dict) or result.get("model_revision") != MODEL_REVISION:
        return False
    required = {"inputs", "annual", "arrival", "baseline_arrival", "receptivity",
                "p_receipt", "receipt_probability_history", "seeds", "model_note"}
    required_inputs = {"initial_annual_infectious_transports", "scale_transport_with_burden",
                       "include_nidi_as_origins", "horizon", "mode", "random_seed",
                       "receipt_cutoff", "receptivity_cutoff", "landscape_mode", "speed_unit", "distance_unit"}
    return (required.issubset(result) and isinstance(result["inputs"], dict)
            and required_inputs.issubset(result["inputs"])
            and result["inputs"]["speed_unit"] == "km/year"
            and isinstance(result["annual"], list) and bool(result["annual"])
            and all(isinstance(row, dict) and {"annual_infectious_transport_mean",
                    "expected_detected_transports", "year", "baseline", "reached", "added"}.issubset(row)
                    for row in result["annual"]))


def county_table(result, year=None):
    if year is None:
        year = result["inputs"]["horizon"]
    frame = pd.DataFrame(county_names()).drop(columns=["map_x", "map_y", "score_1_minus_pfree"], errors="ignore")
    frame["baseline_arrival_year"] = [None if x < 0 else x for x in result["baseline_arrival"]]
    frame["scenario_arrival_year"] = [None if x < 0 else x for x in result["arrival"]]
    frame["receipt_probability_at_horizon"] = result["p_receipt"]
    frame["receptivity"] = [None if x < 0 else x for x in result["receptivity"]]
    frame["predicted_1_minus_pfree"] = result["receptivity"]
    frame["map_year"] = year
    frame["earliest_arrival_source_at_map_year"] = [county_status(result, i, year) for i in range(len(frame))]
    frame["delivery_probability_by_map_year"] = result["receipt_probability_history"][year - 1] if year else 0.
    seeds = {s["index"]: s["year"] for s in result["seeds"]}
    frame["independent_nidus_year"] = [seeds.get(i) for i in range(len(frame))]
    frame["landscape_mode"] = result["inputs"]["landscape_mode"]
    horizon = result["inputs"]["horizon"]
    frame["reached_at_horizon"] = frame.scenario_arrival_year.le(horizon)
    frame["added_at_horizon"] = frame.reached_at_horizon & ~frame.baseline_arrival_year.le(horizon)
    frame["reached_at_map_year"] = frame.scenario_arrival_year.le(year)
    frame["additional_at_map_year"] = frame.reached_at_map_year & ~frame.baseline_arrival_year.le(year)
    return frame


@st.cache_data
def map_parts(revision=MODEL_REVISION):
    root = ET.fromstring((ROOT / "counties.svg").read_text(encoding="utf-8"))
    paths = list(root.iter("{http://www.w3.org/2000/svg}path"))
    return ([(int(p.attrib["data-i"]), p.attrib["d"]) for p in paths if "data-i" in p.attrib],
            [p.attrib["d"] for p in paths if "data-i" not in p.attrib])


def source_code(result, i, year):
    arrival, base = result["arrival"][i], result["baseline_arrival"][i]
    if base == 0:
        return 1
    if arrival < 0 or arrival > year:
        return 0
    return 3 if base < 0 or arrival < base - 1e-6 else 2


def county_status(result, i, year):
    return SOURCE_LABELS[source_code(result, i, year)]


def shade(code, score):
    probability = max(0., min(1., float(score)))
    color = SOURCE_COLORS[code][1:]
    return "#" + "".join(f'{math.floor(255 * (1 - probability * (1 - int(color[k:k+2], 16) / 255)) + .5):02x}' for k in (0, 2, 4))


def map_svg(result, year):
    names = county_names()
    seeds = [s for s in result["seeds"] if s["year"] <= year]
    county_paths, state_paths = map_parts()
    counts = [0, 0, 0, 0]
    paths = []
    for i, geometry in county_paths:
        code = source_code(result, i, year)
        counts[code] += 1
        status = county_status(result, i, year)
        color = shade(code, result["receptivity"][i])
        title = escape(f'{names[i]["name"]}, {names[i]["state"]}: {status}')
        paths.append(f'<path data-i="{i}" fill="{color}" d="{geometry}"><title>{title}</title></path>')
    boundaries = ''.join(f'<path d="{geometry}"/>' for geometry in state_paths)
    markers = []
    for seed in seeds:
        county = names[seed["index"]]
        points = []
        for k in range(10):
            angle, radius = -math.pi / 2 + k * math.pi / 5, 5 if k % 2 == 0 else 2.15
            points.append(f'{county["map_x"] + math.cos(angle) * radius:.2f},{county["map_y"] + math.sin(angle) * radius:.2f}')
        markers.append(f'<polygon points="{" ".join(points)}" fill="#202d38" stroke="#ffffff" stroke-width=".5"/>')
    legend = []
    for j, code in enumerate((1, 2, 3, 0)):
        y = 790 + j * 48
        legend.append(f'<text x="20" y="{y+12}">{SOURCE_LABELS[code]} ({counts[code]:,})</text>'
                      f'<rect x="350" y="{y}" width="660" height="17" fill="url(#ramp{code})"/>')
        for k, tick in enumerate(("0%", "25%", "50%", "75%", "100%")):
            legend.append(f'<text x="{350+k*165}" y="{y+32}" font-size="11" text-anchor="middle">{tick}</text>')
    ramps = ''.join(f'<linearGradient id="ramp{i}"><stop offset="0%" stop-color="#ffffff"/>'
                    f'<stop offset="100%" stop-color="{color}"/></linearGradient>' for i, color in enumerate(SOURCE_COLORS))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1050 1055" '
            'role="img" aria-label="County spread map" style="width:100%;height:auto">'
            f'<title>Model 2 — year {year}</title><desc>{escape(json.dumps(result["inputs"]))}</desc>'
            f'<defs>{ramps}</defs><rect width="1050" height="1055" fill="white"/>'
            f'<text x="20" y="28" font-family="Arial" font-size="22">Model 2 — year {year}</text>'
            '<g transform="translate(0,75)"><g stroke="#ffffff" stroke-width=".22">'
            + "".join(paths) + '</g><g fill="none" stroke="#65747e" stroke-width=".65">'
            + boundaries + '</g><g id="nidus-markers">' + ''.join(markers) + '</g></g>'
            '<g font-family="Arial" font-size="14" fill="#29485c">'
            '<text x="350" y="765">Habitat score = model-predicted 1 − P(free)</text>'
            + ''.join(legend) + '<text x="20" y="1005" font-size="12">'
            'Hue shows earliest arrival source; shade is the habitat score. Stars mark independent nidi.</text>'
            '<text x="20" y="1028" font-size="12">Shading is not a year-specific infection probability or delivery probability.</text>'
            f'<text x="20" y="1047" font-size="12">Spread speeds: {" / ".join(str(result["inputs"][key]) for key in SPEED_KEYS)} km/year.</text></g></svg>')


def controls():
    with st.sidebar:
        st.header("Scenario inputs")
        st.caption("Update inputs, then apply the scenario. Map-year changes do not rerun the model.")
        with st.form("scenario"):
            observed = st.number_input("Detected transported rabid raccoons / year", 0., 20., .2, .1, format="%.3f", help="Year-zero detected transport rate; annual transports can grow with burden.")
            detection = st.number_input("Detection probability (%)", .01, 100., 1., .1, format="%.2f")
            long_share = st.slider("Long-haul share (%)", 0., 100., 60., help="Share traveling at least 1,207.008 routed km.")
            receipt = st.slider("Minimum cumulative delivery chance (%)", 0., 100., 50.)
            receptivity = st.number_input("Minimum habitat suitability score", 0., 1., MODEL_INFO["default_receptivity_cutoff"], .01, format="%.6f")
            horizon = st.slider("Horizon (years)", 1, 20, 20)
            mode = st.selectbox("Calculation", ["monte_carlo", "analytic"], format_func=lambda x: {"monte_carlo": "Monte Carlo · 10,000 histories", "analytic": "Direct Poisson probabilities"}[x])
            seed = st.number_input("Random seed", 0, 4294967295, 20261009)
            scale = st.checkbox("Scale transports with county burden", value=True,
                                help="Multiply the initial transport mean by start-of-year reached counties / year-zero endemic counties (877 at defaults).")
            feedback = st.checkbox("Earlier nidi become transport origins", value=True,
                                   help="Earlier nidi and their onward spread contribute origins beginning the following year.")
            st.subheader("Natural spread")
            speeds = [st.number_input(f"{label} habitat (km/year)",
                      float(MODEL_INFO["speed_range_km_per_year"][0]),
                      float(MODEL_INFO["speed_range_km_per_year"][1]), value, float(MODEL_INFO["speed_step"]))
                      for label, value in zip(("No/very-low", "Low", "Moderate", "High"), DEFAULT_SPEEDS)]
            st.caption("Speeds use steps of 2 km/year (0–400). The landscape, annual origins, and onward spread are recalculated from year zero for every scenario.")
            applied = st.form_submit_button("Apply scenario", type="primary", width="stretch")
    params = dict(observed_per_year=observed, detection_probability=detection / 100,
                  long_share=long_share / 100, receipt_cutoff=receipt / 100,
                  receptivity_cutoff=receptivity, horizon=horizon, mode=mode,
                  random_seed=seed, landscape_mode="rebuild", scale_transport_with_burden=scale,
                  include_nidi_as_origins=feedback,
                  **dict(zip(SPEED_KEYS, speeds)))
    if "result" in st.session_state and not current_result(st.session_state.result):
        del st.session_state.result
    if applied or "result" not in st.session_state:
        try:
            with st.spinner("Calculating county spread…"):
                result = calculate(params, MODEL_REVISION)
            st.session_state.result = result
            st.session_state.map_year = horizon
            st.session_state.pop("scenario_error", None)
        except ValueError as exc:
            st.session_state.scenario_error = str(exc)


def scenario_view(result):
    params = result["inputs"]
    if "scenario_error" in st.session_state:
        st.error(st.session_state.scenario_error)
        st.info("The results below are the last successful scenario. Correct the inputs and apply again.")
    st.caption(f'Applied scenario: {params["initial_annual_infectious_transports"]:g} initial infectious transports/year → '
               f'{result["annual"][-1]["annual_infectious_transport_mean"]:.2f}/year in year {params["horizon"]} · '
               f'{"10,000 histories; seed " + str(params["random_seed"]) if params["mode"] == "monte_carlo" else "Direct Poisson probabilities"}')
    st.caption(f'Burden scaling: {"on" if params["scale_transport_with_burden"] else "off"} · Earlier nidi as origins: {"on" if params["include_nidi_as_origins"] else "off"} · Landscape recalculated from year zero.')
    st.caption(f'New foci require cumulative delivery chance >{params["receipt_cutoff"]:.1%} AND habitat score >{params["receptivity_cutoff"]:.6f}, before the existing front arrives. Habitat score is not a biological establishment probability.')
    year = st.slider("Map year", 0, params["horizon"], key="map_year")
    row = result["annual"][year - 1] if year else dict(
        baseline=sum(x == 0 for x in result["baseline_arrival"]),
        reached=sum(x == 0 for x in result["arrival"]), added=0)
    a, b, c, d = st.columns(4)
    a.metric("Counties reached", f'{row["reached"]:,}')
    b.metric("Baseline counties", f'{row["baseline"]:,}')
    c.metric("Additional counties", f'{row["added"]:,}')
    d.metric("Independent foci to this year", sum(s["year"] <= year for s in result["seeds"]))
    svg = map_svg(result, year)
    # st.html's HTML-only sanitizer removes SVG elements in Streamlit 1.56.
    # The image renderer accepts SVG strings and preserves the county paths.
    st.image(svg, width="stretch")
    st.caption("Blue: year-zero endemic counties · Gold: main front · Coral: nidus-first arrival · Gray: not reached. Each color blends from white using the fixed habitat score, including unreached counties. Coral includes counties reached earlier by nidi even when the natural front arrives later within the horizon.")
    names = county_names()
    county = st.selectbox("Inspect a county", sorted(range(len(names)), key=lambda i: (names[i]["state"], names[i]["name"])),
                          format_func=lambda i: f'{names[i]["name"]}, {names[i]["state"]}')
    frame = county_table(result, year)
    detail = frame.iloc[[county]].copy()
    detail.insert(0, "status_at_map_year", county_status(result, county, year))
    st.dataframe(detail, hide_index=True, width="stretch")
    st.subheader("Annual results")
    annual = pd.DataFrame(result["annual"])
    st.line_chart(annual.set_index("year")[["baseline", "reached", "added"]])
    with st.expander("Annual data and independent foci"):
        st.dataframe(annual, hide_index=True, width="stretch")
        seeds = [{"county": f'{names[s["index"]]["name"]}, {names[s["index"]]["state"]}',
                  "year": s["year"], "receipt_probability": s["p_receipt"], "receptivity": s["receptivity"]}
                 for s in result["seeds"] if s["year"] <= year]
        if seeds:
            st.dataframe(pd.DataFrame(seeds), hide_index=True)
        else:
            st.write(f"No independent foci by map year {year}.")
    st.subheader("Annual transport and burden")
    st.line_chart(annual.set_index("year")[["annual_infectious_transport_mean", "expected_detected_transports"]])
    st.caption(result["model_note"])
    st.subheader("Download results")
    a, b, c, d = st.columns(4)
    a.download_button("County CSV", frame.to_csv(index=False), "model2_county_results.csv", "text/csv")
    b.download_button("Annual CSV", annual.to_csv(index=False), "model2_annual_results.csv", "text/csv")
    c.download_button("Scenario JSON", json.dumps(result, indent=2), "model2_scenario.json", "application/json")
    d.download_button("Map SVG", svg, f"model2_map_year_{year}.svg", "image/svg+xml")


def save_expert(payload, db_path):
    """Use the same response schema as the original local website."""
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as con, con:
        con.execute("""CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_utc TEXT NOT NULL,
            name TEXT NOT NULL, organization TEXT NOT NULL,
            inputs_json TEXT NOT NULL, comments TEXT NOT NULL)""")
        cur = con.execute("INSERT INTO submissions(created_utc,name,organization,inputs_json,comments) VALUES (?,?,?,?,?)",
                          (payload["created_utc"], payload["name"], payload["organization"], json.dumps(payload["inputs"]), payload["comments"]))
        return cur.lastrowid


def expert_view():
    st.subheader("Expert input")
    st.write("Record proposed estimates, ranges, and evidence. These responses do not change the scenario. Parameters marked Recorded only describe fixed assumptions that require a later code revision.")
    db_path = os.environ.get("RRV_DB")
    if not db_path:
        try:
            db_path = st.secrets.get("RRV_DB")
        except FileNotFoundError:
            pass
    if db_path:
        st.info("Responses are saved on this host and can also be downloaded. Include only information you intend to submit to the host administrator.")
    else:
        st.info("Download mode: prepare and download your response below. Responses are not collected or saved on the server.")
    with st.form("expert"):
        a, b = st.columns(2)
        name = a.text_input("Name (optional)", max_chars=120)
        organization = b.text_input("Organization (optional)", max_chars=160)
        rows = pd.DataFrame([dict(parameter=key, label=label, guidance=description, status=status,
                                  central="", low="", high="", evidence="")
                             for key, label, description, status in EXPERT_FIELDS])
        edited = st.data_editor(rows, hide_index=True, disabled=["parameter", "label", "guidance", "status"],
                                column_config={"parameter": None}, width="stretch", key="expert_estimates")
        comments = st.text_area("Additional comments", max_chars=4000)
        submitted = st.form_submit_button("Save response" if db_path else "Prepare response", type="primary")
    if submitted:
        entries = {row["parameter"]: {key: str(row[key]).strip()[:2000] for key in ("central", "low", "high", "evidence")}
                   for row in edited.to_dict("records") if str(row["central"]).strip()}
        if not entries:
            st.error("Enter at least one central estimate.")
        else:
            payload = dict(created_utc=datetime.now(timezone.utc).isoformat(), name=name,
                           organization=organization, comments=comments, inputs=entries)
            st.session_state.expert_response = payload
            if db_path:
                try:
                    ident = save_expert(payload, db_path)
                    st.success(f"Saved response #{ident}.")
                except (OSError, sqlite3.Error):
                    st.error("Server storage is unavailable. Download your response below to keep a copy.")
            else:
                st.success("Response prepared. Download it below to keep a copy.")
    if "expert_response" in st.session_state:
        st.download_button("Download prepared response", json.dumps(st.session_state.expert_response, indent=2),
                           "model2_expert_response.json", "application/json")


def main():
    st.set_page_config(page_title="Raccoon Rabies · Model 2", page_icon="🦝", layout="wide")
    st.title("Raccoon rabies scenario explorer")
    st.write("Explore how transported infections and natural spread affect county reach over time.")
    controls()
    scenario, expert, methods = st.tabs(["Scenario explorer", "Expert input", "Model methods"])
    with scenario:
        if "result" in st.session_state:
            scenario_view(st.session_state.result)
        else:
            st.error(st.session_state.get("scenario_error", "Apply a scenario to begin."))
    with expert:
        expert_view()
    with methods:
        st.html((ROOT / "methods.html").read_text(encoding="utf-8"))
    st.caption("Updated habitat forest: 14 predictors including EPA sewershed coverage; 715 fitting counties and a fixed 72-county holdout. See Model methods for assumptions, validation, and the limits of the shared-front calculation.")


if __name__ == "__main__":
    main()
