"""Sign in with Google."""
import os

from authlib.integrations.starlette_client import OAuth


oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile https://www.googleapis.com/auth/gmail.send'
    }
)

# Yahoo is plain OpenID Connect; sign-in only, no mail permission.
oauth.register(
    name='yahoo',
    client_id=os.getenv("YAHOO_CLIENT_ID"),
    client_secret=os.getenv("YAHOO_CLIENT_SECRET"),
    server_metadata_url='https://api.login.yahoo.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)
