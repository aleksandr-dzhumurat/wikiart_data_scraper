import argparse

from galeriesnow import (
    collapse_data,
    get_exhibitions,
    get_galleries,
    merge_exhibitions_data,
)
from utils import artifact_path, config, prepare_service_data
from wikiart import (
    build_artworks_json_descriptive_stats,
    extract_artworks_descriptions,
    get_artists_info,
    get_artists_pages,
    get_photo_urls,
)
from wikiart import (
    merge_data as merge_wikiart_data,
)


def scrape_wikidata():
    csv_path = artifact_path('artists_pages.csv')
    get_artists_pages(csv_path)
    # TODO: refactor get_artists_info, using parallel batch processing
    get_artists_info(csv_path, artifact_path('artists_info.csv'), artifact_path('artists_wiki_texts.csv'))
    get_photo_urls(csv_path, artifact_path('artists_artworks.jsonl'), artifact_path('data_batches'))
    merge_wikiart_data(
        artifact_path('artists_artworks.jsonl'),
        artifact_path('artists_info.csv'),
        artifact_path('content_db.csv.gz'),
        artifact_path('tags_db.csv.gz')
    )
    extract_artworks_descriptions()
    build_artworks_json_descriptive_stats()

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
    collapse_data(resulted_files, artifact_path('exhibitions_db.csv.gz'))
    print('Galleries collected')

parser = argparse.ArgumentParser()
parser.add_argument('--pipeline', type=str, required=True)
args = parser.parse_args()

if __name__ == '__main__':
    if args.pipeline == 'wikidata':
        scrape_wikidata()
    elif args.pipeline == 'galleries':
        scrape_galleriesnow(config['galleries_pages'])
    elif args.pipeline == 'deploy':
        prepare_service_data()
    elif args.pipeline == 'analysis':
        build_artworks_json_descriptive_stats()
