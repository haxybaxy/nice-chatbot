"""Routes for the authenticated user's own account."""

from fastapi import APIRouter, status

from app.core.openapi import error_responses
from app.core.security import CurrentUserDep
from app.users.dependencies import DeleteUserDep, GetUserDep, UpdateUserDep
from app.users.models import UserModel
from app.users.schemas import UpdateUserIn, UserOut

router = APIRouter(prefix="/users", tags=["users"], responses=error_responses(401))


@router.get("/me", response_model=UserOut, summary="Get the current user")
async def get_me(current_user: CurrentUserDep, get_user: GetUserDep) -> UserModel:
    return await get_user.execute(user_id=current_user.id)


@router.patch("/me", response_model=UserOut, summary="Update the current user", responses=error_responses(422))
async def update_me(body: UpdateUserIn, current_user: CurrentUserDep, update_user: UpdateUserDep) -> UserModel:
    return await update_user.execute(user=current_user, full_name=body.full_name)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT, summary="Delete the current user")
async def delete_me(current_user: CurrentUserDep, delete_user: DeleteUserDep) -> None:
    """Deletes the local account and its Cognito identity. Organization memberships cascade."""
    await delete_user.execute(user=current_user)
