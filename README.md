# Final Model 2 website

A Python application for changing raccoon rabies model parameters and automatically regenerating the analysis and county map. All prepared model data and map assets are included. No R installation, GIS software, map-service key, or external map tiles are needed.

## Streamlit app (recommended)

Use Python 3.12, install the dependencies, and launch the public-app interface:

```bash
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

Open the local URL printed by Streamlit (usually http://localhost:8501).
The sidebar has the scenario controls. Click **Apply scenario** after editing;
map-year and county selection changes reuse the applied results. Custom speeds
automatically select recalculated geography. Downloads include county CSV,
annual CSV, scenario JSON, and the displayed map as SVG. The model engines and
reference calculations are shared with the original website.

### Publish on Streamlit Community Cloud

1. Upload this folder to a GitHub repository, including the three `.npz` files,
   `counties.svg`, `county_names.json`, `methods.html`, the Python files,
   `requirements.txt`, and `.streamlit/config.toml`.
2. At https://share.streamlit.io, choose **Create app**, select the repository
   and branch, and set the main file path to **streamlit_app.py**.
3. In advanced settings, choose **Python 3.12**, then deploy. Set app sharing
   to public to give visitors access through the generated `streamlit.app` URL.

The app needs no API keys, R installation, external map tiles, or separate HTTP
server. Keep `.streamlit/secrets.toml` and response databases out of GitHub.
Deployment instructions: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy

### Expert responses in Streamlit

By default, experts prepare and download a JSON response; the server does not
collect responses. A prepared download remains available until another valid
response is prepared or the visitor's session ends. Editing the form alone does
not change that prepared download. Active and future parameters remain distinct.

For self-hosted installations with a persistent disk, set `RRV_DB` to the SQLite
database path (environment variable or Streamlit secret) to enable collection.
It uses the original website's response schema. Back up that database. Local
files on Community Cloud are not durable response storage; leave collection
disabled there until an external database is integrated. The Streamlit app has
no public administrator export endpoint. The original server is not launched
by Streamlit.

## Original website launch

Use Python 3.12 and run these commands in this extracted folder:

```bash
python -m pip install -r requirements.txt
python app.py
```

The browser opens at **http://127.0.0.1:8765**. Keep the terminal open while using the website. Press Ctrl+C to stop it. If the port is occupied, use `python app.py --port 8766`. To suppress browser launch, add `--no-browser`.

On Windows, `py` can replace `python`. To use a separate environment:

```text
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

On macOS/Linux, create the environment with `python3 -m venv .venv`, activate it with `source .venv/bin/activate`, and use the two launch commands above.

## Original website tabs

**Scenario explorer:** edit an input and pause briefly. The annual analysis and map refresh automatically. The map becomes dimmed during an update or when inputs are invalid; downloads remain disabled until results are current. The map-year slider shows years 0 through the selected horizon without rerunning the simulation. Select a county for arrival time, receptivity, and receipt probability. Download county CSV, annual CSV, scenario JSON, or the displayed map as SVG.

**Expert input:** records proposed values, ranges, and evidence. Submissions do not override the active scenario. Parameters marked FUTURE require additional model work before they can drive the scenario.

**Model methods:** details the design, habitat inputs, route construction, annual simulation, focus rule, natural spread, water barriers, outputs, and validation. Equations have adjacent definitions and plain-language explanations. The recovered original habitat summary is used to explain the Random Forest target (1 − 2024 probability of freedom), 11 land-cover variables plus latitude and log human density, 974-county development sample, 10% holdout, and prediction to 3,096 counties. Missing fitting settings, performance results, and original category breakpoints are identified.

## Inputs

| Control | Default |
|---|---:|
| Directly detected transported rabid raccoons | 0.2/year (one every five years) |
| Detection probability | 1% |
| Long-haul share (at least 750 routed miles) | 60% |
| Cumulative county receipt threshold | >50% |
| Habitat receptivity threshold | >0.7050952593606139 |
| No/very-low habitat speed | 0 miles/year |
| Low habitat speed | 10 miles/year |
| Moderate habitat speed | 25 miles/year |
| High habitat speed | 50 miles/year |
| Landscape mode | Archived reference; speed edits select recalculation |
| Horizon | 20 years; adjustable from 1 to 20 |
| Calculation | Annual Monte Carlo, 10,000 histories |
| Random seed | 20261009 |

The website displays probabilities as **percentages**. The Python API uses **fractions**: 1% detection is `0.01`; 60% long haul is `0.6`; a 50% cutoff is `0.5`. Receptivity remains a 0–1 score in both interfaces. Infectious transport mean is detected events/year divided by detection probability, or 20/year at defaults.

The annual Monte Carlo uses a distributionally exact reduction of the fixed-route Poisson process: new first receipts among previously unhit histories are binomial draws. It estimates cumulative county receipt fractions after each year without storing individual route events. An optional direct Poisson mode removes Monte Carlo sampling. These calculations depend on independent events, fixed annual route intensities, and no new-source feedback; see the methods tab.

At defaults, both modes identify **Pulaski County, Arkansas in year 11** and **Juneau County, Wisconsin in year 14**. Year 20 has **1,522 reached counties**, compared with **1,358 baseline counties**, for **164 additional counties**. Changing the random seed may change marginal threshold crossings. Exported scenario JSON records the seed and all active inputs.

## Editable landscape and fixed assumptions

All four habitat-specific natural spread speeds are editable. Speed changes reweight the 10-km graph, regenerate baseline arrival times, recalculate which counties can serve as transport origins each year, and regenerate onward spread. A zero speed blocks natural movement through that category. Scores and category assignments are retained. Route scope, distance-band weights, river/lake rules, and new-source feedback remain fixed. Receptivity is not a per-animal biological establishment probability. No extra 5% establishment chance is applied. Both threshold comparisons are strictly greater than.

The archived-reference mode retains the agreed Final Model 2 defaults (baseline 1,358; +164 counties). Any speed edit selects recalculated mode. For a valid speed comparison, select recalculated mode for every comparison run, including the run with default speeds: its default-speed baseline reaches 1,373 counties, with +157 after translocation. That baseline difference reflects the preexisting reconstruction, not a speed change. In an archived western-front diagnostic, this reconstruction added 37 counties versus 135 in the accepted archive; that mismatch remains unresolved. Connecticut is absent from the supplied county records. The original habitat methods summary is recovered, but the full fitting records remain unavailable. The methods tab describes these limits. Reproducing the default count does not independently validate the geography.

## Expert storage and shared hosting

Expert responses are saved in `expert_inputs.sqlite3`, or the path set by `RRV_DB`. Back up this file when collecting real estimates. The administrator CSV is `/api/submissions.csv`. When `RRV_ADMIN_TOKEN` is set, this export requires the header `Authorization: Bearer <token>`.

Running `app.py` launches a local website; it does not publish externally. For shared institutional access, run the process or container behind institution-managed HTTPS and authentication, with persistent response storage. The application has no built-in SSO. `RRV_HOST`, `PORT`, `RRV_DB`, and `RRV_ADMIN_TOKEN` configure hosting. The default binds to localhost. `--host 0.0.0.0` enables access through a configured host network.

Build the included container with `docker build -t rrv-model2 .`. The host must supply authentication, networking, and a persistent `/data` volume.

## Package contents

- `app.py`: Python launcher.
- `model_engine.py`: validation, annual probabilities, focus screening, and spread.
- `landscape_engine.py`: speed-dependent graph weights, baseline and onward travel, and annual origin eligibility.
- `server.py`: HTTP endpoints, expert storage, and export.
- `index.html`, `app.js`, `styles.css`: interface and automatic updates.
- `methods.html`: model methods shown on the website.
- `model_data.npz`: prepared route intensities, baseline, habitat scores, and travel times.
- `county_names.json`, `counties.svg`: identifiers, habitat category, and map geometry.
- `landscape_data.npz`, `route_kernels.npz`: editable-speed topology and per-origin destination probabilities.
- `provenance/methods_summary_bachelors_level.txt`: original supplied summary. Its transport assumptions are historical; only the habitat derivation supports the new habitat-methods section.
- `provenance/build_editable_landscape.py`: data-preparation source, requiring the upstream project files and NumPy/SciPy/Matplotlib (use --source for the extracted upstream directory and --output for the website directory); not needed to run the website.
- `DATA_PROVENANCE.json`: upstream array mapping, geographic settings, shapes, and checksums.
- `test_model.py`: regression and live HTTP tests.

## Checks

Run `python -m unittest -v test_model.py test_streamlit.py` for all 15 checks.
The Streamlit checks exercise applied inputs, invalid-input recovery, custom
speeds, map-year changes without recalculation, county inspection, map/export
consistency, and expert-response preparation and storage.

Run `python -m unittest -v test_model.py`. Eleven tests cover reference outputs in both modes, changed and invalid parameters, reproducible annual receipt probabilities, agreement between map-year counts and annual analysis, HTTP scenario/methods responses, expert storage/export protection, regeneration at changed speeds, zero-speed barriers, activation of no/very-low habitat, and agreement of destination kernels and default travel times with the saved model. JavaScript syntax was checked with Node. Browser appearance and downloads still need a normal-browser check on the deployment machine; no browser executable was available in the build environment. No test responses are bundled.

## Interpreting the two thresholds

1. **Minimum chance of a delivery:** cumulative probability of at least one rabid raccoon arriving by that year. At the default 50%, more than 5,000 of 10,000 histories must have a delivery. It is not a 50% annual chance.
2. **Minimum habitat suitability score:** the county’s Random Forest score must exceed the selected value (default approximately 0.705). This is not a biological establishment probability.

Both must pass, and an existing front must not already have reached the county. These thresholds do not change the fitted scores or the spread-speed category labels.
