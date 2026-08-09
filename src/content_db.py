import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from utils import logger
from wikiart import get_tags

logging.basicConfig(format='%(asctime)s: %(message)s', level=logging.INFO)

# embedder = load_embedder()


def user_tags_ranking(user_actions: dict, all_tags_df: pd.DataFrame):
    LIKE = 'like'
    DISLIKE = 'dislike'
    tags_df = all_tags_df.copy()
    if len(user_actions) > 0:
        user_negative_tags = pd.json_normalize([i for i in user_actions if i['action']==DISLIKE])
        if user_negative_tags.shape[0] > 0:
            user_negative_tags = user_negative_tags['content_tag'].value_counts().to_frame(name='cnt').reset_index()
            user_negative_tags.columns = ['content_tag', 'cnt']
        user_positive_tags = pd.json_normalize([i for i in user_actions if i['action']==LIKE])
        if user_positive_tags.shape[0] > 0:
            user_positive_tags = user_positive_tags['content_tag'].value_counts().to_frame(name='cnt').reset_index()
            user_positive_tags.columns = ['content_tag', 'cnt']
        if user_negative_tags.shape[0] > 0:  # drop disliked tags
            tags_df = (
                tags_df
                .merge(user_negative_tags, how='left', left_on='tag', right_on='content_tag',suffixes=('','_neg'))
                .query('cnt_neg.isnull()')
                [['tag', 'cnt']]
            )
        if user_positive_tags.shape[0] > 0:
            tags_df = (
                tags_df
                .merge(user_positive_tags, how='left', left_on='tag', right_on='content_tag',suffixes=('','_pos'))
                .sort_values('cnt_pos', ascending=False)
                [['tag', 'cnt', 'cnt_pos']]
            ).head(3)  # add
    return tags_df

class ArtistsDB:
    def __init__(self):
        self.df = None  # type: Optional[pd.DataFrame]
        # self.tags_df = None  # type: Optional[pd.DataFrame]
        # Simple BoW recommendations
        self.embedder = None
        self.corpus_numpy = None
        
    def init_db(self, path_to_csv):
        self.df = pd.read_csv(path_to_csv)
        # self.df['art_tags'] = self.df['art_tags'].fillna(value='')
        self.df['wikipedia'] = self.df['wikipedia'].fillna(value='')
        print('Num artists %d' % self.df.shape[0])
        # self.tags_df = pd.read_csv(artifact_path('tags_db.csv.gz'), compression='gzip').query('cnt > 1')
        # self.tags_df = self.tags_df[self.tags_df['tag'].str.len() <= 15].copy()
        # excluded_tags = ['art']
        # self.tags_df.drop(self.tags_df[self.tags_df['tag'].isin(excluded_tags)].index, inplace=True)
        # print('Num tags %d' % self.tags_df.shape[0])
        print('Preparing vector DB...')
        # self.embedder = TfidfVectorizer(
        #     analyzer='word',
        #     lowercase=True,
        #     token_pattern=r'\b[\w\d]{3,}\b'
        # )
        # self.embedder.fit(self.df['art_tags'].values)
        # self.corpus_numpy = self.embedder.transform(self.df['art_tags'].values)
        artists_tags = [get_tags(row) for row in self.df.fillna('').to_dict(orient='records')]
        self.embedder = TfidfVectorizer(
            analyzer=lambda x: [t.strip() for t in x.split('|') if t.strip()],
        )
        self.corpus_numpy = self.embedder.fit_transform(artists_tags)
        print(f"DB prepared succesfully! Num content: {len(artists_tags)}")
        return self
    
    def get_content(self, content_id: int) -> dict:
        content_info = self.df.iloc[content_id].to_dict()
        res = {}
        res.update({'artist_movement': content_info['artist_movement']})
        res.update({'field': content_info['artist_field']})
        # random_artwork = np.random.choice(json.loads(content_info['artworks']))
        # artwork_name = json.dumps(random_artwork.split('/')[-1].split('.')[0].replace('-', ' '))
        # res.update({'artworks': random_artwork, 'artwork_name': artwork_name})
        # res.update({'artist_id': content_id, 'artist_name': content_info['artist_name'], 'artist_url': content_info['artist_url']})
        # for key in res:
        #     if not isinstance(res[key], str):
        #         if np.isnan(res[key]):
        #             res[key] = 'Empty'
        return res
    
    def recommend(self, content_id: int, num_recs: int = 10) -> list[dict]:
        artist_row = self.df.fillna('').iloc[content_id]
        query_descr = get_tags(artist_row.to_dict())
        query_embed = self.embedder.transform([query_descr])
        similarities = cosine_similarity(query_embed, self.corpus_numpy).flatten()
        rec_ids = np.argsort(similarities)[::-1][1:num_recs + 1]
        recs_list = []
        for idx in rec_ids:
            row = self.df.iloc[idx]
            recs_list.append({
                'artist_name': row['artist_name'],
                'artist_url': row['artist_url'],
                'score': float(similarities[idx]),
            })
        return recs_list
    
    def sample_content(self, user_actions: list[dict[str, str]], eps: float = 0.3) -> dict:
        all_tags = list(self.embedder.vocabulary_.keys())
        if np.random.random() < eps or len(user_actions) == 0:
            random_tag = np.random.choice(all_tags)
        else:
            positive_tags = [a['content_tag'] for a in user_actions if a['action'] == 'like']
            random_tag = np.random.choice(positive_tags) if positive_tags else np.random.choice(all_tags)
        logger.info('random tag: %s', random_tag)
        matches = self.df[
            self.df['artist_movement'].fillna('')
            .apply(lambda x: random_tag in x.lower())
        ]
        if matches.empty:
            res = int(self.df.sample(1).index[0])
        else:
            res = int(np.random.choice(matches.index))
        return {'item_id': res, 'item_tag': random_tag}

class ArtworksDB:
    def __init__(self):
        self.df = None
        self.images_by_artist = None

    def init_db(self, artworks_json_dir: str):
        artworks_dir = Path(artworks_json_dir)
        cache_path = artworks_dir.parent / 'artworks_images_cache.json'
        if cache_path.exists():
            self.images_by_artist = json.loads(cache_path.read_text(encoding='utf-8'))
            print(f'ArtworksDB loaded from cache: {len(self.images_by_artist)} artists')
        else:
            artworks_json_paths = list(artworks_dir.iterdir())
            self.df = pd.json_normalize([
                json.loads(p.read_text(encoding='utf-8')) for p in artworks_json_paths
            ], max_level=1)
            self.images_by_artist = (
                self.df.groupby('artist_link')['image']
                .apply(list)
                .to_dict()
            )
            cache_path.write_text(json.dumps(self.images_by_artist, ensure_ascii=False), encoding='utf-8')
            print(f'ArtworksDB loaded: {len(self.df)} artworks, {len(self.images_by_artist)} artists (cached)')
        return self

    def get_images(self, artist_link: str) -> list[str]:
        return self.images_by_artist.get(artist_link, [])


class InMemoryStorage:
    def __init__(self):
        self._users = {}  # user_id -> {'name': str, 'actions': list}
        self._next_id = 1

    def find_one(self, name: str) -> dict | None:
        for user_id, user in self._users.items():
            if user['name'] == name:
                return {'_id': user_id, **user}
        return None

    def insert_one(self, name: str) -> str:
        user_id = str(self._next_id)
        self._next_id += 1
        self._users[user_id] = {'name': name, 'actions': []}
        return user_id

    def push_action(self, user_id: str, action: dict):
        self._users[user_id]['actions'].append(action)

    def get_actions(self, user_id: str) -> list[dict]:
        return self._users[user_id]['actions']


class UserDB:
    def __init__(self):
        self.storage = InMemoryStorage()

    def get_user_actions(self, user_name: str) -> tuple[str | None, list[dict] | None]:
        user = self.storage.find_one(user_name)
        if user is None:
            return None, None
        return str(user['_id']), user['actions']

    def create_user(self, user_name: str) -> str:
        user_id, _ = self.get_user_actions(user_name)
        if user_id is None:
            user_id = self.storage.insert_one(user_name)
        else:
            logger.info('User already exists')
        return user_id

    def push_action(self, user_id: str, content_id: str, content_tag: str, action_type: str) -> bool:
        action = {'content_id': content_id, 'content_tag': content_tag, 'action': action_type}
        self.storage.push_action(user_id, action)
        return True
