"""Public Streamlit interface. Run: python -m streamlit run streamlit_app.py."""
import json
import os
import sqlite3
import xml.etree.ElementTree as ET
from contextlib import closing
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from model_engine import run

ROOT = Path(__file__).resolve().parent
SPEED_KEYS = ("speed_very_low", "speed_low", "speed_moderate", "speed_high")
DEFAULT_SPEEDS = (0., 10., 25., 50.)
EXPERT_FIELDS = [
    ("observed_event_interval", "Detected transport interval", "Years per detected event; default 5", "Active"),
    ("detection_probability", "Detection probability", "Fraction; default 0.01", "Active"),
    ("receptivity_cutoff", "Habitat receptivity cutoff", "Score 0–1; default 0.7050952593606139", "Active"),
    ("receipt_cutoff", "County receipt cutoff", "Fraction; default 0.50", "Active"),
    ("long_haul_share", "Long-haul share", "Fraction ≥750 routed miles; default 0.60", "Active"),
    ("spread_speed", "Spread speeds by habitat", "Miles/year; default 0 / 10 / 25 / 50", "Active"),
    ("establishment_probability", "Biological establishment per delivery", "No separate probability in current model", "Future"),
    ("long_haul_distance", "Distance bands", "Routed miles / trip distribution", "Future"),
    ("route_scope", "Interstate corridor scope", "Even-numbered one/two-digit, westbound", "Future"),
    ("origin_destination_weights", "Origin and destination weighting", "Eligible Interstate miles", "Future"),
    ("water_barriers", "River and lake effects", "Fourfold river delay; lakes blocked", "Future"),
    ("event_timing", "Event timing", "Annual threshold; spread following year", "Future"),
    ("new_source_feedback", "New foci as transport origins", "Currently disabled", "Future"),
]


@st.cache_data
def county_names():
    return json.loads((ROOT / "county_names.json").read_text(encoding="utf-8"))


@st.cache_data(max_entries=16, show_spinner=False)
def calculate(params):
    return run(params)


def county_table(result):
    frame = pd.DataFrame(county_names())
    frame["baseline_arrival_year"] = [None if x < 0 else x for x in result["baseline_arrival"]]
    frame["scenario_arrival_year"] = [None if x < 0 else x for x in result["arrival"]]
    frame["receipt_probability_at_horizon"] = result["p_receipt"]
    frame["receptivity"] = [None if x < 0 else x for x in result["receptivity"]]
    seeds = {s["index"]: s["year"] for s in result["seeds"]}
    frame["independent_nidus_year"] = [seeds.get(i) for i in range(len(frame))]
    frame["landscape_mode"] = result["inputs"]["landscape_mode"]
    horizon = result["inputs"]["horizon"]
    frame["reached_at_horizon"] = frame.scenario_arrival_year.le(horizon)
    frame["added_at_horizon"] = frame.reached_at_horizon & ~frame.baseline_arrival_year.le(horizon)
    return frame


@st.cache_data
def map_parts():
    root = ET.fromstring((ROOT / "counties.svg").read_text(encoding="utf-8"))
    return [(int(p.attrib["data-i"]), p.attrib["d"]) for p in root.iter("{http://www.w3.org/2000/svg}path")]


def county_status(result, i, year):
    arrival, base = result["arrival"][i], result["baseline_arrival"][i]
    if arrival < 0 or arrival > year:
        return "Not reached"
    if base < 0 or base > year:
        return "Added after translocation"
    return "Baseline front"


def map_svg(result, year):
    names = county_names()
    seeds = {s["index"] for s in result["seeds"] if s["year"] <= year}
    colors = {"Not reached": "#f0f3f2", "Baseline front": "#65aaa0", "Added after translocation": "#de9560"}
    paths = []
    for i, geometry in map_parts():
        status = county_status(result, i, year)
        color = "#a94932" if i in seeds else colors[status]
        title = escape(f'{names[i]["name"]}, {names[i]["state"]}: {status}')
        paths.append(f'<path fill="{color}" d="{geometry}"><title>{title}</title></path>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1050 730" '
            'role="img" aria-label="County spread map" style="width:100%;height:auto">'
            f'<title>Model 2 — year {year}</title><desc>{escape(json.dumps(result["inputs"]))}</desc>'
            '<rect width="1050" height="730" fill="white"/>'
            f'<text x="20" y="28" font-family="Arial" font-size="22">Model 2 — year {year}</text>'
            '<g transform="translate(0,35)" stroke="#dce2e8" stroke-width="0.18">'
            + "".join(paths) + '</g><text x="20" y="716" font-family="Arial" font-size="14">'
            'Teal: baseline · Orange: added · Red: independent focus · Gray: not reached</text></svg>')


def controls():
    with st.sidebar:
        st.header("Scenario inputs")
        st.caption("Update inputs, then apply the scenario. Map-year changes do not rerun the model.")
        with st.form("scenario"):
            observed = st.number_input("Detected transported rabid raccoons / year", 0., 20., .2, .1, format="%.3f")
            detection = st.number_input("Detection probability (%)", .01, 100., 1., .1, format="%.2f")
            long_share = st.slider("Long-haul share (%)", 0., 100., 60.)
            receipt = st.slider("Minimum cumulative delivery chance (%)", 0., 100., 50.)
            receptivity = st.number_input("Minimum habitat suitability score", 0., 1., .7050952593606139, .01, format="%.6f")
            horizon = st.slider("Horizon (years)", 1, 20, 20)
            mode = st.selectbox("Calculation", ["monte_carlo", "analytic"], format_func=lambda x: {"monte_carlo": "Monte Carlo · 10,000 histories", "analytic": "Direct Poisson probabilities"}[x])
            seed = st.number_input("Random seed", 0, 4294967295, 20261009)
            st.subheader("Natural spread")
            landscape = st.selectbox("Landscape", ["reference", "rebuild"], format_func=lambda x: "Archived reference" if x == "reference" else "Recalculated landscape")
            speeds = [st.number_input(f"{label} habitat (miles/year)", 0., 250., value, 5.)
                      for label, value in zip(("No/very-low", "Low", "Moderate", "High"), DEFAULT_SPEEDS)]
            st.caption("Custom speeds automatically use the recalculated landscape. For speed comparisons, use recalculated mode for every run, including default speeds.")
            applied = st.form_submit_button("Apply scenario", type="primary", width="stretch")
    params = dict(observed_per_year=observed, detection_probability=detection / 100,
                  long_share=long_share / 100, receipt_cutoff=receipt / 100,
                  receptivity_cutoff=receptivity, horizon=horizon, mode=mode,
                  random_seed=seed, landscape_mode="rebuild" if tuple(speeds) != DEFAULT_SPEEDS else landscape,
                  **dict(zip(SPEED_KEYS, speeds)))
    if applied or "result" not in st.session_state:
        try:
            with st.spinner("Calculating county spread…"):
                result = calculate(params)
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
    st.caption(f'Applied scenario: {params["annual_infectious_transports"]:g} infectious transports/year · '
               f'{params["horizon"]} years · {"Archived reference" if params["landscape_mode"] == "reference" else "Recalculated landscape"} · '
               f'{"10,000 histories; seed " + str(params["random_seed"]) if params["mode"] == "monte_carlo" else "Direct Poisson probabilities"}')
    if params["landscape_mode"] == "rebuild":
        st.info("Recalculated geography differs from the archive even at default speeds (1,373 baseline / +157 counties, compared with 1,358 / +164). Compare speed changes using recalculated mode throughout.")
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
    st.html(svg)
    st.caption("Hover over a county for its name. Use the county selector below for detailed results. Receipt probabilities refer to the full scenario horizon.")
    names = county_names()
    county = st.selectbox("Inspect a county", sorted(range(len(names)), key=lambda i: (names[i]["state"], names[i]["name"])),
                          format_func=lambda i: f'{names[i]["name"]}, {names[i]["state"]}')
    frame = county_table(result)
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
                 for s in result["seeds"]]
        if seeds:
            st.dataframe(pd.DataFrame(seeds), hide_index=True)
        else:
            st.write("No independent foci under these inputs.")
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
    st.write("Record proposed estimates, ranges, and evidence. These responses do not change the scenario. Parameters marked Future require additional model work.")
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
    st.caption("Geographic propagation requires further validation. Connecticut is absent from the supplied county records. See Model methods for assumptions and limitations.")


if __name__ == "__main__":
    main()
