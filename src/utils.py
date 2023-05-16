
import json
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
        logger.info('wikitexts saved to %s', output_csv_path)
        pd.DataFrame(wiki_descriptions, columns=['ind', 'artist_name', 'wiki_text']).to_csv(output_wikitext_csv_path, index=False)
        logger.info('json saved to %s', output_wikitext_csv_path)
    else:
        logger.info('Artists info already exists')

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

def get_artworks_links(artwork_links_collector: BeautifulSoup):
    BASE_URL = "https://www.wikiart.org"
    img_link_set = artwork_links_collector.find(name='ul', class_='painting-list-text')
    # img_set = artist_works_scraper.find(name='div', class_='wiki-masonry-container ng-isolate-scope')
    img_iter = img_link_set.find_all(name='li')
    artworks_array = []
    exception_occured = False
    for i in img_iter:
        try:
            link = i.find('a')['href']
            artwork_url = os.path.join(BASE_URL, link[1:])
            artworks_array.append(get_artwork_by_url(artwork_url))
        except Exception as e:
            if not exception_occured:
                logger.error('%s', e)
                exception_occured = True
    return artworks_array

def get_photo_urls(input_csv_path, output_csv_path):
    # page_postfix = "all-works#!#filterName:all-paintings-chronologically,resultType:masonry"
    batch_size = 30
    page_postfix = 'all-works/text-list'
    root_data_dir = '/srv/data/data_batches'
    batch_files = os.listdir(root_data_dir)
    collected_ids = []
    for batch_file in batch_files:
        batch_df = pd.read_csv(os.path.join(root_data_dir, batch_file))
        collected_ids += [int(i) for i in batch_df['ind'].values]
    logger.info('Num collected artists: %d', len(collected_ids))
    if not os.path.exists(output_csv_path):
        logger.info('Artwork url retrieval started')
        artworks = []
        cnt = 0
        batch_num = 0
        for ind, row in pd.read_csv(input_csv_path).iterrows():
            if ind in collected_ids:
                logger.info('%d: %s already collected', ind, row['artist_link'])
                continue
            artist_page_url = os.path.join('https://www.wikiart.org', row['artist_link'][1:])
            result_url = os.path.join(artist_page_url, page_postfix)
            artist_work_links_web_page = request_retries(result_url)
            if artist_work_links_web_page is None:
                artworks_links = []
            else:
                artist_works_scraper = BeautifulSoup(markup=artist_work_links_web_page.content, features="html.parser")
                artworks_links = get_artworks_links(artist_works_scraper)
            if len(artworks_links) == 0:
                logger.error('Empty artwork list for %s', result_url)
            artworks_json = json.dumps(artworks_links)
            artworks.append((ind, row['artist_name'], result_url, artworks_json))
            cnt += 1
            if cnt % batch_size == 0:
                batch_file_name = output_csv_path.replace('/data/', '/data/data_batches/').replace('.csv', f'_{batch_num * batch_size}_{batch_num * batch_size + batch_size}.csv')
                batch_num += 1
                (
                    pd
                    .DataFrame(artworks, columns=['ind', 'artist_name', 'artworks_url', 'artworks'])
                    .to_csv(batch_file_name, index=False)
                )
                logger.info('Num links %d', cnt)
                artworks = []
    logger.info('Artworks data saved')
