"""
Authentication module for OpenCouncil.

Provides:
- JWT token validation via Supabase Auth REST API
- Auth endpoints: signup, login, refresh, me
- Dependency for protected routes

Uses httpx.AsyncClient for Supabase Auth REST API calls (not supabase-py SDK).
"""

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from models.schemas import Volunteer
from storage import get_volunteer, get_volunteer_by_email, save_volunteer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# --- Configuration ---

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


# --- Request/Response Models ---


class SignupRequest(BaseModel):
    email: str
    password: str
    full_name: str
    school: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class SignupResponse(BaseModel):
    user_id: str
    email: str


class UserResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    school: Optional[str] = None
    hours_earned: float = 0.00
    is_active: bool = True


# --- JWT Validation Dependency ---


async def get_current_user(authorization: str = Header(...)) -> dict:
    """Validate Bearer token via Supabase Auth REST API.
    
    Extracts the Bearer token from the Authorization header,
    calls Supabase Auth REST API to validate it, and returns
    the user data. Raises 401 if invalid.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Expected 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[len("Bearer "):]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is empty",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not SUPABASE_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase URL not configured. Set NEXT_PUBLIC_SUPABASE_URL.",
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": SUPABASE_ANON_KEY,
                },
            )

            if response.status_code != 200:
                logger.warning(f"Token validation failed: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            user_data = response.json()
            return user_data

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth service timed out",
        )
    except httpx.RequestError as e:
        logger.error(f"Supabase Auth request failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to reach Supabase Auth service: {str(e)}",
        )


async def get_current_volunteer(user_data: dict = Depends(get_current_user)) -> Volunteer:
    """Get the volunteer profile for the authenticated user.
    
    Uses the user ID from the validated JWT to look up the volunteer
    in the volunteers table. Raises 404 if not found.
    """
    user_id = user_data.get("id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user data from token",
        )

    volunteer = get_volunteer(user_id)
    if not volunteer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Volunteer profile not found. Please sign up first.",
        )

    return volunteer


# --- Auth Endpoints ---


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(request: SignupRequest):
    """Register a new user via Supabase Auth and create a volunteer profile.
    
    Calls Supabase Auth REST API to create the user, then inserts
    a record into the volunteers table.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase Auth not configured. Set NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.",
        )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Call Supabase Auth signup endpoint
            response = await client.post(
                f"{SUPABASE_URL}/auth/v1/signup",
                headers={
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "apikey": SUPABASE_ANON_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "email": request.email,
                    "password": request.password,
                    "data": {
                        "full_name": request.full_name,
                        "school": request.school or "",
                    },
                },
            )

            if response.status_code not in (200, 201):
                error_detail = response.json().get("error_description") or response.json().get("msg") or response.text
                logger.warning(f"Supabase signup failed: {response.status_code} - {error_detail}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Signup failed: {error_detail}",
                )

            auth_data = response.json()
            user_id = auth_data.get("id")
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Supabase did not return a user ID",
                )

            # Create volunteer profile in our database
            volunteer = Volunteer(
                user_id=user_id,
                email=request.email,
                full_name=request.full_name,
                school=request.school,
            )
            save_volunteer(volunteer)

            logger.info(f"New user signed up: {request.email} (id={user_id})")
            return SignupResponse(user_id=user_id, email=request.email)

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth service timed out during signup",
        )
    except httpx.RequestError as e:
        logger.error(f"Supabase signup request failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to reach Supabase Auth service: {str(e)}",
        )


@router.post("/login")
async def login(request: LoginRequest):
    """Authenticate a user with email and password.
    
    Calls Supabase Auth REST API password grant to get an access token.
    Returns the token pair and user info.
    """
    if not SUPABASE_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase Auth not configured. Set NEXT_PUBLIC_SUPABASE_URL.",
        )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
                headers={
                    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
                    "apikey": SUPABASE_ANON_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "email": request.email,
                    "password": request.password,
                },
            )

            if response.status_code != 200:
                error_detail = response.json().get("error_description") or response.json().get("msg") or response.text
                logger.warning(f"Login failed: {response.status_code} - {error_detail}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Login failed: {error_detail}",
                )

            token_data = response.json()
            return AuthResponse(
                access_token=token_data["access_token"],
                token_type="bearer",
                user=token_data.get("user", {}),
            )

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth service timed out during login",
        )
    except httpx.RequestError as e:
        logger.error(f"Supabase login request failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to reach Supabase Auth service: {str(e)}",
        )


@router.post("/refresh")
async def refresh(request: RefreshRequest):
    """Refresh an expired access token using a refresh token.
    
    Calls Supabase Auth REST API refresh_token grant.
    Returns a new token pair.
    """
    if not SUPABASE_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase Auth not configured. Set NEXT_PUBLIC_SUPABASE_URL.",
        )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
                headers={
                    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
                    "apikey": SUPABASE_ANON_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "refresh_token": request.refresh_token,
                },
            )

            if response.status_code != 200:
                error_detail = response.json().get("error_description") or response.json().get("msg") or response.text
                logger.warning(f"Token refresh failed: {response.status_code} - {error_detail}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Token refresh failed: {error_detail}",
                )

            token_data = response.json()
            return {
                "access_token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token"),
                "token_type": "bearer",
                "expires_in": token_data.get("expires_in"),
            }

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth service timed out during token refresh",
        )
    except httpx.RequestError as e:
        logger.error(f"Supabase refresh request failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to reach Supabase Auth service: {str(e)}",
        )


@router.get("/me", response_model=UserResponse)
async def get_me(volunteer: Volunteer = Depends(get_current_volunteer)):
    """Get the current volunteer's profile.
    
    Requires a valid Bearer token in the Authorization header.
    Returns the volunteer record from the volunteers table.
    """
    return UserResponse(
        user_id=volunteer.user_id,
        email=volunteer.email,
        full_name=volunteer.full_name,
        school=volunteer.school,
        hours_earned=volunteer.hours_earned,
        is_active=volunteer.is_active,
    )
