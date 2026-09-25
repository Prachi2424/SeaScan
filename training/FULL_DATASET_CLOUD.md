# Complete Sentinel-1 cloud training

Use SAR_FULL_DATASET_COLAB.ipynb in Google Colab with a GPU runtime and at least 90 GiB of free ephemeral disk. Nothing in this workflow stores the large Zenodo archives on the local Mac.

The workflow deliberately keeps the evaluation defensible:

- Part I: 1,200 oil-spill scenes for training and validation.
- Part II: 685 no-oil and 685 look-alike scenes for training and validation.
- Part III: 150 oil, 150 no-oil, and 150 look-alike scenes reserved for one final test.
- Train/validation separation happens by original scene before four tiles are generated, preventing tiles from one scene leaking across the split.
- Oil performance is reported with Dice and IoU.
- No-oil and look-alike performance is reported with false-positive pixel and false-alarm tile rates.

The script downloads and removes one large category archive at a time. Prepared 512 px scenes remain in the Colab runtime and the final backend-compatible checkpoint is written to Google Drive.

If a run is interrupted, rerun the individual stages in order:

    python training/full_dataset_cloud.py prepare --work-dir /content/seascan-full-dataset
    python training/full_dataset_cloud.py train --work-dir /content/seascan-full-dataset --checkpoint /content/drive/MyDrive/SeaScan/checkpoints/seascan_unet_full.pt
    python training/full_dataset_cloud.py test --work-dir /content/seascan-full-dataset --checkpoint /content/drive/MyDrive/SeaScan/checkpoints/seascan_unet_full.pt

The final checkpoint uses the same 3-input-channel, base-width-32 U-Net architecture and provenance schema as the SeaScan backend.
