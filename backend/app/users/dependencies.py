"""FastAPI factories for the users use cases. Naming: ``<verb_noun>_use_case`` → ``<VerbNoun>Dep``."""

from typing import Annotated

from fastapi import Depends

from app.core.cognito import CognitoDep
from app.db.session import DbDep
from app.users.use_cases.delete_user import DeleteUser
from app.users.use_cases.get_user import GetUser
from app.users.use_cases.update_user import UpdateUser


async def get_user_use_case(db: DbDep) -> GetUser:
    return GetUser(db)


async def update_user_use_case(db: DbDep) -> UpdateUser:
    return UpdateUser(db)


async def delete_user_use_case(db: DbDep, cognito: CognitoDep) -> DeleteUser:
    return DeleteUser(db, cognito)


GetUserDep = Annotated[GetUser, Depends(get_user_use_case)]
UpdateUserDep = Annotated[UpdateUser, Depends(update_user_use_case)]
DeleteUserDep = Annotated[DeleteUser, Depends(delete_user_use_case)]
