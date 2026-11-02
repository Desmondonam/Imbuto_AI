# Imbuto AI

Kirundi-first farm information for Burundi's smallholder farmers, on any phone.
*Imbuto* means seed. The full vision is in the
[concept note](Imbuto_AI_IndabaX_Burundi_2026.pdf).

This repository is also the worked example for the talk *Turn an AI model into an application*
at Deep Learning IndabaX Burundi, 6 November 2026.

> **Status: demo.** Kirundi text and agronomy content are unreviewed drafts, and no operator is
> connected. Do not use it with real farmers until the checks in
> [docs/REVIEW_NEEDED.md](docs/REVIEW_NEEDED.mdare done.

## What it does

| Feature | Reaches people through | Built on |
| --- | --- | --- |
| Rain this season against each commune's record | USSD, SMS, voice, web | CHIRPS rainfall since 1981 |
| Recent market prices | USSD, SMS, voice, web | WFP price data |
| Approved advice, or handover to a person | USSD, SMS, voice, web | Character n-gram retrieval over a vetted knowledge base |
| Bean leaf check from a photo | Web | MobileNetV4 with a small classifier, in ONNX |
| Season map and farmer reports | Dashboard | The same core service |

## Run it

You need Python 3.12 and [uv](https://docs.astral.sh/uv/) (`pip install uv`). Trained artifacts
are committed, so the app needs no downloads and no internet.

```bash
uv sync
make run        # http://localhost:8000
make test
```

| Page | Shows |
| --- | --- |
| `/` | Farmer web app, installable on a phone |
| `/simulator` | Feature phone: the real USSD and SMS logic, with no operator |
| `/dashboard` | Rain map for ministries, co-ops and NGOs |
| `/ops` | Model monitoring. `make traffic` sends simulated traffic to it |
| `/api/docs` | Interactive API documentation |

To rebuild everything from public sources, which downloads about 240 MB:

```bash
make data && make train
```

## Measured results

| Measure | Result | Conditions |
| --- | --- | --- |
| Bean disease accuracy | 92.2% | 128 Ugandan test photos, full size |
| After shrinking for 2G | 87.5% | Same photos at 320 px, JPEG quality 40 |
| When the model chooses to answer | 95.6%, on 88% of photos | Full size |
| Upload size | 14 KB from a 1.5 MB file | Real Chrome, one test photo |
| Photo check on simulated 2G | 7.5 s | 40 kbps down, 20 kbps up, 800 ms latency |
| Home page on simulated 2G | 0.9 s | Same conditions |
| Rain shortfall forecast | **No reliable skill, so not released** | Walk-forward over 41 seasons |

These figures do not show how the model performs in Burundi: no Burundian test set exists yet.

## Learn from it

The [notebooks](notebooks/) follow the path of the talk.

1. [Data collection](notebooks/01_data_collection.ipynb): what is really available for Burundi
2. [Data storage](notebooks/02_data_storage.ipynb): a lakehouse on one laptop
3. [Crop health model](notebooks/03_model_crop_health.ipynb): the quantisation bug that raised no error
4. [Rain forecast](notebooks/04_model_rain_forecast.ipynb): when the right answer is "don't deploy"
5. [Packaging and API](notebooks/05_packaging_and_api.ipynb): bundles, FastAPI and safe retrieval
6. [Interface, deployment, monitoring](notebooks/06_interface_deploy_monitor.ipynb): 2G budgets and drift

Run `make data` first, because the notebooks read the raw data.

## Deploy

```bash
docker compose -f deploy/docker-compose.yml up --build
```

Before production, set `IMBUTO_ENV=production` and the secrets in [.env.example](.env.example).
The service refuses to start on development secrets. It also hides the simulator.

Real USSD, SMS and voice need an in-country aggregator or operator, plus short codes approved by
the regulator, ARCT. The gateway webhooks use a common format; expect to write a small adapter for
whichever provider you sign with.

## Project layout

```text
src/imbuto/lakehouse/   Bronze, silver and gold data
src/imbuto/ml/          Models, training, bundles, advisory retrieval
src/imbuto/core/        Channel-agnostic answers and alerts
src/imbuto/channels/    USSD and voice menu, SMS commands
src/imbuto/api/         FastAPI, web pages, service worker
src/imbuto/monitoring/  Storage, metrics, drift alert
artifacts/              Versioned, checksummed bundles
knowledge/, locale/     Draft knowledge base and translations
docs/                   Architecture, decisions, review list
slides/                 Talk run sheet, deck source, backup screenshots
```

Design decisions are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Data and licences

- CHIRPS rainfall, UCSB Climate Hazards Center, via the IRI Data Library
- Food prices, WFP via HDX (CC BY-IGO)
- Boundaries, geoBoundaries
- ONI and DMI, NOAA
- iBean images, Makerere AI Lab (MIT)
- MobileNetV4, through timm (Apache-2.0)

## Contribute

Kirundi speakers, agronomists, and holders of Burundian data are especially welcome. Corrections
to `locale/rn.json` are the fastest way to help.

Contact: Desmond Onam, desmondonam@gmail.com