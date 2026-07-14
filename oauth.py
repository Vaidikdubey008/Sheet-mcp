# oauth.py
# OAuth 2.0 Authorization Server endpoints for MCP
# Implements the three endpoints claude.ai needs to authenticate:
# 1. /.well-known/oauth-authorization-server  — discovery
# 2. /authorize                                — redirect to Clerk login
# 3. /token                                   — exchange code for JWT

import os
import httpx
import secrets
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route
from dotenv import load_dotenv

load_dotenv()

MCP_BASE_URL          = os.environ.get("MCP_BASE_URL", "http://localhost:8000")
CLERK_AUTHORIZE_URL   = os.environ.get("CLERK_OAUTH_AUTHORIZE_URL", "")
CLERK_TOKEN_URL       = os.environ.get("CLERK_OAUTH_TOKEN_URL", "")
OAUTH_CLIENT_ID       = os.environ.get("CLERK_OAUTH_CLIENT_ID", "")
OAUTH_CLIENT_SECRET   = os.environ.get("CLERK_OAUTH_CLIENT_SECRET", "")


async def discovery(request: Request):
    """
    GET /.well-known/oauth-authorization-server
    Claude.ai hits this first to learn how to authenticate.
    Returns the OAuth 2.0 Authorization Server Metadata (RFC 8414).
    """
    return JSONResponse({
        "issuer": MCP_BASE_URL,
        "authorization_endpoint": f"{MCP_BASE_URL}/authorize",
        "token_endpoint": f"{MCP_BASE_URL}/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
    })


async def authorize(request: Request):
    """
    GET /authorize
    Claude.ai redirects the user here to log in.
    We forward them straight to Clerk's hosted login page,
    passing through all the OAuth parameters claude.ai sent us.
    """
    params = dict(request.query_params)

    # Replace our client_id with Clerk's actual OAuth client_id
    params["client_id"] = OAUTH_CLIENT_ID

    # Build the Clerk authorize URL with all params
    import urllib.parse
    query = urllib.parse.urlencode(params)
    clerk_url = f"{CLERK_AUTHORIZE_URL}?{query}"

    return RedirectResponse(url=clerk_url, status_code=302)


async def token(request: Request):
    """
    POST /token
    After Clerk login, claude.ai sends us the authorization code here.
    We exchange it with Clerk for a real access token,
    then return it to claude.ai.
    """
    form = await request.form()
    code          = form.get("code", "")
    redirect_uri  = form.get("redirect_uri", "")
    code_verifier = form.get("code_verifier", "")

    # Exchange the authorization code with Clerk
    async with httpx.AsyncClient() as client:
        response = await client.post(
            CLERK_TOKEN_URL,
            data={
                "grant_type":     "authorization_code",
                "code":           code,
                "redirect_uri":   redirect_uri,
                "client_id":      OAUTH_CLIENT_ID,
                "client_secret":  OAUTH_CLIENT_SECRET,
                "code_verifier":  code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )

    if response.status_code != 200:
        return JSONResponse(
            {"error": "token_exchange_failed", "detail": response.text},
            status_code=400,
        )

    return JSONResponse(response.json())


# The three routes claude.ai needs
oauth_routes = [
    Route("/.well-known/oauth-authorization-server", discovery, methods=["GET"]),
    Route("/authorize", authorize, methods=["GET"]),
    Route("/token", token, methods=["POST"]),
]