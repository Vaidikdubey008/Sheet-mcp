# get_token.py
# Generates a Clerk JWT for testing the MCP server.
# Run this, copy the token, paste into Inspector api_key field.

from clerk_backend_api import Clerk

CLERK_SECRET_KEY = "sk_test_QVO6loAonvtbNNJBRprPhVoDF42kePBb97WJuq8gta"
CLERK_USER_ID    = "user_3GAvxm9EH91XWdzCJqpjLwWQp43"
TEMPLATE_NAME    = "mcp-access"

with Clerk(bearer_auth=CLERK_SECRET_KEY) as sdk:

    # Step 1 — Create a session for the test user
    print("Creating session...")
    session = sdk.sessions.create(request={"user_id": CLERK_USER_ID})
    session_id = session.id
    print(f"Session created: {session_id}")

    # Step 2 — Generate JWT from our JWT template
    print(f"Generating JWT from template '{TEMPLATE_NAME}'...")
    token_response = sdk.sessions.create_token_from_template(
        session_id=session_id,
        template_name=TEMPLATE_NAME
    )

    jwt_token = token_response.jwt

    print("\n" + "="*60)
    print("YOUR JWT TOKEN:")
    print("="*60)
    print(jwt_token)
    print("="*60)
    print("\nCopy the token above and paste it into the api_key field.")
    print("Token expires in 60 seconds — run again if you get a 401.")