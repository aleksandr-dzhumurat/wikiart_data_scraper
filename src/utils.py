import hashlib
import json
import logging
import os
import shutil
import tarfile
import time
from pathlib import Path

import requests
import yaml

logger = logging.getLogger('my_logger')
logging.basicConfig(format='%(asctime)s: %(message)s', level=logging.INFO)

def load_config() -> dict:
    default_config_path = os.path.join(os.path.dirname(__file__), "config.yml")
    config_path = os.getenv("CONFIG_PATH", default_config_path)
    with open(config_path, "r") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    config['root_data_dir'] = os.getenv("ROOT_DATA_DIR", config['root_data_dir'])
    os.makedirs(config['root_data_dir'], exist_ok=True)
    config['data_version_dir'] = os.path.join(config['root_data_dir'], config['data_version'])
    os.makedirs(config['data_version_dir'], exist_ok=True)
    return config


config = load_config()


def extract_tar_gz(archive_path, output_directory):
    """
    # Example usage:
    archive_path = "archive.tar.gz"
    output_directory = "data"

    extract_tar_gz(archive_path, output_directory)
    """
    if not os.path.exists(archive_path):
        raise FileNotFoundError(f"Archive file '{archive_path}' not found.")

    # Create the output directory if it doesn't exist
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

    # Extract the contents of the tar.gz archive
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(output_directory)


def create_tar_gz(directory_path, output_path):
    # Check if the directory exists
    if not os.path.exists(directory_path):
        raise FileNotFoundError(f"Directory '{directory_path}' not found.")

    with tarfile.open(output_path, 'w:gz') as archive:
        # Walk through the directory and add files to the archive
        for root, _, files in os.walk(directory_path):
            for file in files:
                file_path = os.path.join(root, file)
                # Archive only the files without their parent directory
                archive.add(file_path, arcname=os.path.relpath(file_path, directory_path))


def artifact_path(artifact_name: str):
    return os.path.join(config['data_version_dir'], artifact_name)

def init_nltk():
    import nltk

    root_data_dir = os.getenv("ROOT_DATA_DIR", config['root_data_dir'])
    nltk_data_dir = os.path.join(root_data_dir, 'nltk_data')
    os.makedirs(nltk_data_dir, exist_ok=True)
    logger.info('NLTK dir %s ready', nltk_data_dir)
    nltk.download('stopwords', download_dir=nltk_data_dir)
    nltk.data.path.append(nltk_data_dir)

def generate_files():
    basepath = '/srv/src'
    result = []
    for fname in os.listdir(basepath):
        path = os.path.join(basepath, fname)
        if os.path.isdir(path):
            # skip directories
            continue
        result.append(os.path.join(basepath, fname))
    return result

def files_version() -> bytes:
    hash = hashlib.md5()
    for fn in generate_files():
        try:
            hash.update(Path(fn).read_bytes())
        except IsADirectoryError:
            pass
    return str(hash.hexdigest())[:8]

def prepare_service_data():
    service_file_names = [
        'tags_db.csv.gz',
        'content_db.csv.gz',
        'exhibitions_db.csv.gz'
    ]
    result_data_dir = artifact_path('service_data')
    if os.path.exists(result_data_dir):
        postfix = files_version()
        os.rename(result_data_dir, result_data_dir.replace('service_data', f'{postfix}_service_data'))
    os.makedirs(result_data_dir)
    for f in service_file_names:
        source_file = artifact_path(f)
        shutil.copyfile(source_file, os.path.join(result_data_dir, f))
        logger.info('Copied to %s', os.path.join(result_data_dir, f))
    logger.info('Data collected to %s', result_data_dir)
    create_tar_gz(result_data_dir, f'{result_data_dir}.tar.gz'.replace(f"{config['data_version']}_", ''))

def write_jsonl(records: list[dict], output_path: str):
    with open(output_path, 'w', encoding='utf-8') as file:
        file.writelines(json.dumps(record, ensure_ascii=False) + '\n' for record in records)

def read_jsonl(input_path: str) -> list[dict]:
    result = []
    with open(input_path, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            result.append(json.loads(line))
    return result

def request_retries(url, num_retries: int = 3):
    # TODO: use 'backoff' module  instead of this
    res = None
    for _ in range(num_retries):
        try:
            res = requests.get(url)
            if res.status_code == 200:
                return res
            else:
                print("Failed to retrieve webpage %s. Status code: %s" % (url, res.status_code))
        except requests.exceptions.ConnectionError as e:
            logger.error('Failed to retrieve webpage %s\n%s', url, e)
            time.sleep(0.25)
    return res

def get_html(url, html_dir_name='', root_data_dir = config['data_version_dir']):
    html_dir = os.path.join(root_data_dir, html_dir_name)
    os.makedirs(html_dir, exist_ok=True)
    path_parts = [part for part in url.split('/') if part]
    # WikiArt URLs are usually /en/<artist-slug>/... ; use artist slug to keep cache files unique per artist.
    artist_slug = path_parts[3] if len(path_parts) > 3 and path_parts[2] == 'en' else ''
    page_slug = path_parts[-1].split('.')[0]
    html_file_name = f"{artist_slug}_{page_slug}" if artist_slug else page_slug
    html_path = os.path.join(html_dir, f"{html_file_name}.html")
    if os.path.exists(html_path):
        with open(html_path, 'r', encoding='utf-8') as file:
            html_content = file.read()
    else:
        html_content = request_retries(url)
        html_content = html_content.text  # `.content` ?
        with open(html_path, 'w', encoding='utf-8') as file:
            file.write(html_content)
    return html_content

def n_gram_split(input_str: str):
  potential_tags = []
  tokens = input_str.split(' ')
  for window_size in range(1,4):
    start = 0
    while start + window_size < len(tokens) + 1:
      potential_tag = ' '.join(tokens[start: start+window_size])
      potential_tags.append(potential_tag)
      start += 1
  return potential_tags
