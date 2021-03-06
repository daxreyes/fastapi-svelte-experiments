from typing import Any, List

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from pydantic.networks import EmailStr
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.api import deps
from app.config import settings
from loguru import logger

from app import utils

router = APIRouter()


@router.get("/", response_model=List[schemas.User])
def read_users(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    # current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Retrieve users.
    """
    users = crud.user.get_multi(db, skip=skip, limit=limit)
    return users


@router.post("/", response_model=schemas.User)
def create_user(
    *,
    db: Session = Depends(deps.get_db),
    user_in: schemas.UserCreate,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Create new user.
    """
    logger.info(f"Creating new user {user_in.dict()} by logged in user {current_user} ")
    user = crud.user.get_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )
    user = crud.user.create(db, obj_in=user_in)
    return user


@router.put("/me", response_model=schemas.User)
def update_user_me(
    *,
    db: Session = Depends(deps.get_db),
    password: str = Body(None),
    full_name: str = Body(None),
    email: EmailStr = Body(None),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Update own user.
    """
    current_user_data = jsonable_encoder(current_user)
    user_in = schemas.UserUpdate(**current_user_data)
    if password is not None:
        user_in.password = password
    if full_name is not None:
        user_in.full_name = full_name
    if email is not None:
        user_in.email = email
    user = crud.user.update(db, db_obj=current_user, obj_in=user_in)
    return user


@router.get("/me", response_model=schemas.User)
def read_user_me(
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get current user.
    """
    return current_user


@router.post("/open", response_model=schemas.User)
def create_user_open(
    *,
    db: Session = Depends(deps.get_db),
    password: str = Body(...),
    email: EmailStr = Body(...),
    full_name: str = Body(None),
    is_hospital_staff: bool = Body(False),
    about: str = Body(None),
) -> Any:
    """
    Create new user without the need to be logged in.
    """
    if not settings.USERS_OPEN_REGISTRATION:
        raise HTTPException(
            status_code=403, detail="Open user registration is forbidden on this server."
        )
    user = crud.user.get_by_email(db, email=email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system",
        )
    user_in = schemas.UserCreate(
        password=password, email=email, full_name=full_name, is_hospital_staff=is_hospital_staff
    )

    user = crud.user.create(db, obj_in=user_in)
    token = utils.generate_verification_token(user.id)
    utils.send_new_account_email(email_to=user_in.email, username=user_in.email, token=token)
    utils.send_new_account_info(
        email_to=settings.EMAILS_FROM_EMAIL,
        username=user_in.email,
        full_name=user_in.full_name,
        about=about,
    )
    return user


@router.put(
    "/confirm-registration/{token}",
    response_model=schemas.User,
    responses={404: {"model": schemas.Msg}, 403: {"model": schemas.Msg}},
)
def confirm_me(
    *,
    db: Session = Depends(deps.get_db),
    token: str,
) -> schemas.User:
    """
    Verify user registration.
    """
    decoded_jwt = utils.decode_verification_token(token)
    if decoded_jwt:
        user = crud.user.get(db, id=decoded_jwt["sub"])
        if user:
            user = crud.user.update(
                db, db_obj=user, obj_in={"is_verified": True, "is_volunteer": True}
            )
            utils.send_welcome_email(user.email, user.email)
        else:
            return JSONResponse(
                status_code=404, content={"msg": "User with provided token not found."}
            )
    else:
        return JSONResponse(
            status_code=403, content={"msg": "There was an error validating the provided token."}
        )
    return user


@router.delete(
    "/cancel-registration/{token}",
    response_model=schemas.User,
    responses={404: {"model": schemas.Msg}, 403: {"model": schemas.Msg}},
)
def cancel_me(
    *,
    db: Session = Depends(deps.get_db),
    token: str,
) -> Any:
    """
    Cancel user registration.
    """
    decoded_jwt = utils.decode_verification_token(token)
    if decoded_jwt:
        user = crud.user.get(db, id=decoded_jwt["sub"])
        if user:
            crud.user.remove(db, id=user.id)
        else:
            return JSONResponse(
                status_code=404, content={"msg": "User with provided token not found."}
            )
    else:
        return JSONResponse(
            status_code=403, content={"msg": "There was an error validating the provided token."}
        )
    return user


@router.get("/{user_id}", response_model=schemas.User)
def read_user_by_id(
    user_id: str,
    current_user: models.User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db),
) -> Any:
    """
    Get a specific user by id.
    """
    user = crud.user.get(db, id=user_id)
    if user == current_user:
        return user
    if not crud.user.is_superuser(current_user):
        raise HTTPException(status_code=400, detail="The user doesn't have enough privileges.")
    return user


@router.put("/{user_id}", response_model=schemas.User)
def update_user(
    *,
    db: Session = Depends(deps.get_db),
    user_id: int,
    user_in: schemas.UserUpdate,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    """
    Update a user.
    """
    user = crud.user.get(db, id=user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )
    user = crud.user.update(db, db_obj=user, obj_in=user_in)
    return user
