import streamlit as st

from content_db import ArtistsDB, ArtworksDB, UserDB
from utils import artifact_path
from wikiart import get_tags


@st.cache_resource
def load_artists_db():
    db = ArtistsDB()
    db.init_db(artifact_path('artists_info.csv'))
    return db

@st.cache_resource
def load_artworks_db():
    db = ArtworksDB()
    db.init_db(artifact_path('artworks_json'))
    return db


artists_db = load_artists_db()
artworks_db = load_artworks_db()

if 'users_db' not in st.session_state:
    st.session_state.users_db = UserDB()
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'user_name' not in st.session_state:
    st.session_state.user_name = None

users_db = st.session_state.users_db

st.title('ArtSwipe')

# --- Auth ---
with st.sidebar:
    st.header('User')
    user_name = st.text_input('Enter your name')
    if st.button('Login'):
        user_id = users_db.create_user(user_name)
        st.session_state.user_id = user_id
        st.session_state.user_name = user_name

    if st.session_state.user_name:
        st.success(f'Logged in as {st.session_state.user_name}')
        _, actions = users_db.get_user_actions(st.session_state.user_name)
        if actions:
            st.write(f'{len(actions)} actions recorded')

# --- Main ---
if st.session_state.user_id is None:
    st.info('Please login to start.')
    st.stop()

# Show random artist
if st.button('Pick an artist 👀') or 'current_artist' not in st.session_state:
    idx = artists_db.df.sample(1).index[0]
    st.session_state.current_artist = int(idx)

artist_idx = st.session_state.current_artist
artist_row = artists_db.df.iloc[artist_idx]
content = artists_db.get_content(artist_idx)

col_img, col_info = st.columns([1, 2])
with col_img:
    artist_pic = artist_row.get('artist_pic', '')
    if isinstance(artist_pic, str) and artist_pic.startswith('http'):
        st.image(artist_pic, width=200)
with col_info:
    st.subheader(artist_row['artist_name'])
    st.write(f"**Movement:** {content.get('artist_movement', '')}")
    st.write(f"**Field:** {content.get('field', '')}")
    if artist_row.get('nationality') and isinstance(artist_row['nationality'], str):
        st.write(f"**Nationality:** {artist_row['nationality']}")
    links = []
    if artist_row.get('artist_url'):
        links.append(f"[WikiArt]({artist_row['artist_url']})")
    if artist_row.get('wikipedia') and isinstance(artist_row['wikipedia'], str):
        links.append(f"[Wikipedia](https://{artist_row['wikipedia']})")
    if links:
        st.markdown(' | '.join(links))

# --- Artworks ---
artist_link = artist_row.get('artist_link', '')
artworks_images = artworks_db.get_images(artist_link)
if artworks_images:
    st.write(f"**Artworks** ({len(artworks_images)})")
    cols = st.columns(min(len(artworks_images), 4))
    for i, img_url in enumerate(artworks_images[:4]):
        with cols[i]:
            st.image(img_url, width="stretch")

artist_tags = get_tags(artists_db.df.fillna('').iloc[artist_idx].to_dict())
col1, col2 = st.columns(2)
with col1:
    if st.button('Like'):
        users_db.push_action(
            st.session_state.user_id, str(artist_idx), artist_tags, 'like',
        )
        st.toast('Liked!')
with col2:
    if st.button('Dislike'):
        users_db.push_action(
            st.session_state.user_id, str(artist_idx), artist_tags, 'dislike',
        )
        st.toast('Disliked!')

# --- Similar artists ---
st.divider()
st.subheader('Similar artists')
recs = artists_db.recommend(artist_idx)
for rec in recs:
    st.write(f"- **{rec['artist_name']}** ({rec['score']:.3f}) — [WikiArt]({rec['artist_url']})")
