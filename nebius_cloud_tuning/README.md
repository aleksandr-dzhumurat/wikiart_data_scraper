# Fine-tuning Image Classification on Nebius AI Jobs

| Field | Value |
|-------|-------|
| title | Fine-tuning Image Classification on a HuggingFace Dataset |
| category | training |
| type | job |
| runtime | gpu |
| hardware | 1× L40S (48 GB VRAM), 8 vCPU, 32 GB RAM |
| frameworks | transformers, datasets, torchvision |
| model | google/vit-base-patch16-224 |
| task | image-classification |
| classes | Impressionism, Surrealism, Minimalism, Pop Art |
| dataset size | 4 × 400 images (80/10/10 split) |
| best val accuracy | 76% |
| keywords | fine-tuning, vision-transformer, wikiart |
| difficulty | beginner |

**Task:** Multi-class art genre classification (image → label)
**Approach:** Fine-tune a pretrained ViT (Vision Transformer) using HuggingFace `transformers` + `Trainer`

---

## 1. Project structure

```
src/
├── train.py                     # Training script
├── inference.py                 # Local inference script
├── requirements.txt             # Python dependencies
└── configs/
    ├── config_prod.yaml         # train config
```

---

## 2. Dataset

4 art style classes (400 images each, 80/10/10 train/val/test split):

- Impressionism
- Surrealism
- Minimalism
- Pop Art

Build and upload the dataset:

```bash
# Download images and prepare hf_dataset/ with train/validation/test splits
make prepare-images

# Upload splits to S3 object storage
make upload-dataset-s3
```

The training job reads the dataset from the S3-mounted volume at `/workspace/data/hf_dataset`.

---

## 3. Upload job files to Object Storage

```bash
# Create bucket
nebius storage bucket create --name adzhumurat-art-genre-classification

# Get bucket ID
export BUCKET_ID=$(nebius storage bucket get-by-name \
  --name adzhumurat-art-genre-classification \
  --format jsonpath='{.metadata.id}')

# Upload training script, config, requirements
make upload-job-files
```

---

## 4. Launch the job

```bash
make deploy
```

This creates a Nebius AI job named `art-genre-classification-prod` on a 1×L40S GPU with the production config.

---

## 5. Monitor and retrieve results

```bash
# Get job ID
export JOB_ID=$(nebius ai job get-by-name \
  --name art-genre-classification-prod \
  --format jsonpath='{.metadata.id}')

# Check status (QUEUED → RUNNING → SUCCEEDED)
nebius ai job get $JOB_ID

# Stream logs
nebius ai logs $JOB_ID

# Download best model and results to nebius_cloud_tuning/output/<RUN_ID>/
make download_model
```

---

## 6. Artifacts

Each run saves the following to `output/<RUN_ID>/`:

| File | Description |
|------|-------------|
| `best_model/` | Final model weights + processor config |
| `learning_curve.json/csv` | Per-epoch train/eval loss and accuracy |
| `test_results.json` | Overall test set metrics |
| `accuracy_table.json/csv` | Per-class precision, recall, F1 |

---

## 7. Local inference

```bash
make predict
```

Uses `configs/config_local.yaml` and `nebius_cloud_tuning/inference.py`.
