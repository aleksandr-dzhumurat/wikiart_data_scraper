import os
import json
import requests
import re
from typing import Optional, List, Dict

import pandas as pd
from bs4 import BeautifulSoup

from utils import request_retries, logger


def prepare_pages_list() -> List[str]:
    import string

    BASE_URL = "https://www.wikiart.org/en/Alphabet"
    postfix = 'text-list'

    alphabet = list(string.ascii_lowercase)
    pages_list = [os.path.join(BASE_URL, page_liter, postfix) for page_liter in alphabet]
    return pages_list


def get_artists_pages(result_csv_path: str):
    page_list: List[str] = prepare_pages_list()
    logger.info(result_csv_path)
    
    if not os.path.exists(result_csv_path):
        res = pd.DataFrame([], columns=['artist_name', 'artist_link'])
        for current_alphabet_page in page_list:
            artists_scraper = BeautifulSoup(
                markup=requests.get(current_alphabet_page).content, features="html.parser"
            )
            res = artists_scraper.find(name="div", class_='masonry-text-view masonry-text-view-all')
            artists = res.find_all(name='li')

            res = []
            for artist in artists:
                artist_info = artist.find('a')
                res.append((artist_info['href'], artist_info.get_text()))
            current_page_df = pd.DataFrame(res, columns=['artist_name', 'artist_link'])
            res_df = pd.concat([res_df, current_page_df])
        res_df.to_csv(result_csv_path, index=False)
        logger.info("Artists pages saved to %s: %d rows", result_csv_path, res_df.shape[0])

def extract_artist_wiki(artist_info_scraper: BeautifulSoup) -> str:
    wiki_text = 'Empty wiki'
    try:
        wiki_text = artist_info_scraper.find(id='info-tab-wikipediaArticle', class_='wiki-layout-artist-info-tab').get_text()
        if wiki_text is None:
            raise AttributeError
    except AttributeError:
        pass
    return wiki_text

def extract_artists_info(artist_page_scraper: BeautifulSoup) -> Dict[str, str]:
    res_dict = {}
    artist_info = artist_page_scraper.find(name='div', class_='wiki-layout-artist-info')
    if artist_info is not None:
        artist_properties = artist_info.find_all(name='li')
        if artist_properties is not None:
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


def get_artists_info(input_csv_path: str, output_csv_path: str, output_wikitext_csv_path: str):
    if not os.path.exists(output_csv_path):
        wiki_descriptions = []
        artists_info = []
        cnt = 0
        input_df = pd.read_csv(input_csv_path)
        logger.info('Artists information (wiki, etc) scraping started: %d rows', input_df.shape[0])
        for ind, row in input_df.iterrows():
            artist_page_url = os.path.join('https://www.wikiart.org', row['artist_link'][1:])
            artist_info_page = request_retries(artist_page_url)
            artist_dict = {'ind': ind, 'request_result_success': False}
            if artist_info_page is not None:
                artist_info_scraper = BeautifulSoup(markup=artist_info_page.content, features="html.parser")
                wiki_text = extract_artist_wiki(artist_info_scraper)
                artist_dict.update(extract_artists_info(artist_info_scraper))
                artist_dict.update({'request_result_success': True})
            wiki_text = 'Empty wiki'
            wiki_descriptions.append((ind, row['artist_name'], wiki_text))
            artist_dict.update({'artist_name': row['artist_name'], 'artist_url': artist_page_url})
            artists_info.append(artist_dict)
            # time.sleep(0.25)
            cnt += 1
            if cnt % 500 == 0:
                logger.info('Num artists %d of %d', cnt, input_df.shape[0])
        # saving data
        pd.json_normalize(artists_info).to_csv(output_csv_path, index=False)
        logger.info('wikitexts saved to %s', output_csv_path)
        (
            pd.DataFrame(wiki_descriptions, columns=['ind', 'artist_name', 'wiki_text'])
            .to_csv(output_wikitext_csv_path, index=False)
        )
        logger.info('json saved to %s', output_wikitext_csv_path)
    else:
        logger.info('Artists info already exists files: %s; %s', output_csv_path, output_wikitext_csv_path)

def get_artworks_json(artist_scraper: BeautifulSoup) -> str:
    img_set = artist_scraper.find(
        name='ul', class_='wiki-masonry-container'
    )
    res = ''
    if img_set is not None:
        img_iter = img_set.find_all(name='li')
        if img_iter is not None:
            res = json.dumps([i.find(name='img')['img-source'].replace("'", "") for i in img_iter])
    return res

def get_artwork_by_url(url) -> str:
    artwork_web_page = requests.get(url)
    artwork_scraper = BeautifulSoup(markup=artwork_web_page.content, features="html.parser")
    class_ = 'wiki-layout-artist-image-wrapper'
    artwork_block = artwork_scraper.find(name='div', class_=class_)
    res = artwork_block.find('img')['src']
    return res

def get_artworks_links(artworks_url: str, limit: int = 10):
    artworks_page = request_retries(artworks_url).content
    artworks_array = []
    if artworks_page is not None:
        artwork_links_collector: BeautifulSoup = BeautifulSoup(markup=artworks_page, features="html.parser")
        BASE_URL = "https://www.wikiart.org"
        img_link_set = artwork_links_collector.find(name='ul', class_='painting-list-text')
        if img_link_set is not None:
            img_iter = img_link_set.find_all(name='li')
            exception_occured = False
            artwork_cnt = 0
            for i in img_iter:
                if artwork_cnt > limit:
                    break
                try:
                    link = i.find('a')['href']
                    artwork_url = os.path.join(BASE_URL, link[1:])
                    artworks_array.append(get_artwork_by_url(artwork_url))
                    artwork_cnt += 1
                except Exception as e:
                    if not exception_occured:
                        logger.error('url: %s, error %s', artworks_url, e)
                        exception_occured = True
    return artworks_array


def save_batch(batch_data: List, final_csv_path: str, batches_dir_name: str, batch_num: int, batch_size: int):
    batch_file_name = (
        final_csv_path
        .replace('.csv', f'_{batch_num * batch_size}_{batch_num * batch_size + batch_size}.csv')
        .split('/')[-1]
    )
    batch_file_name = os.path.join(batches_dir_name, batch_file_name)
    (
        pd
        .DataFrame(batch_data, columns=['ind', 'artist_name', 'artworks_url', 'artworks'])
        .to_csv(batch_file_name, index=False)
    )

def collect_batches(batches_dir_name):
    res = pd.DataFrame([], columns=['ind', 'artist_name', 'artworks_url', 'artworks'])
    try: 
        batch_files = os.listdir(batches_dir_name)
        # batches from previous runs
        for batch_file in batch_files:
            res = pd.concat([res, pd.read_csv(os.path.join(batches_dir_name, batch_file))])
    except FileNotFoundError:
        os.makedirs(batches_dir_name)
    return res

def get_photo_urls(input_csv_path, output_csv_path, batches_dir_name, batch_size: int = 30):
    page_postfix = 'all-works/text-list'
    batches_df = collect_batches(batches_dir_name)
    collected_ids = [int(i) for i in batches_df['ind'].values]
    logger.info('Artwork url retrieval started. Num already collected artists: %d', len(collected_ids))
    if not os.path.exists(output_csv_path):
        artworks = []
        cnt = 0
        batch_num = 0
        for ind, row in pd.read_csv(input_csv_path).iterrows():
            cnt += 1
            if ind in collected_ids:
                continue  # skip all collected ids
            logger.info('scraping %d: %s...', ind, row['artist_link'])
            result_url = os.path.join(os.path.join('https://www.wikiart.org', row['artist_link'][1:]), page_postfix)
            # TODO: replace request_retries with backoff
            artworks_links = get_artworks_links(result_url)
            artworks.append((ind, row['artist_name'], result_url, json.dumps(artworks_links)))
            if cnt % batch_size == 0:
                save_batch(artworks, output_csv_path, batches_dir_name, batch_num, batch_size)
                batch_num += 1
                logger.info('Num processed links %d', cnt)
                artworks = []
    logger.info('Artworks data saved')
