import os
import logging
import tarfile
import shutil
import hashlib
from pathlib import Path

import yaml

logger = logging.getLogger('my_logger')
logging.basicConfig(format='%(asctime)s: %(message)s', level=logging.INFO)

def load_config() -> dict:
    config_path = os.getenv("CONFIG_PATH", "config.yml")
    with open(config_path, "r") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
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
    artifact_filename  = f"{config['data_version']}_{artifact_name}"
    return os.path.join(config['root_data_dir'], artifact_filename)

def init_nltk():
    import nltk
    
    config['root_data_dir']
    nltk_data_dir = os.path.join('/srv/data', 'nltk_data')
    if not os.path.exists(nltk_data_dir):
        os.makedirs(nltk_data_dir)
    logger.info('NLTK dir %s created', nltk_data_dir)
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
