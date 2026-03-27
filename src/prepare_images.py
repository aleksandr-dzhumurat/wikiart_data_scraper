import argparse
import json
import os
import random
import shutil
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from tqdm import tqdm

ROOT_DATA_DIR = os.getenv("ROOT_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
STATS_FILE = os.path.join(ROOT_DATA_DIR, "artworks_json_descriptive_stats.json")
ARTWORKS_DIR = os.path.join(ROOT_DATA_DIR, "artworks_json")
DATASET_DIR = os.path.join(ROOT_DATA_DIR, "dataset")
HF_DATASET_DIR = os.path.join(ROOT_DATA_DIR, "hf_dataset")

HF_WHITELIST = [
    "Impressionism",
    "Surrealism",
    "Minimalism",
    "Pop Art",
]
HF_MAX_FILES = 400

HF_DATASET_REPO = os.getenv("HF_DATASET_REPO", "")

MAX_WORKERS = 16

EXCLUDED_URLS = {
    "https://uploads.wikiart.org/Content/images/FRAME-600x480.jpg",
}

_local = threading.local()


def get_session() -> requests.Session:
    """Return a per-thread requests.Session with retry support."""
    if not hasattr(_local, "session"):
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1, max_retries=2)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _local.session = session
    return _local.session


def load_styles() -> dict:
    with open(STATS_FILE) as f:
        return json.load(f)["style"]


def extract_filename(image_url: str) -> str:
    path = urllib.parse.urlparse(image_url).path
    name = path.rstrip("/").split("/")[-1]
    return name.split("!")[0] if "!" in name else name


def collect_tasks(styles: dict) -> list[tuple[str, str]]:
    """Return (url, dest_path) pairs for images that still need downloading."""
    tasks = []
    for entry in Path(ARTWORKS_DIR).glob("*.json"):
        try:
            data = json.loads(entry.read_text())
        except json.JSONDecodeError:
            continue
        style = data.get("style", "")
        image = data.get("image", "")
        if not style or style not in styles or not image:
            continue
        if image in EXCLUDED_URLS:
            continue
        filename = extract_filename(image)
        if not filename:
            continue
        dest = os.path.join(DATASET_DIR, style, filename)
        if not os.path.exists(dest):
            tasks.append((image, dest))
    return tasks


def download(url: str, dest: str) -> tuple[bool, str]:
    if os.path.exists(dest):
        return True, dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        with get_session().get(url, timeout=30, stream=True) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
        return True, dest
    except Exception as exc:
        return False, f"{url} -> {exc}"


def run_download():
    os.makedirs(DATASET_DIR, exist_ok=True)

    styles = load_styles()
    print(f"Loaded {len(styles)} styles")

    print("Scanning artworks JSON files...")
    tasks = collect_tasks(styles)
    print(f"Found {len(tasks)} images to download")

    if not tasks:
        print("Nothing to download.")
        return

    ok = err = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(download, url, dest): (url, dest) for url, dest in tasks}
        with tqdm(total=len(futures), unit="img", dynamic_ncols=True) as bar:
            for future in as_completed(futures):
                success, msg = future.result()
                if success:
                    ok += 1
                else:
                    err += 1
                    tqdm.write(f"FAIL: {msg}")
                bar.set_postfix(ok=ok, err=err)
                bar.update(1)

    print(f"\nDone: {ok} downloaded, {err} failed.")


TRAIN_RATIO = 0.8
VAL_RATIO = 0.1
# TEST_RATIO = 0.1 (remainder)
SPLIT_SEED = 42


def prepare_hf_dataset():
    dataset_dir = Path(DATASET_DIR)
    hf_dir = Path(HF_DATASET_DIR)
    image_exts = {".jpg", ".jpeg", ".png"}
    rng = random.Random(SPLIT_SEED)

    for style in HF_WHITELIST:
        src_dir = dataset_dir / style
        train_dst = hf_dir / "train" / style
        if train_dst.exists():
            print(f"Skip {style}: already exists in hf_dataset/train")
            continue
        if not src_dir.is_dir():
            print(f"Skip {style}: not found in dataset")
            continue

        files = [p for p in src_dir.iterdir() if p.suffix.lower() in image_exts]
        sample = rng.sample(files, min(HF_MAX_FILES, len(files)))

        n = len(sample)
        n_train = int(n * TRAIN_RATIO)
        n_val = int(n * VAL_RATIO)
        splits = {
            "train":      sample[:n_train],
            "validation": sample[n_train: n_train + n_val],
            "test":       sample[n_train + n_val:],
        }

        for split_name, split_files in splits.items():
            dst = hf_dir / split_name / style
            dst.mkdir(parents=True, exist_ok=True)
            for src_file in split_files:
                shutil.copy2(src_file, dst / src_file.name)

        print(f"{style}: train={len(splits['train'])} val={len(splits['validation'])} test={len(splits['test'])}")

    print("prepare_hf_dataset done.")


def run_upload():
    from huggingface_hub import DatasetCard, DatasetCardData, HfApi

    if not HF_DATASET_REPO:
        raise ValueError("HF_DATASET_REPO env var is not set")

    if not os.path.isdir(HF_DATASET_DIR):
        raise FileNotFoundError(f"HF dataset dir not found: {HF_DATASET_DIR}")

    api = HfApi()
    api.create_repo(repo_id=HF_DATASET_REPO, repo_type="dataset", exist_ok=True)

    card = DatasetCard.from_template(
        DatasetCardData(
            language=["en"],
            license="cc-by-nc-4.0",
            pretty_name="Art Genre Classification",
            task_categories=["image-classification"],
            size_categories=["1K<n<10K"],
            tags=["art", "painting", "genre", "wikiart"],
        ),
        template_str=(
            "---\n{{ card_data }}\n---\n\n"
            "# Art Genre Classification Dataset\n\n"
            "Images sampled from WikiArt, organised into 8 genre directories:\n\n"
            + "\n".join(f"- {s}" for s in HF_WHITELIST)
            + f"\n\nUp to {HF_MAX_FILES} images per class.\n"
        ),
    )
    card.push_to_hub(repo_id=HF_DATASET_REPO, repo_type="dataset")
    print("Dataset card pushed.")

    print(f"Uploading {HF_DATASET_DIR} -> {HF_DATASET_REPO} ...")
    api.upload_large_folder(
        repo_id=HF_DATASET_REPO,
        repo_type="dataset",
        folder_path=HF_DATASET_DIR,
    )
    print("Upload complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload dataset/  to HuggingFace Hub after downloading",
    )
    args = parser.parse_args()

    run_download()
    prepare_hf_dataset()

    if args.upload:
        run_upload()
