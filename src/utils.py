
import json
import os
import time
import logging
import string
from typing import List, Dict
import shutil

import pandas as pd
import requests
import yaml
from bs4 import BeautifulSoup

logger = logging.getLogger('my_logger')
logging.basicConfig(format='%(asctime)s: %(message)s', level=logging.INFO)

def load_config() -> dict:
    config_path = os.getenv("CONFIG_PATH", "config.yml")
    with open(config_path, "r") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    return config

def request_retries(url, num_retries: int = 3):
    # TODO: use 'backoff' module  instead of this
    res = None
    for i in range(num_retries):
        try:
            res = requests.get(url)
            return res
        except requests.exceptions.ConnectionError as e:
            logger.error('%s\n%s', url, e)
            time.sleep(1)
    return res

config = load_config()

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

def prepare_service_data():
    service_file_names = [
        'tags_db.csv',
        'content_db.csv',
        'exhibitions_db.csv'
    ]
    result_data_dir = artifact_path('service_data')
    if not os.path.exists(result_data_dir):
        os.makedirs(result_data_dir)
    for f in service_file_names:
        source_file = artifact_path(f)
        shutil.copyfile(source_file, os.path.join(result_data_dir, f))
        logger.info('Copied to %s', os.path.join(result_data_dir, f))
    logger.info('Data collected to %s', result_data_dir)
