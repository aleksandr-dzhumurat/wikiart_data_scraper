import json
import multiprocessing
import os
import time
from typing import Dict, List, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup

try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover
    tqdm = None

from utils import init_nltk, logger, n_gram_split


def prepare_pages_list() -> List[str]:
    import string

    BASE_URL = "https://www.wikiart.org/en/Alphabet"
    postfix = 'text-list'

    alphabet = list(string.ascii_lowercase)
    pages_list = [os.path.join(BASE_URL, page_liter, postfix) for page_liter in alphabet]
    return pages_list

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

def get_html(url, html_dir_name=''):
    html_dir = os.path.join(os.environ['ROOT_DATA_DIR'], html_dir_name)
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

def get_artists_pages(result_csv_path: str):
    page_list: List[str] = prepare_pages_list()
    if not os.path.exists(result_csv_path):
        res_df = pd.DataFrame([], columns=['artist_name', 'artist_link'])
        for current_alphabet_page in page_list:
            artists_scraper = BeautifulSoup(
                markup=requests.get(current_alphabet_page).content, features="html.parser"
            )
            res = artists_scraper.find(name="div", class_='masonry-text-view masonry-text-view-all')
            artists = res.find_all(name='li')
            print('Current page: %s, num artists: %d' % (current_alphabet_page, len(artists)))
            res = []
            for artist in artists:
                artist_info = artist.find('a')
                res.append((artist_info['href'], artist_info.get_text()))
            current_page_df = pd.DataFrame(res, columns=['artist_link', 'artist_name'])
            res_df = pd.concat([res_df, current_page_df])
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
        print(raw_str)
        raise e
    return res

def get_artists_info(input_csv_path: str, output_csv_path: str, output_wikitext_csv_path: str):
    if not os.path.exists(output_csv_path):
        wiki_descriptions = []
        artists_info = []
        cnt = 0
        input_df = pd.read_csv(input_csv_path)
        logger.info('Artists information (wiki, etc) scraping started: %d rows', input_df.shape[0])
        for ind, row in input_df.iterrows():
            artist_page_url = os.path.join('https://www.wikiart.org', row['artist_link'][1:])
            logger.info('[%d/%d] Fetching artist: %s', cnt + 1, input_df.shape[0], row['artist_name'])
            artist_info_page = get_html(artist_page_url, 'artists_raw_html')
            artist_dict = {
                'ind': ind, 'artist_name': row['artist_name'], 'artist_url': artist_page_url,
                'request_result_success': False
            }
            wiki_text = 'Empty wiki'
            if artist_info_page is not None:
                # artist_info_scraper = BeautifulSoup(markup=artist_info_page.content, features="html.parser")
                artist_info_scraper = BeautifulSoup(markup=artist_info_page, features="html.parser")
                wiki_text = extract_artist_wiki(artist_info_scraper)
                artist_info = extract_artists_info(artist_info_scraper)
                artist_dict.update(artist_info)
                artist_dict.update({'request_result_success': True})
                logger.info('[%d/%d] OK: %s', cnt + 1, input_df.shape[0], row['artist_name'])
            else:
                logger.warning('[%d/%d] FAILED (no page): %s', cnt + 1, input_df.shape[0], row['artist_name'])
            wiki_descriptions.append((ind, row['artist_name'], wiki_text))
            artists_info.append(artist_dict)
            # time.sleep(0.25)
            cnt += 1
            if cnt % 100 == 0:
                logger.info('Progress: %d of %d artists processed', cnt, input_df.shape[0])
        # saving data to artists_info.csv
        artists_info_df = pd.json_normalize(artists_info)
        artists_info_df['artist_field'] = artists_info_df['field'].apply(process_field)
        artists_info_df['artist_movement'] = artists_info_df['art movement'].apply(process_art_movement)
        artists_info_df.to_csv(output_csv_path, index=False)
        logger.info('authors info saved to %s', output_csv_path)
        (
            pd.DataFrame(wiki_descriptions, columns=['ind', 'artist_name', 'wiki_text'])
            .to_csv(output_wikitext_csv_path, index=False)
        )
        logger.info('wiki textx saved to %s', output_wikitext_csv_path)
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
    # artwork_web_page = requests.get(url)
    artwork_web_page = get_html(url, 'artworks_raw_html')
    artwork_scraper = BeautifulSoup(markup=artwork_web_page, features="html.parser")
    class_ = 'wiki-layout-artist-image-wrapper'
    artwork_block = artwork_scraper.find(name='div', class_=class_)
    res = artwork_block.find('img')['src']
    return res


def extract_artwork_description(filename: str) -> Dict:
    root_data_dir = os.environ.get('ROOT_DATA_DIR', 'data')
    filepath = os.path.join(root_data_dir, 'artworks_raw_html', filename)

    with open(filepath, 'r', encoding='utf-8') as file:
        artwork_page = file.read()

    artwork_scraper = BeautifulSoup(markup=artwork_page, features="html.parser")
    artwork_info = artwork_scraper.find(name='div', class_='wiki-layout-artist-info wiki-layout-artwork-info')

    if artwork_info is None:
        raise ValueError(f'Could not find artwork info block in {filepath}')

    title = ''
    artist = ''

    title_node = artwork_info.find(name='h1')
    if title_node is not None:
        title = title_node.get_text(strip=True)

    artist_node = artwork_info.find(name='h2')
    if artist_node is not None:
        artist_link = artist_node.find(name='a')
        artist = artist_link.get_text(strip=True) if artist_link else artist_node.get_text(strip=True)

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
        'date': date,
        'style': style,
        'genre': genre,
        'location': {
            'venue': venue,
            'city': city,
            'country': country,
        },
        'image': image,
        'images': images,
    }


def _process_artwork_file(args: Tuple[str, str]) -> Tuple[str, str]:
    """Worker function for multiprocessing. Returns (status, filename).
    status is one of: 'processed', 'skipped', 'failed'
    """
    html_filename, output_json_dir = args
    json_filename = f"{os.path.splitext(html_filename)[0]}.json"
    json_filepath = os.path.join(output_json_dir, json_filename)

    if os.path.exists(json_filepath):
        return ('skipped', html_filename)

    try:
        artwork_description = extract_artwork_description(html_filename)
        with open(json_filepath, 'w', encoding='utf-8') as file:
            json.dump(artwork_description, file, ensure_ascii=False, indent=4)
        return ('processed', html_filename)
    except Exception as e:
        logger.warning('Failed to extract artwork description from %s: %s', html_filename, e)
        return ('failed', html_filename)


def extract_artworks_descriptions(
    raw_html_dir_name: str = 'artworks_raw_html',
    output_json_dir_name: str = 'artworks_json',
    num_workers: int = 2,
):
    root_data_dir = os.environ.get('ROOT_DATA_DIR', 'data')
    raw_html_dir = os.path.join(root_data_dir, raw_html_dir_name)
    output_json_dir = os.path.join(root_data_dir, output_json_dir_name)

    os.makedirs(output_json_dir, exist_ok=True)

    if not os.path.exists(raw_html_dir):
        logger.warning('Raw artworks html directory does not exist: %s', raw_html_dir)
        return

    html_files = sorted([
        filename for filename in os.listdir(raw_html_dir)
        if filename.endswith('.html')
    ])

    logger.info('Artwork description extraction started. Num html files: %d, workers: %d', len(html_files), num_workers)

    processed_cnt = 0
    skipped_cnt = 0
    failed_cnt = 0

    worker_args = [(filename, output_json_dir) for filename in html_files]

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
    json_dir_name: str = 'artworks_json',
    stats_output_name: str = 'artworks_json_descriptive_stats.json'
):
    root_data_dir = os.environ.get('ROOT_DATA_DIR', 'data')
    json_dir = os.path.join(root_data_dir, json_dir_name)
    stats_output_path = os.path.join(root_data_dir, stats_output_name)

    if not os.path.exists(json_dir):
        logger.warning('Artwork json directory does not exist: %s', json_dir)
        return

    json_files = sorted([
        filename for filename in os.listdir(json_dir)
        if filename.endswith('.json')
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
    genre_counts: Dict[str, int] = {}
    style_counts: Dict[str, int] = {}

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

def get_artworks_links(artworks_url: str, limit: int = 10):
    # artworks_page = request_retries(artworks_url).content
    artworks_page = get_html(artworks_url, 'art_links')
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


def write_jsonl(records: List[Dict], output_path: str):
    with open(output_path, 'w', encoding='utf-8') as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + '\n')


def read_jsonl(input_path: str) -> List[Dict]:
    result = []
    with open(input_path, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            result.append(json.loads(line))
    return result

def save_batch(batch_data: List[Dict], final_output_path: str, batches_dir_name: str, batch_num: int, batch_size: int):
    output_base_name, output_ext = os.path.splitext(os.path.basename(final_output_path))
    batch_file_name = f'{output_base_name}_{batch_num * batch_size}_{batch_num * batch_size + batch_size}{output_ext}'
    batch_file_name = os.path.join(batches_dir_name, batch_file_name)
    write_jsonl(batch_data, batch_file_name)
    logger.info('Saved to %s', batch_file_name)

def collect_batches(batches_dir_name: str,  overwrite: bool = False):
    logger.info('Collecting batches from %s', batches_dir_name)
    res = pd.DataFrame([], columns=['ind', 'artist_name', 'artworks'])
    try: 
        batch_files = os.listdir(batches_dir_name)
        # batches from previous runs
        for batch_file in batch_files:
            batch_path = os.path.join(batches_dir_name, batch_file)
            if batch_file.endswith('.jsonl'):
                res = pd.concat([res, pd.DataFrame(read_jsonl(batch_path))], ignore_index=True)
            elif batch_file.endswith('.csv'):
                # Backward compatibility with old batch format.
                old_batch = pd.read_csv(batch_path)
                old_batch = old_batch[['ind', 'artist_name', 'artworks']]
                old_batch['artworks'] = old_batch['artworks'].apply(
                    lambda x: json.loads(x) if isinstance(x, str) and x.strip().startswith('[') else []
                )
                res = pd.concat([res, old_batch], ignore_index=True)
        if res.shape[0] > 0 and overwrite:
            for batch_file in batch_files:
                logger.info('removing %s', batch_file)
                os.remove(os.path.join(batches_dir_name, batch_file))
        logger.info('Batches collected, num rows: %d', res.shape[0])
    except FileNotFoundError:
        os.makedirs(batches_dir_name)
    return res

def get_photo_urls(input_csv_path, output_jsonl_path, batches_dir_name, batch_size: int = 30):
    page_postfix = 'all-works/text-list'
    batches_df = collect_batches(batches_dir_name)
    if batches_df.shape[0] > 0:
        logger.info('Removing files...')
        min_id, max_id = batches_df['ind'].min(), batches_df['ind'].max()
        output_name, output_ext = os.path.splitext(output_jsonl_path)
        result_f_name = f"{os.path.basename(output_name)}_{min_id}_{max_id}{output_ext}"
        batch_files = os.listdir(batches_dir_name)
        for batch_file in batch_files:
            logger.info('removing %s', batch_file)
            os.remove(os.path.join(batches_dir_name, batch_file))
        logger.info('Saving to %s', os.path.join(batches_dir_name, result_f_name))
        write_jsonl(
            batches_df.sort_values(by='ind')[['ind', 'artist_name', 'artworks']].to_dict(orient='records'),
            os.path.join(batches_dir_name, result_f_name)
        )
    collected_ids = [int(i) for i in batches_df['ind'].values]
    logger.info('Artwork url retrieval started. Num already collected artists: %d', len(collected_ids))
    if not os.path.exists(output_jsonl_path):
        artworks = []
        cnt = 0
        batch_num = 0
        for ind, row in pd.read_csv(input_csv_path).iterrows():
            cnt += 1
            if ind in collected_ids:
                if cnt % batch_size == 0:
                    batch_num += 1
                continue  # skip all collected ids
            logger.info('scraping %d: %s...', ind, row['artist_link'])
            result_url = os.path.join(os.path.join('https://www.wikiart.org', row['artist_link'][1:]), page_postfix)
            artworks_links = get_artworks_links(result_url)
            artworks.append({'ind': int(ind), 'artist_name': row['artist_name'], 'artworks': artworks_links})
            if cnt % batch_size == 0:
                save_batch(artworks, output_jsonl_path, batches_dir_name, batch_num, batch_size)
                batch_num += 1
                logger.info('Num processed links %d', cnt)
                artworks = []
        if artworks:
            save_batch(artworks, output_jsonl_path, batches_dir_name, batch_num, batch_size)
        final_df = collect_batches(batches_dir_name)
        logger.info('Total num rows %d', final_df.shape[0])
        write_jsonl(
            final_df.sort_values(by='ind')[['ind', 'artist_name', 'artworks']].to_dict(orient='records'),
            output_jsonl_path
        )
    logger.info('Artworks data saved')

def process_art_movement(raw_str):
    if not isinstance(raw_str, str):
        return ''
    try:
        res = ' '.join(sorted(set([i.strip() for i in raw_str.split(',')])))
        res = ' '.join(sorted(set(res.split(' '))))
    except Exception as e:
        print(raw_str)
        raise e
    return res

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

    def process_art_movement(raw_str: str):
        return [i.strip() for i in raw_str.split(',') if len(i.strip().lower()) > 0]

    artists_df['art movement'] = artists_df['art movement'].fillna('').apply(lambda x: x.lower())
    artists_df['art_movement_raw_tags'] = artists_df['art movement'].apply(process_art_movement)
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

def merge_data(
    input_jsonl_path: str,
    input_artists_info_csv_path: str,
    output_csv_path: str,
    output_tags_csv_path: str
):
    init_nltk()
    res_df = pd.DataFrame(read_jsonl(input_jsonl_path))
    if 'ind' in res_df.columns:
        assert (res_df['ind'].values.size == res_df['ind'].unique().size)
        res_df.set_index('ind', inplace=True)
    res_df.index.name = None
    #
    artists_info_df = pd.read_csv(input_artists_info_csv_path)
    print(artists_info_df.shape[0], artists_info_df.columns.tolist())
    #
    content_df = pd.merge(
        artists_info_df[['artist_name', 'art movement', 'nationality', 'field', 'artist_pic', 'wikipedia', 'artist_url']],
        # artists_info_df[['artist_name', 'artist_pic', 'artist_url']],
        res_df,
        left_index=True, right_index=True, suffixes=('', '_check')
    )
    #
    logger.info('Num rows %d', content_df.shape[0])
    content_df.to_csv(output_csv_path, index=False, compression="gzip")
    print('Saved to %s, num rows: %d' % (output_csv_path, content_df.shape[0]))
    #
    tags_df = compute_tags(content_df).query('cnt > 1')
    logger.info('Num tags %d', tags_df.shape[0])
    tags_df.to_csv(output_tags_csv_path, index=False, compression="gzip")
    print('Saved to %s, num rows: %d' % (output_tags_csv_path, tags_df.shape[0]))

def prepare_service_data(service_data_path: str):
    pass
