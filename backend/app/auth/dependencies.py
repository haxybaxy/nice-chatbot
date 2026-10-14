"""FastAPI factories for the auth use cases. Naming: ``<verb_noun>_use_case`` → ``<VerbNoun>Dep``."""

from typing import Annotated

from fastapi import Depends

from app.auth.use_cases.refresh_session import RefreshSession
from app.auth.use_cases.request_password_reset import RequestPasswordReset
from app.auth.use_cases.reset_password import ResetPassword
from app.auth.use_cases.sign_in import SignIn
from app.auth.use_cases.sign_out import SignOut
from app.auth.use_cases.sign_up import SignUp
from app.core.cognito import CognitoDep
from app.core.mail import MailDep
from app.db.session import DbDep


async def sign_up_use_case(db: DbDep, cognito: CognitoDep) -> SignUp:
    return SignUp(db, cognito)


async def sign_in_use_case(cognito: CognitoDep) -> SignIn:
    return SignIn(cognito)


async def refresh_session_use_case(cognito: CognitoDep) -> RefreshSession:
    return RefreshSession(cognito)


async def sign_out_use_case(cognito: CognitoDep) -> SignOut:
    return SignOut(cognito)


async def request_password_reset_use_case(db: DbDep, mail: MailDep) -> RequestPasswordReset:
    return RequestPasswordReset(db, mail)


async def reset_password_use_case(db: DbDep, cognito: CognitoDep) -> ResetPassword:
    return ResetPassword(db, cognito)


SignUpDep = Annotated[SignUp, Depends(sign_up_use_case)]
SignInDep = Annotated[SignIn, Depends(sign_in_use_case)]
RefreshSessionDep = Annotated[RefreshSession, Depends(refresh_session_use_case)]
SignOutDep = Annotated[SignOut, Depends(sign_out_use_case)]
RequestPasswordResetDep = Annotated[RequestPasswordReset, Depends(request_password_reset_use_case)]
ResetPasswordDep = Annotated[ResetPassword, Depends(reset_password_use_case)]
