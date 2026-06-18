from enum import Enum

from fastapi import FastAPI, HTTPException

app = FastAPI()


class Repository:
    async def fetch(self, user_id: str):
        raise NotImplementedError


repository = Repository()


class UserStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


@app.get("/users/{user_id}")
async def get_user(user_id: str):
    user = await load_user(user_id)
    if user is None:
        raise HTTPException(status_code=404)
    if user.status == UserStatus.SUSPENDED:
        raise HTTPException(status_code=403)
    return user


@app.patch("/users/{user_id}")
async def update_user(user_id: str, command: str):
    user = await load_user(user_id)
    if user is None:
        raise HTTPException(status_code=404)
    action = user_action(user, command)
    if action == "deny":
        raise HTTPException(status_code=403)
    if action == "archive":
        return await archive_user(user)
    if action == "restore":
        return await restore_user(user)
    return user


async def load_user(user_id: str):
    return await repository.fetch(user_id)


def user_action(user, command: str):
    if user.status == UserStatus.DELETED:
        return "deny"
    if command == "archive" and user.status == UserStatus.ACTIVE:
        return "archive"
    if command == "restore" and user.status == UserStatus.SUSPENDED:
        return "restore"
    if command == "delete":
        return "deny"
    return "noop"


async def archive_user(user):
    user.status = UserStatus.SUSPENDED
    return user


async def restore_user(user):
    user.status = UserStatus.ACTIVE
    return user
