# Final Model 2 website

Updated October 30, 2026. The application includes the accepted final habitat model, annual burden-scaled translocation, feedback from earlier nidi, and the approved map colors and probability shading. All runtime data are bundled; no R, GIS software, map key, or external data service is required.

## Streamlit app and public hosting

Use Python 3.12 and run:

```bash
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

Edit inputs and click **Apply scenario**. Burden scaling and earlier-nidus origin
feedback are on by default. Every scenario rebuilds the landscape from year zero;
the previous archived-reference mode is retired. Map-year and county selection
changes reuse the applied result. County details and CSVs include delivery
probability by map year and at the horizon, earliest arrival source, and
additional-county indicators. Displayed and downloaded SVGs share source colors,
habitat-score ramps, county/state boundaries, and independent-nidus stars.
The map uses Streamlit's image renderer to preserve SVG graphics.

The mean total transport distance control replaces the old long-haul-share
input. Its shifted-exponential curve, central 95% trip-distance range, derived
long-haul share, and routing-band probabilities update with each applied
scenario. The **Drop-off probability** tab shows a separate delivery-probability
map with SVG and CSV downloads. Year sliders and county selection are synchronized
between the two maps. Scenario JSON records the selected distribution; annual
CSV includes assigned and unassigned events and assigned-route distance summaries.

For Streamlit Community Cloud, use `ravikiran072/rrv-model2-streamlit`, branch
`main`, main file `streamlit_app.py`, and Python 3.12. Pushed changes update the
deployed app. The accepted predictions are bundled; scikit-learn and the fitted
forest are not loaded at runtime.

Expert input defaults to preparing downloadable JSON responses without server
collection. On a self-hosted installation with persistent storage, set `RRV_DB`
(environment variable or Streamlit secret) to enable SQLite collection. Community
Cloud local files are not durable storage; leave collection disabled there until
external storage is integrated. Keep secrets and databases out of GitHub. A
prepared download is a snapshot; editing the form does not update it until the
response is prepared again.

The imported `new/` folder is excluded from Git; its runtime and provenance files
have been integrated at the project root.

## Original website launch

Install Python 3.12. Open a terminal in the extracted `rrv_model2` folder and run:

```bash
python -m pip install -r requirements.txt
python app.py
```

The browser opens at http://127.0.0.1:8765. Keep the terminal open; Ctrl+C stops the application. On Windows, `py` can replace `python`. Use `python app.py --port 8766` if needed, or `--no-browser` to suppress browser launch. A virtual environment is optional.

## Using the website

- **Scenario explorer:** changing inputs automatically recalculates the analysis and map after a short pause. Dimmed results and disabled downloads indicate an update is pending. The map-year slider shows years 0 through the chosen horizon.
- **Drop-off probability:** a supplemental county map of cumulative probability of at least one infectious delivery by the displayed year. Both maps share the same year slider and scenario inputs. Its blue shading uses delivery probability directly, without habitat or nidus thresholds. Download the map as SVG or its values as County CSV.
- **Expert input:** records proposed central values, ranges, and evidence in a local database. Submissions do not override the scenario. Entries labeled RECORDED ONLY concern fixed assumptions that require a later code revision.
- **Model methods:** documents habitat predictors and processing, the training and validation procedure, annual transport, the two thresholds, landscape spread, assumptions, and map interpretation.

County CSV, annual CSV, scenario JSON, and the displayed map as an SVG are downloadable. SVG preserves the probability ramps, source colors, county and state boundaries, and nidus stars.

## Accepted defaults

| Parameter | Default |
|---|---:|
| Detected rabid raccoon transports at year zero | 0.2/year; one every five years |
| Detection probability | 1% |
| Initial inferred infectious transport mean | 20/year |
| Burden scaling | On; multiply initial mean by start-of-year reached counties / 877 |
| Earlier nidi become transport origins | On; beginning the following year |
| Minimum routed transport distance | 100 km |
| Mean total transport distance | 2,268 km; editable |
| Distance distribution | Shifted exponential; eight automatically weighted bands |
| Long-haul share | Derived from the curve; approximately 60% initially |
| Cumulative delivery probability cutoff | Strictly >50% |
| Habitat score cutoff | Strictly >0.7928484500378316; initial endemic-county median |
| Spread speeds: very low / low / moderate / high | 0 / 16 / 40 / 80 km/year |
| Horizon | 20 years; adjustable from 1 to 20 |
| Calculation | 10,000 annual Monte Carlo delivery histories |
| Random seed | 20261009 |

Default year 20: **2,003 counties reached**, versus **1,908** in the natural-only counterfactual; **95 additional counties** and **5 independent nidi**. The nidi are Pulaski AR (year 9), Lake IN (9), King WA (11), Juneau WI (11), and Jackson MO (19). Year-20 inferred transport mean is 44.7434/year. The optional analytic calculation produces 2,003 reached counties and 95 additional counties; it follows its own feedback trajectory.

The annual model uses one shared scenario front and ensemble delivery probabilities. It does not simulate 10,000 independently evolving epidemic fronts. Counties reached is a proxy for burden, assuming constant average burden per county. Origin weights are normalized Interstate kilometers; the burden multiplier is applied once to the national transport mean.

## Map interpretation

Hue indicates earliest modeled arrival source: blue for year-zero endemic counties, gold for the main enzootic front, coral for translocation nidi and their onward spread, gray for counties not yet reached. Each hue blends from white to its full color using the final habitat forest's predicted **1 − P(free)** score. This shade is not a year-specific infection probability or the delivery probability. Stars mark independent nidi.

At year 20, 289 counties have nidus-first arrival. Of these, 194 would also be reached later by the natural front within 20 years; 95 are beyond the natural-only footprint. Thus the coral count differs from the additional-county count.

## Thresholds and speed controls

The delivery screen requires a cumulative chance of at least one infectious delivery above the selected cutoff. At 50%, more than 5,000 of 10,000 histories must have received a delivery by that year. It is not a 50% annual chance. The separate habitat screen requires the fitted 1 − P(free) score to exceed the chosen value. There is no additional 5% establishment chance. Existing-front arrival by the end of that year preempts nidus establishment.

All four speeds are editable in multiples of 2 km/year (0–400). Distances use km and areas use km². Metric defaults round the previously accepted speeds to the nearest 2 km/year; this rounding can slightly change results. Every scenario rebuilds the landscape from year zero and updates annual origins and onward spread. A zero speed blocks natural spread through that habitat category. Changing the habitat cutoff does not refit the forest or change speed-category assignments. River delay, lake barriers, Interstate route scope, and habitat predictions remain fixed. Distance-band weights update from the selected mean.

## Habitat fit and reproducibility

The final forest has 14 predictors, including mapped EPA sewershed coverage. The fitting cohort contains 715 raccoon-variant counties after excluding counties baited by USDA in 2020–2024. Evaluation uses the retained random 72-county holdout and training-only tuning on 643 counties. Holdout R² is 0.306214, RMSE 0.204503, and MAE 0.164438. The final forest was then refitted on all 715 eligible counties for national prediction. The methods tab gives the full processing and evaluation details.

`provenance/` includes the working fitted forest, its metadata, the frozen fitting table, holdout predictions and results, tuning results, national predictions, integration and integrity audits, and the current shifted-exponential scenario reference and historical accepted reference. The forest archive supplied earlier was corrupt; its recovered replacement reproduces all 715 saved training predictions to numerical precision. Original exact habitat category cutpoints were unavailable; documented reconstructed midpoints reproduce every original category label.

`DATA_PROVENANCE.json` identifies sources, network assumptions, array shapes, and SHA-256 checksums. Raw national GIS source layers are supplied separately in the full habitat integration archive; the website uses prepared arrays. Running the website requires only NumPy and SciPy. Reading the optional fitted forest requires compatible scikit-learn 1.8.0 and joblib 1.5.3.

## Shared hosting and expert responses

Running `app.py` starts a local website and does not deploy it. For institutional hosting, use the included Dockerfile behind institution-managed HTTPS and authentication, with persistent response storage. Configure `RRV_HOST`, `PORT`, `RRV_DB`, and `RRV_ADMIN_TOKEN`; the default host is localhost. The application has no built-in login system.

Expert responses are saved in `expert_inputs.sqlite3`, or the path in `RRV_DB`. Back up that file. No existing responses or test responses are included in this ZIP. The administrator export is `/api/submissions.csv`; setting `RRV_ADMIN_TOKEN` requires `Authorization: Bearer <token>` for this endpoint.

Container: `docker build -t rrv-model2 .`. Mount persistent storage at `/data`. The host supplies access controls and network configuration.

## Verification

Run `python -m unittest -v test_model.py test_streamlit.py`. Tests compare the accepted reference, annual feedback formula, temporal consistency, event-rate comparisons, speed response, map attribution and shading, HTTP endpoints, and expert capture using a temporary database. JavaScript syntax is also checked with Node. Run `node test_map_style.js` for the optional palette, shading, and attribution checks. Headless Chromium checks passed for both maps, probability shading, synchronized year sliders, zero probabilities at year zero, live mean edits, reset, CSV/SVG downloads, methods, expert capture using a temporary database, and a mobile-width layout.

## Metric update — October 30

All live speed inputs and scenario JSON speeds are now in km/year, with multiples of 2 required (0–400). Map exports and route-distance descriptions use km. Areas remain km². Defaults of 0/16/40/80 km/year are rounded conversions, so they are slightly slower than the previous defaults. This changes year-20 total reach from 2,006 to 2,013 and additional reach from 89 to 105 through arrival and nidus-threshold timing. The original accepted reference is preserved as `provenance/historical_accepted_scenario_reference.json`; its speed fields retain their original historical units.

## Shifted exponential transport update

Transport distance is 100 km plus an exponential additional distance with mean `mean_transport_km - 100`. Distances below 100 km are excluded. The user selects mean total distance; the displayed central 95% trip-distance range, curve, eight band probabilities, and nominal long-haul share follow automatically. This range is not a confidence interval for the mean.

The initial mean 2,268 km approximately reproduces the previous nominal 60% tail above 1,207.008 km. It is an initialization for expert review, not an observed estimate. The eight bands begin at 100, 160.9344, 402.336, 804.672, 1,207.008, 1,609.344, 2,414.016, and 3,218.688 km; the final band is open ended. The complete exponential tail is retained.

Within each band, eligible destinations are weighted by selected Interstate length. Empty bands transfer probability to the nearest available band; routes remain westbound and at least 100 km. Origins with no eligible route contribute unassigned events. Consequently the nominal mean and long-haul fraction can differ from assigned distances. Annual CSV reports both assigned and unassigned transport means, mean assigned distance, and assigned long-haul fraction. The national event-rate anchor remains unchanged.

**Trucking volume:** no measured freight, truck-count, or shipping-volume data are used. The initial national event mean is defined as 0.2 detected transports/year divided by 1% detection, giving 20 infectious transports/year. This frequency sets the scale; normalized Interstate lengths and the distance assumption allocate events geographically.

The Python API accepts `mean_transport_km` (>100 and ≤10,000). The old `long_share` input is rejected because it is now a derived output. Scenario JSON includes distribution settings and full-precision annual receipt probabilities. The default reference is `provenance/shifted_exponential_scenario_reference.json`; historical metric references preserve the prior model for comparison.
