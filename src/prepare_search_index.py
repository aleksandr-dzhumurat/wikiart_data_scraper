import json
import os
from typing import Optional, Dict

import pandas as pd
import joblib
import numpy as np
from scipy.sparse import save_npz, load_npz
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer

from utils import (
    artifact_path,
    logger
)


class ContentDB:
    def __init__(self):
        self.df = None  # type: Optional[pd.DataFrame]
        self.tags_df = None  # type: Optional[pd.DataFrame]
        # Simple BoW recommendations
        self.embedder = None
        self.corpus_numpy = None
        
    def init_db(self):
        self.df = pd.read_csv(artifact_path('artists_wiki_texts.csv'))
        # self.df = pd.read_csv(artifact_path('content_db.csv.gz'), compression='gzip')
        # self.df['art_tags'] = self.df['art_tags'].fillna(value='')
        # self.df['wikipedia'] = self.df['wikipedia'].fillna(value='')
        # print('Num artists %d' % self.df.shape[0])
        # self.tags_df = pd.read_csv(artifact_path('tags_db.csv.gz'), compression='gzip').query('cnt > 1')
        # self.tags_df = self.tags_df[self.tags_df['tag'].str.len() <= 15].copy()
        # excluded_tags = ['art']
        # self.tags_df.drop(self.tags_df[self.tags_df['tag'].isin(excluded_tags)].index, inplace=True)
        # print('Num tags %d' % self.tags_df.shape[0])
        print('Preparing vector DB... %d' % self.df.shape[0])
        embeds_path = artifact_path('embeds.npy')
        model_filename = artifact_path('tfidf_vectorizer.pkl')
        if os.path.exists(embeds_path):
            logger.info('Loading from dump...')
            self.embedder = joblib.load(model_filename)
            # self.corpus_numpy = np.load(embeds_path, allow_pickle=False)
            self.corpus_numpy = load_npz(embeds_path)
            print(self.corpus_numpy.shape)
        else:
            embedder = TfidfVectorizer(
                analyzer='word',
                lowercase=True,
                token_pattern=r'\b[\w\d]{3,}\b'
            )
            # embedder.fit(self.df['art_tags'].values)
            embedder.fit(self.df['wiki_text'].values)
            # self.corpus_numpy = embedder.transform(self.df['art_tags'].values)
            self.corpus_numpy = embedder.transform(self.df['wiki_text'].values)
            self.embedder = embedder
            logger.info('Dumping models... %s, %s', self.corpus_numpy.shape, type(self.corpus_numpy))
            joblib.dump(embedder, model_filename)
            # np.save(embeds_path, self.corpus_numpy, allow_pickle=False)
            save_npz(embeds_path, self.corpus_numpy)
        print("DB prepared succesfully! Num embeds %d" % self.corpus_numpy.shape[0])
    
    def get_content(self, content_id: int) -> Dict:
        content_info = self.df.iloc[content_id].to_dict()
        res = {}
        res.update({'artist_movement': content_info['artist_movement']})
        res.update({'field': content_info['artist_field']})
        random_artwork = np.random.choice(json.loads(content_info['artworks']))
        artwork_name = json.dumps(random_artwork.split('/')[-1].split('.')[0].replace('-', ' '))
        res.update({'artworks': random_artwork, 'artwork_name': artwork_name})
        res.update({'artist_id': content_id, 'artist_name': content_info['artist_name'], 'artist_url': content_info['artist_url']})
        for key in res.keys():
            if not isinstance(res[key], str):
                if np.isnan(res[key]):
                    res[key] = 'Empty'
        return res
    
    def recommend(self, user_query, num_recs: int = 10) -> dict:
        user_pref = ''
        if len(user_query) > 0:
            query_embed = self.embedder.transform([user_query])
            similarities = cosine_similarity(query_embed, self.corpus_numpy).flatten()
            rec_ids = np.argsort(similarities)[::-1][:num_recs]
            recs = self.df.iloc[rec_ids]
        else:
            logger.info('random recommendation')
            recs = self.df.sample(num_recs)
        recs_list = []
        for _, row in recs.sample(3).iterrows():
            recs_list.append({
                'artist_name': row['artist_name'],
                # 'artist_url': row['artist_url'],
                # 'artist_wiki_url': 'https://'+row['wikipedia']
            })
        return recs_list


# df = pd.read_csv('/srv/data/06_content_db.csv.gz', compression="gzip")
# corpus_df = pd.read_csv('/srv/data/06_artists_wiki_texts.csv')

# print(df.shape[0], corpus_df.shape[0], df.columns.tolist(), corpus_df.columns.tolist())

content_db = ContentDB()
content_db.init_db()

print(content_db.recommend('picasso'))