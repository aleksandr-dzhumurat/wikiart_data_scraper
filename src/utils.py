
import json
import os
import time
import logging
import string
from typing import List, Dict

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
