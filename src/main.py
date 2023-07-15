import argparse

from utils import (
    logger,
    config,
    artifact_path,
    prepare_service_data
)
from wikiart import (
    get_artists_pages,
    get_artists_info,
    get_photo_urls,
    merge_data as merge_wikiart_data,
)
from galeriesnow import (
    get_exhibitions,
    get_galleries,
    merge_exhibitions_data,
    collapse_data
)

def scrape_wikidata():
    csv_path = artifact_path('artists_pages.csv')
    get_artists_pages(csv_path)
    # TODO: refactor get_artists_info, using parallel batch processing
    get_artists_info(csv_path, artifact_path('artists_info.csv'), artifact_path('artists_wiki_texts.csv'))
    get_photo_urls(csv_path, artifact_path('artists_artworks.csv'), artifact_path('data_batches'))
    merge_wikiart_data(
        artifact_path('artists_artworks.csv'),
        artifact_path('artists_info.csv'),
        artifact_path('content_db.csv'),
        artifact_path('tags_db.csv')
    )

def scrape_galleriesnow(galleries_list):
    resulted_files = []
    for gallery_link in galleries_list:
        artifact_partition_name = gallery_link.split('/')[-1]
        #
        exhibitions_file_path = artifact_path(f'{artifact_partition_name}_exhibitions.csv')
        get_exhibitions(gallery_link, exhibitions_file_path)
        #
        galleries_file_path = artifact_path(f'{artifact_partition_name}_galleries.csv')
        get_galleries(gallery_link, galleries_file_path, overwrite=False)
        #
        final_file_path = artifact_path(f'{artifact_partition_name}_exhibitions_db.csv')
        resulted_files.append(final_file_path)
        merge_exhibitions_data(artifact_partition_name, exhibitions_file_path, galleries_file_path, final_file_path)
    collapse_data(resulted_files, artifact_path('exhibitions_db.csv'))
    print('Galleries collected')

parser = argparse.ArgumentParser()
parser.add_argument('--pipeline', type=str, required=True)
args = parser.parse_args()

if __name__ == '__main__':
    if args.pipeline == 'wikidata':
        scrape_wikidata()
    elif args.pipeline == 'galleries':
        scrape_galleriesnow(config['galleries_pages'])
    prepare_service_data()

