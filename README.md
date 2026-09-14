# SeaScan

SeaScan is a real-data maritime forensics platform for oil-spill detection, drift reconstruction, and explainable vessel attribution. It is being built as a Smart India Hackathon 2026 prototype for NTRO Problem Statement 26143.

> **Investigation principle:** the platform ranks *potentially responsible vessels* from evidence. It never asserts legal guilt. No synthetic spill masks, AIS tracks, confidence scores, or vessel rankings are generated.

## Phase 6: forensic reporting and packaging

SeaScan persists investigation evidence, validates uploads, uses those files for particle drift reconstruction and explainable AIS candidate ranking, and exports immutable forensic report packages.

Implemented API endpoints:

- `GET /` — service discovery
- `GET /api/health` — service health and version
- `GET /api/system/config` — supported data formats and pipeline stages
- `POST /api/investigations` — create an investigation before adding evidence
- `GET /api/investigations` and `GET /api/investigations/{id}` — retrieve persisted case records and evidence
- `POST /api/ais/upload` — validate and persist real AIS CSV/Parquet evidence
- `POST /api/environment/upload` — validate and persist real current/wind CSV, GeoJSON, or NetCDF evidence
- `POST /api/satellite/upload` — segment a real GeoTIFF/PNG only with configured trained U-Net weights
- `POST /api/drift/forward` and `POST /api/drift/backward` — particle advection using uploaded timestamped environmental observations
- `POST /api/attribution/rank` — candidate vessel ranking from uploaded AIS, with all score components returned
- `POST /api/reports/forensic.pdf` — PDF containing an evidence map, spill metrics, drift summary, candidate rankings, provenance, and legal notices
- `POST /api/reports/package.zip` — PDF plus a SHA-256 integrity manifest and standalone legal notice
- `GET /docs` — interactive OpenAPI documentation

## Repository layout

```text
SeaScan/
├── frontend/                 # React + Vite + TypeScript dashboard
├── backend/
│   ├── app/api/              # FastAPI route modules
│   ├── app/core/             # configuration and startup lifecycle
│   ├── app/schemas/          # typed HTTP contracts
│   └── tests/                # backend API tests
├── training/                 # segmentation training (Phase 2)
├── data/uploads/             # real source files, ignored by Git
├── data/processed/           # pipeline outputs, ignored by Git
├── docker-compose.yml
└── .env.example
```

## Run locally

Prerequisites: Python 3.11+ and Node.js 20+.

1. Create a local environment file if you need to override defaults:

   ```powershell
   Copy-Item .env.example backend/.env
   ```

   `SEASCAN_CORS_ORIGINS` must be a JSON array, for example `["http://localhost:5173"]`. For Docker, copy the same file to the repository root as `.env`; Compose reads `SEASCAN_MODEL_WEIGHTS_PATH` from there.

2. Start the API:

   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8000
   ```

3. In a separate terminal, start the dashboard:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

Open [http://localhost:5173](http://localhost:5173); API documentation is at [http://localhost:8000/docs](http://localhost:8000/docs).

## Train and enable satellite segmentation

The satellite endpoint intentionally returns `503` until it has a checkpoint produced from real, paired scenes and masks. Train with matching filename stems, then set the generated path in `SEASCAN_MODEL_WEIGHTS_PATH`:

```powershell
cd training
python train.py --images path\to\scenes --masks path\to\masks --output ..\data\models\seascan_unet.pt
```

The saved checkpoint records its held-out Dice score, epoch, UTC training time, and sample count. SeaScan returns direct sigmoid probabilities from that checkpoint; it does not create arbitrary confidence values.

## Run with Docker

```powershell
docker compose up --build
```

The frontend is available at `http://localhost:5173` and the API at `http://localhost:8000`. Uploaded and processed evidence remains mounted in `./data`.

## Phase roadmap

1. **Foundation** — project scaffold, configuration, health checks, and dashboard shell. *(complete)*
2. **ML and real-data ingestion** — imagery, AIS, and environmental upload validation; U-Net inference interface; persistent investigation records. *(complete)*
3. **Drift and attribution** — particle advection, AIS reconstruction, behavioral features, and transparent weighted scoring. *(complete)*
4. **Forensics dashboard** — Leaflet GIS layers, evidence timeline, Mermaid relationship graph, charts, and investigation workflows.
5. **Deployment hardening** — full Docker runtime, tests, documentation, and model/data operations. *(complete)*
6. **Forensic report and packaging** — PDF export, evidence-map snapshot, geometry metrics, rankings, legal disclaimers, and SHA-256 manifest. *(complete)*

## Model provenance (Part A)

The **Model provenance** button is available from the overview and investigation
workspace. `GET /api/model/info` returns checkpoint identity, architecture,
training records, and metrics. `GET /api/model/metrics` returns the metrics alone.
Both inspect the configured `SEASCAN_MODEL_WEIGHTS_PATH` with the inference
architecture and reject missing, invalid, or incompatible checkpoints with HTTP 503.

Optional supplementary metadata belongs next to the checkpoint, named
`<checkpoint filename>.metadata.json` (for example, `seascan_unet.pt.metadata.json`).
Its JSON object must contain `weights_sha256` (the lowercase SHA-256 of the weights)
and `training_metadata` (an object containing additional recorded fields).
Supported additional fields are `validation_iou` (0–1), `training_epochs` (total
completed epochs), `input_shape` ([channels, height, width]), and
`dataset_provenance` (a JSON object of actual dataset identifiers, sources,
versions, split details, and/or licenses). Input channels must be 3; spatial
sizes must be positive multiples of 16. Any repeated checkpoint fields must
match exactly. The checkpoint epoch is displayed separately from total epochs.

The existing trainer only records `trained_at`, `epoch`, `dataset_sample_count`,
and `validation_dice`. This change does not invent missing IoU, training shape,
or dataset provenance, and does not change training. Unrecorded values are null
in the API and shown as **Not recorded**. A checksum binds the metadata to the
weights; it does not independently substantiate training claims.

Run the Part A contract checks from `backend` with:

```sh
python -m pytest tests/test_model_provenance.py -q
```

Tests generate temporary, untrained checkpoint fixtures exclusively to verify
loading and validation. No test weights or metrics are used by the application.
