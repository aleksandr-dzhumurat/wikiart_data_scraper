import os
import random
from pathlib import Path

import torch
import yaml
from PIL import Image
from torchvision.transforms import CenterCrop, Compose, Normalize, Resize, ToTensor
from transformers import AutoImageProcessor, AutoModelForImageClassification

# ── Config ────────────────────────────────────────────────────────────────────
cfg = yaml.safe_load(open(os.environ.get("JOB_CONFIG_PATH", "/workspace/data/config.yaml")))
output_dir = Path(cfg["output_dir"])

# Support both flat layout (output_dir/best_model) and per-run layout (output_dir/<RUN_ID>/best_model)
if (output_dir / "best_model").exists():
    model_dir = output_dir / "best_model"
else:
    run_dirs = sorted([d for d in output_dir.iterdir() if d.is_dir() and (d / "best_model").exists()])
    if not run_dirs:
        raise FileNotFoundError(f"No best_model found under {output_dir}")
    model_dir = run_dirs[-1] / "best_model"
    print(f"Using latest run: {run_dirs[-1].name}")

# ── Load model ────────────────────────────────────────────────────────────────
print(f"Loading model from {model_dir} ...")
processor = AutoImageProcessor.from_pretrained(str(model_dir))
model = AutoModelForImageClassification.from_pretrained(str(model_dir))
model.eval()

size = processor.size.get("height", 224)
transform = Compose([
    Resize((size, size)),
    CenterCrop(size),
    ToTensor(),
    Normalize(mean=processor.image_mean, std=processor.image_std),
])

# ── Pick random image from data/dataset ───────────────────────────────────────
dataset_name = cfg["dataset_name"]
dataset_dir = Path(dataset_name) if os.path.isdir(dataset_name) else Path("data/dataset")

image_paths = list(dataset_dir.glob("*/*"))
image_paths = [p for p in image_paths if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]

if not image_paths:
    raise FileNotFoundError(f"No images found in {dataset_dir}")

samples = random.sample(image_paths, min(5, len(image_paths)))

# ── Inference ─────────────────────────────────────────────────────────────────
correct = 0
for i, image_path in enumerate(samples, 1):
    true_label = image_path.parent.name
    image = Image.open(image_path).convert("RGB")
    pixel_values = transform(image).unsqueeze(0)  # (1, C, H, W)

    with torch.no_grad():
        logits = model(pixel_values=pixel_values).logits

    pred_id = logits.argmax(-1).item()
    pred_label = model.config.id2label[pred_id]
    confidence = torch.softmax(logits, dim=-1)[0, pred_id].item()
    match = pred_label == true_label
    correct += int(match)

    print(f"[{i}/5] {image_path.name}")
    print(f"  True : {true_label}")
    print(f"  Pred : {pred_label}  ({confidence:.1%})  {'✓' if match else '✗'}")

print(f"\nAccuracy: {correct}/5")
