import csv
import json
import logging
import os
from pathlib import Path

import evaluate
import numpy as np
import yaml
from datasets import disable_caching, load_dataset
from PIL import Image
from sklearn.metrics import classification_report
from torchvision.transforms import (
    CenterCrop,
    ColorJitter,
    Compose,
    Normalize,
    RandomHorizontalFlip,
    RandomVerticalFlip,
    Resize,
    ToTensor,
)
from transformers import (
    AutoImageProcessor,
    AutoModelForImageClassification,
    DefaultDataCollator,
    Trainer,
    TrainingArguments,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Load config ──────────────────────────────────────────────────────────────
cfg = yaml.safe_load(open(os.environ.get("JOB_CONFIG_PATH", "/workspace/data/config.yaml")))
output_dir = Path(os.environ.get("OUTPUT_DIR", cfg["output_dir"]))
output_dir.mkdir(parents=True, exist_ok=True)
log.info("Artifacts will be saved to: %s", output_dir)
disable_caching()
# ── Dataset ───────────────────────────────────────────────────────────────────
dataset_name = cfg["dataset_name"]
num_proc = os.cpu_count() or 4
if os.path.isdir(dataset_name):
    log.info("Loading dataset %s from S3...", dataset_name)
    raw = load_dataset("imagefolder", data_dir=dataset_name, num_proc=num_proc)
else:
    log.info("Loading dataset %s from Huggingface...", dataset_name)
    raw = load_dataset(dataset_name, num_proc=num_proc)

labels     = raw[cfg["dataset_split_train"]].features[cfg["label_column"]].names
label2id   = {l: i for i, l in enumerate(labels)}
id2label   = {i: l for i, l in enumerate(labels)}
num_labels = len(labels)
log.info("Classes (%d): %s", num_labels, labels)

# ── Processor & transforms ────────────────────────────────────────────────────
processor = AutoImageProcessor.from_pretrained(cfg["model_name"])
mean, std  = processor.image_mean, processor.image_std
size       = processor.size.get("height", 224)

train_transforms = Compose([
    Resize((size, size)),
    RandomHorizontalFlip(),
    RandomVerticalFlip(),
    ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2),
    ToTensor(),
    Normalize(mean=mean, std=std),
])
val_transforms = Compose([
    Resize((size, size)),
    CenterCrop(size),
    ToTensor(),
    Normalize(mean=mean, std=std),
])

def apply_transforms(batch, transforms):
    return {
        "pixel_values": [
            transforms(img.convert("RGB") if isinstance(img, Image.Image)
                       else Image.open(img).convert("RGB"))
            for img in batch[cfg["image_column"]]
        ],
        "labels": batch[cfg["label_column"]],
    }

train_ds = raw[cfg["dataset_split_train"]].with_transform(
    lambda b: apply_transforms(b, train_transforms))
val_ds   = raw[cfg["dataset_split_val"]].with_transform(
    lambda b: apply_transforms(b, val_transforms))
test_ds  = raw[cfg["dataset_split_test"]].with_transform(
    lambda b: apply_transforms(b, val_transforms))

# ── Model ─────────────────────────────────────────────────────────────────────
log.info("Loading model: %s", cfg["model_name"])
model = AutoModelForImageClassification.from_pretrained(
    cfg["model_name"],
    num_labels=num_labels,
    id2label=id2label,
    label2id=label2id,
    ignore_mismatched_sizes=True,   # replace classification head
)

# ── Metrics ───────────────────────────────────────────────────────────────────
accuracy = evaluate.load("accuracy")

def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    return accuracy.compute(predictions=preds, references=labels)

# ── Training ──────────────────────────────────────────────────────────────────
training_args = TrainingArguments(
    output_dir=str(output_dir),
    num_train_epochs=cfg["num_train_epochs"],
    per_device_train_batch_size=cfg["per_device_train_batch_size"],
    per_device_eval_batch_size=cfg["per_device_eval_batch_size"],
    learning_rate=cfg["learning_rate"],
    weight_decay=cfg["weight_decay"],
    warmup_ratio=cfg["warmup_ratio"],
    lr_scheduler_type=cfg["lr_scheduler_type"],
    fp16=cfg["fp16"],
    dataloader_num_workers=cfg["dataloader_num_workers"],
    save_strategy=cfg["save_strategy"],
    eval_strategy=cfg["eval_strategy"],
    load_best_model_at_end=cfg["load_best_model_at_end"],
    metric_for_best_model=cfg["metric_for_best_model"],
    save_total_limit=cfg.get("save_total_limit"),
    save_only_model=cfg.get("save_only_model", False),
    push_to_hub=False,
    report_to="none",
    logging_steps=20,
    remove_unused_columns=False,   # required: keep "pixel_values" column
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_ds,
    eval_dataset=val_ds,
    compute_metrics=compute_metrics,
    data_collator=DefaultDataCollator(),
)

log.info("Starting training...")
trainer.train()

# ── Learning curve ────────────────────────────────────────────────────────────
train_log = [e for e in trainer.state.log_history if "loss" in e and "eval_loss" not in e]
eval_log  = [e for e in trainer.state.log_history if "eval_accuracy" in e]
curve = []
for ev in eval_log:
    epoch = ev["epoch"]
    tr = next((e for e in reversed(train_log) if e["epoch"] <= epoch), {})
    curve.append({
        "epoch": epoch,
        "train_loss": tr.get("loss"),
        "eval_loss": ev.get("eval_loss"),
        "eval_accuracy": ev.get("eval_accuracy"),
    })
with open(output_dir / "learning_curve.json", "w") as f:
    json.dump(curve, f, indent=2)
with open(output_dir / "learning_curve.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["epoch", "train_loss", "eval_loss", "eval_accuracy"])
    writer.writeheader()
    writer.writerows(curve)
log.info("Learning curve saved (%d epochs)", len(curve))

# ── Test evaluation ───────────────────────────────────────────────────────────
log.info("Evaluating on test split...")
pred_output = trainer.predict(test_ds)
preds     = np.argmax(pred_output.predictions, axis=-1)
label_ids = pred_output.label_ids
test_results = {k: v for k, v in pred_output.metrics.items()}
log.info("Test results: %s", test_results)
with open(output_dir / "test_results.json", "w") as f:
    json.dump(test_results, f, indent=2)

# ── Per-class accuracy table ──────────────────────────────────────────────────
all_label_ids = list(range(len(labels)))
report_str  = classification_report(label_ids, preds, labels=all_label_ids, target_names=labels, digits=4)
report_dict = classification_report(label_ids, preds, labels=all_label_ids, target_names=labels, output_dict=True)
log.info("Per-class accuracy:\n%s", report_str)
with open(output_dir / "accuracy_table.json", "w") as f:
    json.dump(report_dict, f, indent=2)
rows = [{"class": cls, **{k: v for k, v in metrics.items()}}
        for cls, metrics in report_dict.items() if isinstance(metrics, dict)]
with open(output_dir / "accuracy_table.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["class", "precision", "recall", "f1-score", "support"])
    writer.writeheader()
    writer.writerows(rows)
log.info("Accuracy table saved")

# ── Save final model ──────────────────────────────────────────────────────────
trainer.save_model(str(output_dir / "best_model"))
processor.save_pretrained(str(output_dir / "best_model"))
log.info("Model saved to %s", output_dir / "best_model")
