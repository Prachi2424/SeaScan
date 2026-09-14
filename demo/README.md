# SeaScan internal hackathon demo

This package provides one coherent end-to-end case for demonstrating SeaScan. It deliberately separates real evidence from synthetic evidence.

## Evidence provenance

- `evidence/satellite/sentinel1_2018_12_19_e.png` is a normalized, resized copy of a real Sentinel-1A GRD VV scene from the Gulf of Mexico.
- `evidence/satellite/sentinel1_2018_12_19_e_ground_truth.png` is the corresponding published binary oil-spill mask. It is for visual comparison only; do not upload it as satellite evidence.
- `evidence/ais/gulf_vessel_tracks_synthetic.csv` is synthetic demonstration AIS data. It contains four fictional MMSIs and must never be represented as observed vessel traffic.
- `evidence/environment/gulf_currents_2018_12_17_21.csv` is synthetic demonstration current and wind data. It must never be represented as an observed ocean product.

Satellite source: William Alberto Ramirez, *Oil Spill Segmentation*, Zenodo, DOI `10.5281/zenodo.4672426`. The source record describes 23 paired Sentinel-1 scenes and NOAA-derived masks from Gulf of Mexico incidents between 2018 and 2020.

## Demo values

- PNG bounds (west, south, east, north): `-88.8509434, 29.0606100, -88.4597525, 29.2801243`
- Satellite observation time: `2018-12-19 12:00 UTC`
- Suggested backward drift: `24 hours`, `30-minute step`, `200 particles`, `250 m initial spread`, `0.03 windage`
- Expected approximate hindcast origin: `29.1533028, -88.8045445` at `2018-12-18 12:00 UTC`
- Attribution settings: `25 km` radius, `90-minute` time window, `24-hour` behavior window

## Demonstration sequence

1. Start the backend and frontend, then create an investigation named `Gulf Sentinel-1 demo — 2018-12-19`.
2. Upload the satellite PNG, enable manual bounds, and enter the four bounds above. Keep the segmentation threshold at `0.5`.
3. Upload the synthetic environment CSV and synthetic AIS CSV. State aloud that both are synthetic and permitted for demonstration by the problem statement.
4. In Drift Analysis, set the observation time to `2018-12-19 12:00`, then run the 24-hour backward drift and 48-hour forward drift.
5. Run vessel attribution using the suggested hindcast origin and the settings above.
6. Explain the score breakdown instead of calling the top candidate guilty. Export the forensic PDF and evidence package.

## Model card summary

- Architecture: compact PyTorch U-Net, 3 input channels, base width 32, one binary output channel.
- Input: VV band normalized per scene from its 2nd to 98th percentiles, resized to 256x256, then replicated to three channels.
- Source scenes: 14 training/validation scenes; three were held out by scene for validation. Seven separate published test scenes were retained for an independent check.
- Training: 30 epochs, AdamW, combined binary cross-entropy and Dice loss.
- Held-out validation: mean per-scene Dice `0.367`, IoU `0.252`.
- Separate seven-scene test: mean per-scene Dice `0.551`, IoU `0.408`.
- Limitation: this is a small prototype checkpoint for an internal hackathon, not a production maritime surveillance model.
