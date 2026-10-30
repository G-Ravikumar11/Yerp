"""Sign in with Google."""
import os

from authlib.integrations.starlette_client import OAuth

from app.constants.common import GMAIL_SCOPES


oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    # The default is the Gmail connection's: send mail only. The platform console's sign-in passes its own scope
    # (GOOGLE_SIGNIN_SCOPES) to be told who somebody is.
    client_kwargs={'scope': ' '.join(GMAIL_SCOPES)}
)

# Yahoo is plain OpenID Connect; sign-in only, no mail permission.
oauth.register(
    name='yahoo',
    client_id=os.getenv("YAHOO_CLIENT_ID"),
    client_secret=os.getenv("YAHOO_CLIENT_SECRET"),
    server_metadata_url='https://api.login.yahoo.com/.well-known/openid-configuration',
    # PKCE (S256) on top of the state and nonce authlib already checks; the ID token's signature, issuer, audience,
    # expiry and nonce are checked by authlib against Yahoo's published keys when the code is exchanged.
    client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256'},
)
