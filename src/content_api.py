from fastapi import FastAPI
from pydantic import BaseModel

from content_db import ArtistsDB, UserDB
from utils import artifact_path


class Action(BaseModel):
    user_token: str
    user_name: str
    item_id: int
    item_tag: str
    action_type: str

class User(BaseModel):
    user_name: str

artists_db = ArtistsDB()
artists_db.init_db(artifact_path('artists_info.csv'))
users_db = UserDB()

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/items/{item_id}")
async def get_item(item_id: int):
    item = artists_db.get_content(item_id)
    return {"item": item}

@app.post("/action")
async def action(action: Action):
    users_db.push_action(action.user_token, str(action.item_id), action.item_tag, action.action_type)
    return {"result": "ok"}

@app.post("/auth")
async def auth(user: User):
    bearer_token = users_db.create_user(user.user_name)
    return {"Bearer": bearer_token}

@app.get("/recommend/{item_id}")
async def recommend(item_id: int):
    recs_list = artists_db.recommend(item_id)
    return {"recs": recs_list}

@app.post("/sample")
async def sample(user: User):
    _, user_actions = users_db.get_user_actions(user.user_name)
    result = artists_db.sample_content(user_actions if user_actions else [])
    return result
