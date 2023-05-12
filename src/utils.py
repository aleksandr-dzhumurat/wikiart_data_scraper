import os
import time
import logging
import string
from typing import List, Dict

import pandas as pd
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger('my_logger')

logging.basicConfig(format='%(asctime)s: %(message)s', level=logging.INFO)

def prepare_pages_list() -> List[str]:
    import string

    BASE_URL = "https://www.wikiart.org/en/Alphabet"
    postfix = 'text-list'

    alphabet = list(string.ascii_lowercase)
    pages_list = [os.path.join(BASE_URL, page_liter, postfix) for page_liter in alphabet]
    return pages_list
        

def get_artists_pages(result_csv_path: str):
    page_list: List[str] = prepare_pages_list()
    
    if not os.path.exists(result_csv_path):
        res_df = None
        for current_alphabet_page in page_list:
            web_page = requests.get(current_alphabet_page)

            artists_scraper = BeautifulSoup(markup=web_page.content, features="html.parser")
            res = artists_scraper.find(name="div", class_='masonry-text-view masonry-text-view-all')
            artists = res.find_all(name='li')

            cnt = 0
            res = []
            for artist in artists:
                cnt += 1
                artist_link = artist.find('a')['href']
                artist_name = artist.find('a').get_text()
                res.append((artist_name, artist_link))
            current_page_df = pd.DataFrame(res, columns=['artist_name', 'artist_link'])
            if res_df is None:
                res_df = current_page_df
            else:
                res_df = pd.concat([res_df, current_page_df])

        res_df.to_csv(result_csv_path, index=False)
        logger.info("Saved to %s: %d rows", result_csv_path, res_df.shape[0])

def extract_artists_info(artist_page_scraper: BeautifulSoup) -> Dict[str, str]:
    artist_info = artist_page_scraper.find(name='div', class_='wiki-layout-artist-info')
    artist_properties = artist_info.find_all(name='li')

    res_dict = {}
    for prop in artist_properties:
        prop_html = prop.find(name='s')
        if prop_html is not None and prop_html.get_text() is not None:
            property_name = prop_html.get_text().strip().lower().replace(':', '')
            if property_name != 'share':
                prop_values = ' '.join(set(
                    [i.get_text().strip().replace('\n', ' ') for i in prop.find_all(name='span')] +
                    [i.get_text().strip().replace('\n', ' ') for i in prop.find_all(name='a')]
                    )
                )
                res_dict.update({property_name: prop_values})
    res_dict['artist_pic'] = (
        artist_page_scraper
        .find(name='div', class_='wiki-layout-artist-image-wrapper')
        .find(name='img')['src']
    )
    return res_dict

def request_retries(url, num_retries: int = 3):
    res = None
    for i in range(num_retries):
        try:
            res = requests.get(url)
            return res
        except requests.exceptions.ConnectionError as e:
            logger.error(url, e)
            time.sleep(1)
    return res


def get_artists_info(input_csv_path: str, output_csv_path: str, output_wikitext_csv_path: str):
    # wiki_text = artist_scraper.find(id='info-tab-wikipediaArticle', class_='wiki-layout-artist-info-tab').get_text()
    if not os.path.exists(output_csv_path):
        wiki_descriptions = []
        artists_info = []
        cnt = 0
        for ind, row in pd.read_csv(input_csv_path).iterrows():
            # print(ind, row['artist_name'], )
            artist_page_url = os.path.join('https://www.wikiart.org', row['artist_link'][1:])
            artist_info_page = request_retries(artist_page_url)
            artist_dict = {'request_result_success': False}
            wiki_text = ''
            if artist_info_page is not None:
                artist_info_scraper = BeautifulSoup(markup=artist_info_page.content, features="html.parser")
                try:
                    wiki_text = artist_info_scraper.find(id='info-tab-wikipediaArticle', class_='wiki-layout-artist-info-tab').get_text()
                    if wiki_text is None:
                        wiki_text = ''
                except AttributeError:
                    logger.error('Wiki text error %s', artist_page_url)
                # artist_info
                artist_dict.update(extract_artists_info(artist_info_scraper))
                artist_dict.update({'request_result_success': True})
            wiki_descriptions.append((ind, row['artist_name'], wiki_text))
            artist_dict.update({'artist_name': row['artist_name'], 'artist_url': artist_page_url})
            artists_info.append(artist_dict)
            # time.sleep(0.25)
            cnt += 1
            if cnt % 500 == 0:
                logger.info('Num artists %d', cnt)
        pd.json_normalize(artists_info).to_csv(output_csv_path, index=False)
        pd.DataFrame(wiki_descriptions, columns=['ind', 'artist_name', 'wiki_text']).to_csv(output_wikitext_csv_path, index=False)
        logger.info('json saved')
    else:
        logger.info('Artists info already exists')
