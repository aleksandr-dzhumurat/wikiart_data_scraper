import argparse

from utils import (
    logger,
    config,
    artifact_path
)
from wikiart import (
    get_artists_pages,
    get_artists_info,
    get_photo_urls,
)
from galeriesnow import (
    get_exhibitions,
    get_galleries,
    merge_data
)

def scrape_wikidata():
    csv_path = artifact_path('artists_pages.csv')
    get_artists_pages(csv_path)
    # TODO: refactor get_artists_info, using parallel batch processing
    get_artists_info(csv_path, artifact_path('artists_info.csv'), artifact_path('artists_wiki_texts.csv'))
    get_photo_urls(csv_path, artifact_path('artists_artworks.csv'), artifact_path('data_batches'))

def scrape_galleriesnow(galleries_list):
    for gallery_link in galleries_list:
        exhibitions_file_path = artifact_path(f'{artifact_partition_name}_exhibitions.csv')
        galleries_file_path = artifact_path(f'{artifact_partition_name}_galleries.csv')
        artifact_partition_name = gallery_link.split('/')[-1].replace()
        #
        get_exhibitions(gallery_link, exhibitions_file_path)
        get_galleries(gallery_link, galleries_file_path)
        merge_data(exhibitions_file_path, galleries_file_path, f'{artifact_partition_name}_exhibitions_db.csv')
    print('Galleries collected')

parser = argparse.ArgumentParser()
parser.add_argument('--pipeline', type=str, required=True)
args = parser.parse_args()

if __name__ == '__main__':
    if args.pipeline == 'wikidata':
        scrape_wikidata()
    elif args.pipeline == 'galleriesnow':
        scrape_galleriesnow(config['galleries_pages'])
    else:
        print('¯\_(ツ)_/¯')
