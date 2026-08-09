import json
import multiprocessing
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover
    tqdm = None

from utils import (
    config,
    get_html,
    init_nltk,
    logger,
    n_gram_split,
)

BASE_URL = "https://www.wikiart.org"


@dataclass
class Artist:
    artist_name: str
    artist_link: str
    artist_url: str
    is_popular: bool = False


@dataclass
class Artwork:
    url: str
    artist_link: str = None
    local_html_path: str = None
    title: str = None
    tags: str = None


def prepare_pages_list() -> list[str]:
    import string

    alphabet_url = f"{BASE_URL}/en/Alphabet"
    postfix = 'text-list'

    alphabet = list(string.ascii_lowercase)
    pages_list = [os.path.join(alphabet_url, page_liter, postfix) for page_liter in alphabet]
    return pages_list

def get_popular_artists() -> list[str]:
    popular_page = get_html('https://www.wikiart.org/en/popular-artists/text-list', html_dir_name='popular')
    soup = BeautifulSoup(markup=popular_page, features="html.parser")
    popular_div = soup.find(name='div', class_='masonry-text-view masonry-text-view-all')
    if popular_div is None:
        logger.warning('Could not find popular artists list')
        return []
    artists = popular_div.find_all(name='li')
    popular_urls = []
    for artist in artists:
        a_tag = artist.find('a')
        if a_tag and a_tag.get('href'):
            popular_urls.append(f"{BASE_URL}{a_tag['href']}")
    logger.info('Found %d popular artists', len(popular_urls))
    return popular_urls


def get_artists_pages(result_csv_path: str, popular_artists: list[str] | None = None):
    if popular_artists is None:
        popular_artists = []
    popular_set = set(popular_artists)
    page_list: list[str] = prepare_pages_list()
    if not os.path.exists(result_csv_path):
        all_rows_list = []
        for current_alphabet_page in page_list:
            artists_scraper = BeautifulSoup(
                markup=requests.get(current_alphabet_page).content, features="html.parser"
            )
            res = artists_scraper.find(name="div", class_='masonry-text-view masonry-text-view-all')
            artists = res.find_all(name='li')
            logger.info('Current page: %s, num artists: %d', current_alphabet_page, len(artists))
            rows_list = []
            for artist in artists:
                artist_info = artist.find('a')
                artist_url = f"{BASE_URL}{artist_info['href']}"
                rows_list.append(Artist(
                    artist_name=artist_info.get_text(),
                    artist_link=artist_info['href'],
                    artist_url=artist_url,
                    is_popular=artist_url in popular_set,
                ))
            all_rows_list.extend(rows_list)
        res_df = pd.DataFrame([asdict(a) for a in all_rows_list])
        res_df.to_csv(result_csv_path, index=False)
    else:
        res_df = pd.read_csv(result_csv_path)
    logger.info("Artists pages saved to %s: %d rows", result_csv_path, res_df.shape[0])

def extract_artist_wiki(artist_info_scraper: BeautifulSoup) -> str:
    wiki_text = 'Empty wiki'
    try:
        wiki_text = artist_info_scraper.find(id='info-tab-wikipediaArticle', class_='wiki-layout-artist-info-tab').get_text()
        if wiki_text is None:
            raise AttributeError
    except AttributeError:
        pass
    return wiki_text.replace('\n', ' ')

def get_tags(row):
    MOVEMENT_BOOST = 3

    movement_tags = [i.lower().strip() for i in row['artist_movement'].split('|') if i.strip()]
    field_tags = [i.lower().strip() for i in row['field'].split(',') if i.strip()]
    res = '|'.join(movement_tags * MOVEMENT_BOOST + field_tags)
    return res

def extract_artists_info(artist_page_scraper: BeautifulSoup) -> dict[str, str]:
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
                        links = prop.find_all(name='a')
                        if links:
                            prop_values = ', '.join(
                                i.get_text().strip().replace('\n', ' ') for i in links
                            )
                        else:
                            prop_values = prop.get_text().strip().replace('\n', ' ')
                            # Remove the label prefix (e.g. "Art Movement:")
                            label = prop_html.get_text().strip()
                            if prop_values.startswith(label):
                                prop_values = prop_values[len(label):].strip()
                        res_dict.update({property_name: prop_values})
            res_dict['artist_pic'] = (
                artist_page_scraper
                .find(name='div', class_='wiki-layout-artist-image-wrapper')
                .find(name='img')['src']
            )
    res_dict['artist_field'] = process_field(res_dict.get('field', ''))
    res_dict['artist_movement'] = process_art_movement(res_dict.get('art movement', ''))
    return res_dict

def process_field(raw_str):
    if not isinstance(raw_str, str):
        return ''
    try:
        res = ' '.join(sorted(set([
            i.strip().replace(',', '')
            for i in raw_str.split(' ')
            if len(i.strip().replace(',', '')) > 0]))
        )
    except Exception as e:
        logger.error('Error occurred while processing raw string: %s', raw_str)
        raise e
    return res

def get_artists_info(input_csv_path: str, output_csv_path: str, output_wikitext_csv_path: str):
    if not os.path.exists(output_csv_path):
        wiki_descriptions = []
        artists_info = []
        input_df = pd.read_csv(input_csv_path)
        logger.info('Artists information (wiki, etc) scraping started: %d rows', input_df.shape[0])
        for ind, row in input_df.iterrows():
            logger.info('[%d/%d] Fetching artist: %s', ind + 1, input_df.shape[0], row['artist_name'])
            artist_info_page = get_html(row['artist_url'], 'artists_raw_html')
            artist_dict = {
                'artist_name': row['artist_name'], 'artist_link': row['artist_link'],
                'artist_url': row['artist_url'], 'request_result_success': False
            }
            wiki_text = 'Empty wiki'
            if artist_info_page is not None:
                artist_info_scraper = BeautifulSoup(markup=artist_info_page, features="html.parser")
                wiki_text = extract_artist_wiki(artist_info_scraper)
                artist_info = extract_artists_info(artist_info_scraper)
                artist_dict.update(artist_info)
                artist_dict.update({'request_result_success': True})
                logger.info('[%d/%d] OK: %s', ind + 1, input_df.shape[0], row['artist_name'])
            else:
                logger.warning('[%d/%d] FAILED (no page): %s', ind + 1, input_df.shape[0], row['artist_name'])
            wiki_descriptions.append((row['artist_link'], wiki_text))
            artists_info.append(artist_dict)
            if ind % 100 == 0:
                logger.info('Progress: %d of %d artists processed', ind, input_df.shape[0])
        artists_info_df = pd.json_normalize(artists_info)
        artists_info_df.to_csv(output_csv_path, index=False)
        logger.info('authors info saved to %s', output_csv_path)
        (
            pd.DataFrame(wiki_descriptions, columns=['artist_link', 'wiki_text'])
            .to_csv(output_wikitext_csv_path, index=False)
        )
        logger.info('wiki texts saved to %s', output_wikitext_csv_path)
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

def extract_artwork_description(filepath: str) -> dict:
    with open(filepath, 'r', encoding='utf-8') as file:
        artwork_page = file.read()

    artwork_scraper = BeautifulSoup(markup=artwork_page, features="html.parser")
    artwork_info = artwork_scraper.find(name='div', class_='wiki-layout-artist-info wiki-layout-artwork-info')

    if artwork_info is None:
        raise ValueError(f'Could not find artwork info block in {filepath}')

    title = ''
    artist = ''
    artist_link = ''

    title_node = artwork_info.find(name='h1')
    if title_node is not None:
        title = title_node.get_text(strip=True)

    artist_node = artwork_info.find(name='h2')
    if artist_node is not None:
        artist_a = artist_node.find(name='a')
        artist = artist_a.get_text(strip=True) if artist_a else artist_node.get_text(strip=True)
        if artist_a and artist_a.get('href'):
            artist_link = artist_a['href']

    details = artwork_info.find(name='article')

    def extract_detail_value(label: str) -> str:
        if details is None:
            return ''
        for li in details.find_all(name='li'):
            label_node = li.find(name='s')
            if label_node is None:
                continue
            normalized_label = label_node.get_text(strip=True).lower().rstrip(':')
            if normalized_label != label.lower().rstrip(':'):
                continue
            li_copy = BeautifulSoup(str(li), features="html.parser")
            for tag in li_copy.find_all(name='s'):
                tag.extract()
            return li_copy.get_text(' ', strip=True)
        return ''

    date = extract_detail_value('date').replace('c. ', 'c.')
    style = extract_detail_value('style')
    genre = extract_detail_value('genre')
    location_text = extract_detail_value('location')

    venue = ''
    city = ''
    country = ''
    if location_text:
        location_parts = [part.strip() for part in location_text.split(',') if part.strip()]
        if len(location_parts) > 0:
            venue = location_parts[0]
        if len(location_parts) > 1:
            city = location_parts[1]
        if len(location_parts) > 2:
            country = ', '.join(location_parts[2:])

    image = ''
    image_node = artwork_info.find(name='img', attrs={'itemprop': 'image'})
    if image_node is not None:
        image = image_node.get('src', '')

    image_url = ''
    artwork_block = artwork_scraper.find(name='div', class_='wiki-layout-artist-image-wrapper')
    if artwork_block is not None:
        img_tag = artwork_block.find('img')
        if img_tag is not None:
            image_url = img_tag.get('src', '')

    images = []
    variants_container = artwork_info.find(name='ul', class_='image-variants-container')
    if variants_container is not None:
        for a_tag in variants_container.find_all(name='a', attrs={'data-image-url': True}):
            url = a_tag['data-image-url'].strip()
            if url:
                images.append(url)

    return {
        'title': title,
        'artist': artist,
        'artist_link': artist_link,
        'date': date,
        'style': style,
        'genre': genre,
        'location': {
            'venue': venue,
            'city': city,
            'country': country,
        },
        'image': image,
        'image_url': image_url,
        'images': images,
    }

def _process_artwork_file(args: tuple[str, str]) -> tuple[str, str]:
    """Worker function for multiprocessing. Returns (status, filename).
    status is one of: 'processed', 'skipped', 'failed'
    """
    html_filepath, output_json_dir = args
    html_filename = os.path.basename(html_filepath)
    json_filename = f"{os.path.splitext(html_filename)[0]}.json"
    json_filepath = os.path.join(output_json_dir, json_filename)

    if os.path.exists(json_filepath):
        return ('skipped', html_filename)

    try:
        artwork_description = extract_artwork_description(html_filepath)
        with open(json_filepath, 'w', encoding='utf-8') as file:
            json.dump(artwork_description, file, ensure_ascii=False, indent=4)
        return ('processed', html_filename)
    except Exception as e:
        logger.warning('Failed to extract artwork description from %s: %s', html_filename, e)
        return ('failed', html_filename)

def extract_artworks_descriptions(
    raw_html_dir: str,
    output_json_dir: str,
    num_workers: int,
):

    os.makedirs(output_json_dir, exist_ok=True)

    if not os.path.exists(raw_html_dir):
        logger.warning('Raw artworks html directory does not exist: %s', raw_html_dir)
        return

    html_files = sorted([
        str(p) for p in Path(raw_html_dir).iterdir()
        if p.suffix == '.html'
    ])

    logger.info('Artwork description extraction started. Num html files: %d, workers: %d', len(html_files), num_workers)

    processed_cnt = 0
    skipped_cnt = 0
    failed_cnt = 0

    worker_args = [(filepath, output_json_dir) for filepath in html_files]

    with multiprocessing.Pool(processes=num_workers) as pool:
        results = pool.imap_unordered(_process_artwork_file, worker_args)

        if tqdm is not None:
            results = tqdm(results, total=len(html_files), desc='Processing artworks_raw_html', unit='file')

        for status, _ in results:
            if status == 'processed':
                processed_cnt += 1
            elif status == 'skipped':
                skipped_cnt += 1
            else:
                failed_cnt += 1

            if tqdm is not None:
                results.set_postfix(processed=processed_cnt, skipped=skipped_cnt, failed=failed_cnt)

    logger.info(
        'Artwork description extraction finished. processed=%d skipped=%d failed=%d output_dir=%s',
        processed_cnt,
        skipped_cnt,
        failed_cnt,
        output_json_dir,
    )

def build_artworks_json_descriptive_stats(
    json_dir: str,
    stats_output_path: str,
):

    if not os.path.exists(json_dir):
        logger.warning('Artwork json directory does not exist: %s', json_dir)
        return

    json_files = sorted([
        p.name for p in Path(json_dir).iterdir()
        if p.suffix == '.json'
    ])

    total_files = len(json_files)
    if total_files == 0:
        stats = {
            'total_json_files': 0,
            'json_with_any_empty_description': 0,
            'share_json_with_any_empty_description': 0.0,
            'json_with_empty_location': 0,
            'share_json_with_empty_location': 0.0,
            'empty_field_counts': {
                'title': 0,
                'artist': 0,
                'date': 0,
                'style': 0,
                'genre': 0,
                'location_venue': 0,
                'location_city': 0,
                'location_country': 0,
            },
            'invalid_json_files': 0,
            'genre': {},
            'style': {},
        }
        with open(stats_output_path, 'w', encoding='utf-8') as file:
            json.dump(stats, file, ensure_ascii=False, indent=4)
        logger.info('No artwork json files found. Stats saved to %s', stats_output_path)
        return

    empty_field_counts = {
        'title': 0,
        'artist': 0,
        'date': 0,
        'style': 0,
        'genre': 0,
        'location_venue': 0,
        'location_city': 0,
        'location_country': 0,
    }

    any_empty_description_cnt = 0
    empty_location_cnt = 0
    invalid_json_files = 0
    genre_counts: dict[str, int] = {}
    style_counts: dict[str, int] = {}

    for filename in json_files:
        filepath = os.path.join(json_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as file:
                item = json.load(file)
        except Exception as e:
            invalid_json_files += 1
            logger.warning('Invalid json file %s: %s', filepath, e)
            continue

        title = (item.get('title') or '').strip()
        artist = (item.get('artist') or '').strip()
        date = (item.get('date') or '').strip()
        style = (item.get('style') or '').strip()
        genre = (item.get('genre') or '').strip()
        location = item.get('location') if isinstance(item.get('location'), dict) else {}
        location_venue = (location.get('venue') or '').strip()
        location_city = (location.get('city') or '').strip()
        location_country = (location.get('country') or '').strip()

        field_to_value = {
            'title': title,
            'artist': artist,
            'date': date,
            'style': style,
            'genre': genre,
            'location_venue': location_venue,
            'location_city': location_city,
            'location_country': location_country,
        }

        has_any_empty = False
        for field_name, value in field_to_value.items():
            if not value:
                empty_field_counts[field_name] += 1
                has_any_empty = True

        if has_any_empty:
            any_empty_description_cnt += 1

        if not location_venue and not location_city and not location_country:
            empty_location_cnt += 1

        if genre:
            genre_counts[genre] = genre_counts.get(genre, 0) + 1
        if style:
            style_counts[style] = style_counts.get(style, 0) + 1

    top_genres = dict(sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:20])
    top_styles = dict(sorted(style_counts.items(), key=lambda x: x[1], reverse=True)[:20])

    denominator = max(1, total_files)
    stats = {
        'total_json_files': total_files,
        'json_with_any_empty_description': any_empty_description_cnt,
        'share_json_with_any_empty_description': round(any_empty_description_cnt / denominator, 6),
        'json_with_empty_location': empty_location_cnt,
        'share_json_with_empty_location': round(empty_location_cnt / denominator, 6),
        'empty_field_counts': empty_field_counts,
        'invalid_json_files': invalid_json_files,
        'genre': top_genres,
        'style': top_styles,
    }

    with open(stats_output_path, 'w', encoding='utf-8') as file:
        json.dump(stats, file, ensure_ascii=False, indent=4)

    logger.info('Artwork json descriptive stats saved to %s', stats_output_path)

def get_artwork(artwork_web_page) -> Artwork:
    if artwork_web_page is None:
        return None
    artwork_scraper = BeautifulSoup(markup=artwork_web_page, features="html.parser")
    class_ = 'wiki-layout-artist-image-wrapper'
    artwork_block = artwork_scraper.find(name='div', class_=class_)
    image_url = artwork_block.find('img')['src']
    return Artwork(img_url=image_url)

def get_artworks_info(img_iter, target_html_dir: str, limit: int = 10) -> list[Artwork]:
    artwork_cnt = 0
    failed_cnt = 0
    artworks_list = []
    for i in img_iter:
        if artwork_cnt >= limit:
            break
        try:
            artwork_url = f"{BASE_URL}{i.find('a')['href']}"
            artwork_web_page = get_html(artwork_url, target_html_dir)
            artwork = get_artwork(artwork_web_page)
            artworks_list.append(artwork)
            artwork_cnt += 1
        except Exception:
            failed_cnt += 1
    if failed_cnt > 0:
        logger.warning('url: %d/%d artworks failed', failed_cnt, artwork_cnt + failed_cnt)
    return artworks_list

def get_artworks_list_page(artist_url: str, target_html_dir: str = 'art_links_lists') -> list[Artwork]:
    # artworks_page = request_retries(artworks_url).content
    page_postfix = 'all-works/text-list'
    artworks_url = f"{artist_url}/{page_postfix}"
    artworks_page = get_html(artworks_url, html_dir_name=target_html_dir)
    if artworks_page is None:
        logger.error('Failed to retrieve artworks page for URL: %s', artworks_url)
    return artworks_page

# def extract_artworks_list(artworks_page, target_html_dir) -> list[Artwork]:
#     artworks_array = []
#     artwork_links_collector: BeautifulSoup = BeautifulSoup(markup=artworks_page, features="html.parser")
#     img_link_set = artwork_links_collector.find(name='ul', class_='painting-list-text')
#     if img_link_set is not None:
#         img_iter = img_link_set.find_all(name='li')
#         artworks_array = get_artworks_info(img_iter, target_html_dir=target_html_dir, limit=limit)
#     return artworks_array

# def save_batch(batch_data: list[dict], final_output_path: str, batches_dir_name: str, batch_num: int, batch_size: int):
#     output_base_name, output_ext = os.path.splitext(os.path.basename(final_output_path))
#     batch_file_name = f'{output_base_name}_{batch_num * batch_size}_{batch_num * batch_size + batch_size}{output_ext}'
#     batch_file_name = os.path.join(batches_dir_name, batch_file_name)
#     write_jsonl(batch_data, batch_file_name)
#     logger.info('Saved to %s', batch_file_name)

# def collect_batches(batches_dir_name: str,  overwrite: bool = False):
#     logger.info('Collecting batches from %s', batches_dir_name)
#     res = pd.DataFrame([], columns=['ind', 'artist_name', 'artworks'])
#     try: 
#         batch_files = os.listdir(batches_dir_name)
#         # batches from previous runs
#         for batch_file in batch_files:
#             batch_path = os.path.join(batches_dir_name, batch_file)
#             if batch_file.endswith('.jsonl'):
#                 res = pd.concat([res, pd.DataFrame(read_jsonl(batch_path))], ignore_index=True)
#             elif batch_file.endswith('.csv'):
#                 # Backward compatibility with old batch format.
#                 old_batch = pd.read_csv(batch_path)
#                 old_batch = old_batch[['ind', 'artist_name', 'artworks']]
#                 old_batch['artworks'] = old_batch['artworks'].apply(
#                     lambda x: json.loads(x) if isinstance(x, str) and x.strip().startswith('[') else []
#                 )
#                 res = pd.concat([res, old_batch], ignore_index=True)
#         if res.shape[0] > 0 and overwrite:
#             for batch_file in batch_files:
#                 logger.info('removing %s', batch_file)
#                 os.remove(os.path.join(batches_dir_name, batch_file))
#         logger.info('Batches collected, num rows: %d', res.shape[0])
#     except FileNotFoundError:
#         os.makedirs(batches_dir_name)
#     return res

# def consolidate_batches(batches_df, batches_dir_name, output_jsonl_path):
#     min_id, max_id = batches_df['ind'].min(), batches_df['ind'].max()
#     output_name, output_ext = os.path.splitext(output_jsonl_path)
#     result_f_name = f"{os.path.basename(output_name)}_{min_id}_{max_id}{output_ext}"
#     batch_files = os.listdir(batches_dir_name)
#     for batch_file in batch_files:
#         logger.info('removing %s', batch_file)
#         os.remove(os.path.join(batches_dir_name, batch_file))
#     logger.info('Saving to %s', os.path.join(batches_dir_name, result_f_name))
#     write_jsonl(
#         batches_df.sort_values(by='ind')[['ind', 'artist_name', 'artworks']].to_dict(orient='records'),
#         os.path.join(batches_dir_name, result_f_name)
#     )

# def scrape_artist_artworks(input_csv_path, output_jsonl_path, batches_dir_name, target_html_dir, collected_ids, batch_size):
#     artworks = []
#     cnt = 0
#     batch_num = 0
#     for ind, row in pd.read_csv(input_csv_path).iterrows():
#         cnt += 1
#         if ind in collected_ids:
#             if cnt % batch_size == 0:
#                 batch_num += 1
#             continue  # skip all collected ids
#         logger.info('scraping %d: %s...', ind, row['artist_link'])
#         artworks = get_artworks(row['artist_url'], target_html_dir=target_html_dir)
#         artworks.append({'ind': int(ind), 'artist_name': row['artist_name'], 'artworks': [a.img_url for a in artworks]})
#         if cnt % batch_size == 0:
#             save_batch(artworks, output_jsonl_path, batches_dir_name, batch_num, batch_size)
#             batch_num += 1
#             logger.info('Num processed links %d', cnt)
#             artworks = []
#     if artworks:
#         save_batch(artworks, output_jsonl_path, batches_dir_name, batch_num, batch_size)

# def scrape_artworks(input_csv_path, output_jsonl_path, batches_dir_name, target_html_dir: str, batch_size: int = 30):
#     batches_df = collect_batches(batches_dir_name)
#     if batches_df.shape[0] > 0:
#         logger.info('Removing files...')
#         consolidate_batches(batches_df, batches_dir_name, output_jsonl_path)
#     collected_ids = [int(i) for i in batches_df['ind'].values]
#     logger.info('Artwork url retrieval started. Num already collected artists: %d', len(collected_ids))
#     if not os.path.exists(output_jsonl_path):
#         scrape_artist_artworks(
#             input_csv_path,
#             output_jsonl_path,
#             batches_dir_name,
#             target_html_dir,
#             collected_ids,
#             batch_size
#         )
#         final_df = collect_batches(batches_dir_name)
#         logger.info('Total num rows %d', final_df.shape[0])
#         write_jsonl(
#             final_df.sort_values(by='ind')[['ind', 'artist_name', 'artworks']].to_dict(orient='records'),
#             output_jsonl_path
#         )
#     logger.info('Artworks data saved')


def _build_html_path(url, html_dir_name, root_data_dir=None):
    if root_data_dir is None:
        root_data_dir = config['data_version_dir']
    html_dir = os.path.join(root_data_dir, html_dir_name)
    path_parts = [part for part in url.split('/') if part]
    artist_slug = path_parts[3] if len(path_parts) > 3 and path_parts[2] == 'en' else ''
    page_slug = path_parts[-1].split('.')[0]
    html_file_name = f"{artist_slug}_{page_slug}" if artist_slug else page_slug
    return os.path.join(html_dir, f"{html_file_name}.html")


def prepare_artworks_index(artists_index: list[dict], limit=10) -> list[dict]:
    index = []
    for artist in artists_index:
        f_path = Path(artist['artist_artworks_source'])
        if not f_path.exists():
            continue
        page_content = f_path.read_text(encoding='utf-8')
        artwork_scraper = BeautifulSoup(markup=page_content, features="html.parser")
        link_set = artwork_scraper.find(name='ul', class_='painting-list-text')
        if link_set is not None:
            link_iter = link_set.find_all(name='li', class_='painting-list-text-row')
            for artwork_cnt, li in enumerate(link_iter):
                if artwork_cnt >= limit:
                    break
                a_tag = li.find('a')
                if a_tag and a_tag.get('href'):
                    href = a_tag['href']
                    if href.startswith('http') and 'wikiart.org' not in href:
                        continue
                    url = href if href.startswith('http') else f"{BASE_URL}{href}"
                    index.append({
                        'source': f_path.name,
                        'artist_url': artist['artist_url'],
                        'artwork_url': url,
                    })
    logger.info('Prepared artworks index: %d items from %d artists', len(index), len(artists_index))
    return index


def get_artworks_raw_html(artworks_index: list[dict], target_html_dir='artworks_raw_html', num_workers=4) -> list[dict]:
    if not artworks_index:
        logger.warning('Empty artworks index, nothing to download')
        return []
    logger.info('URL example: %s', artworks_index[0]['artwork_url'])
    logger.info('Downloading %d artworks with %d threads', len(artworks_index), num_workers)
    completed = 0
    failed_urls = set()
    total = len(artworks_index)
    urls = [item['artwork_url'] for item in artworks_index]
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(get_html, url, target_html_dir): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                future.result()
            except Exception:
                logger.error('Failed to download %s', url)
                failed_urls.add(url)
            completed += 1
            if completed % 50 == 0 or completed == total:
                logger.info('Progress: %d/%d artworks downloaded', completed, total)
    for item in artworks_index:
        item['local_html_path'] = _build_html_path(item['artwork_url'], target_html_dir)
    artworks_index = [item for item in artworks_index if item['artwork_url'] not in failed_urls]
    return artworks_index

def prepare_artists_index(input_csv_path, lists_html_dir='art_links_lists', num_workers=4) -> list[dict]:
    rows = pd.read_csv(input_csv_path).to_dict(orient='records')
    logger.info('Downloading artworks list pages for %d artists with %d threads', len(rows), num_workers)
    completed = 0
    total = len(rows)
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {
            executor.submit(get_artworks_list_page, row['artist_url'], lists_html_dir): row
            for row in rows
        }
        for future in as_completed(futures):
            row = futures[future]
            try:
                future.result()
            except Exception:
                logger.error('Failed to download artworks list for %s', row['artist_name'])
            completed += 1
            if completed % 50 == 0 or completed == total:
                logger.info('Progress: %d/%d artists downloaded', completed, total)
    artists_index = []
    for row in rows:
        list_url = f"{row['artist_url']}/all-works/text-list"
        artist_artworks_source = _build_html_path(list_url, lists_html_dir)
        artists_index.append({
            'artist_url': row['artist_url'],
            'artist_artworks_source': artist_artworks_source,
        })
    logger.info('Prepared artists index: %d items', len(artists_index))
    return artists_index


# def scrape_artworks_v2(input_csv_path, artworks_html_dir, saving_path, num_workers=4):
#     artists_index = prepare_artists_index(input_csv_path, num_workers=num_workers)
#     artworks_index = prepare_artworks_index(artists_index, limit=10)
#     artworks_index = get_artworks_raw_html(
#         artworks_index=artworks_index,
#         target_html_dir=artworks_html_dir,
#         num_workers=num_workers,
#     )
#     write_jsonl(artworks_index, saving_path)
#     logger.info('Saved %d artworks index to %s', len(artworks_index), saving_path)

def process_art_movement(raw_str):
    if not isinstance(raw_str, str):
        return ''
    tags = []
    # Split on commas not inside parentheses
    items = re.split(r',\s*(?![^()]*\))', raw_str)
    for item in items:
        item = item.strip()
        if not item:
            continue
        # Extract main name and parenthesized aliases as separate tags
        parts = re.split(r'\(([^)]+)\)', item)
        for part in parts:
            for sub in part.split(','):
                sub = sub.strip()
                if sub:
                    tags.append(sub)
    # Deduplicate while preserving order
    tags = list(dict.fromkeys(tags))
    return '|'.join(tags)

def greedy_tag_split(raw_tag_description: str, tags_df: pd.DataFrame) -> str:
    """greedy_tag_split('post-impressionism socialist realism')"""
    input_str = raw_tag_description
    res = (
        pd.DataFrame(n_gram_split(input_str), columns=['tag'])
        .merge(tags_df[~tags_df['tag'].isin([input_str])], how='inner', on='tag')
        .sort_values(by='size', ascending=False)  # sort values for greedy matching algorithms
        ['tag']
        .values
    )
    res_tags = []
    for i in res:
        if i in input_str and len(i) < 20: # 27
            res_tags.append(i)
            input_str = input_str.replace(i, '')
        if ' '.join(res_tags) == input_str:
            break
    if len(res_tags) == 0:
        res_tags.append(input_str)
    return ','.join([' '.join(set(j.split(' '))) for j in res_tags])

def compute_tags(artists_df) -> pd.DataFrame:
    from itertools import chain

    def art_movement_helper(raw_str: str):
        return [i.strip() for i in raw_str.split(',') if len(i.strip().lower()) > 0]

    artists_df['art movement'] = artists_df['art movement'].fillna('').apply(lambda x: x.lower())
    artists_df['art_movement_raw_tags'] = artists_df['art movement'].apply(art_movement_helper)
    flatten_genres = list(chain.from_iterable(artists_df['art_movement_raw_tags'].values))
    tags_df = (
        pd.DataFrame(flatten_genres,columns=['tag'])['tag']
        .value_counts()
        .reset_index(name='cnt')
    )
    # tags_df.rename(columns={'index': 'tag'}, inplace=True)
    print(tags_df.head())
    # some useful features
    tags_df['is_complex'] = tags_df['tag'].apply(lambda x: len(x.split(' ')) > 1)
    tags_df['size'] = tags_df['tag'].apply(lambda x: len(x))

    tags_df['splitted_tags'] =  tags_df['tag'].apply(lambda x: greedy_tag_split(x, tags_df))
    processed_tag_mapping = {i: j for i, j in tags_df[['tag', 'splitted_tags']].values}
    artists_df['art_tags'] = artists_df['art_movement_raw_tags'].apply(lambda x: ','.join([processed_tag_mapping[i] for i in x]))

    tags_df = (
        pd.DataFrame(list(chain.from_iterable(artists_df['art_tags'].apply(lambda x: x.split(',')).values)), columns=['tag'])
        .value_counts()
        .reset_index(name='cnt')
    )
    tags_df = tags_df[tags_df['tag'].apply(len) > 1]
    # stop_words = set(stopwords.words('english')) 
    # flat_list = list(
    #     np.concatenate(
    #         input_content_df['artist_movement']
    #         .apply(lambda x: [i.replace('(', '').replace(')', '').lower() for i in x.split(' ') if len(i)>0])
    #         .values
    #     ).flat
    # )
    # flat_list = [i for i in flat_list if i not in stop_words]

    # tags_df = (
    #     pd.DataFrame(flat_list, columns=['tag'])
    #     .value_counts()
    #     .to_frame(name='cnt')
    #     .query('cnt>1').reset_index()
    # )
    # tags_df.drop(tags_df[~tags_df['tag'].apply(lambda x: any(c.isalpha() for c in x))].index, inplace=True)
    # tags_df.reset_index(inplace=True, drop=True)

    return tags_df

def merge_wikiart_data(
    # input_jsonl_path: str,
    artworks_json_dir: str,
    input_artists_info_csv_path: str,
    output_csv_path: str,
):
    # res_df = pd.DataFrame(read_jsonl(input_jsonl_path))
    # if 'ind' in res_df.columns:
    #     assert (res_df['ind'].values.size == res_df['ind'].unique().size)
    #     res_df.set_index('ind', inplace=True)
    # res_df.index.name = None
    artists_info_df = pd.read_csv(input_artists_info_csv_path)
    print(artists_info_df.shape[0], artists_info_df.columns.tolist())
    cols_list = ['artist_name', 'artist_link', 'art movement', 'nationality', 'field', 'artist_pic', 'wikipedia', 'artist_url']
    # content_df = pd.merge(
    #     artists_info_df[['artist_name', 'art movement', 'nationality', 'field', 'artist_pic', 'wikipedia', 'artist_url']],
    #     res_df,
    #     left_index=True, right_index=True, suffixes=('', '_check')
    # )
    artworks_json_paths = list(Path(artworks_json_dir).iterdir())
    print(len(artworks_json_paths))
    df = pd.json_normalize([
        json.loads(item_path.read_text(encoding="utf-8")) for item_path in artworks_json_paths
    ], max_level=1)
    artworks_images_df = df.groupby('artist_link')['image'].apply(list).reset_index()
    content_df = artists_info_df[cols_list].merge(artworks_images_df, on='artist_link')
    logger.info('Num rows %d', content_df.shape[0])
    content_df.to_csv(output_csv_path, index=False, compression="gzip")
    print('Saved to %s, num rows: %d' % (output_csv_path, content_df.shape[0]))

def compute_tags_and_save(input_csv_path: str, output_tags_csv_path: str):
    init_nltk()
    content_df = pd.read_csv(input_csv_path, compression="gzip")
    tags_df = compute_tags(content_df).query('cnt > 1')
    logger.info('Num tags %d', tags_df.shape[0])
    tags_df.to_csv(output_tags_csv_path, index=False, compression="gzip")
    print('Saved to %s, num rows: %d' % (output_tags_csv_path, tags_df.shape[0]))

def prepare_service_data(service_data_path: str):
    pass
