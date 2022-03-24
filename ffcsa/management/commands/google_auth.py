from django.core.management import BaseCommand
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from ffcsa.core.google import authenticate, SCOPES


class Command(BaseCommand):
    """
    Authenticate fullfarmcsa user using google OAUTH2
    """
    help = 'Authenticate fullfarmcsa@deckfamilyfarm.com.com to access google apis'

    def handle(self, *args, **options):
        if not authenticate():
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_console()
            # Save the credentials for the next run
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)

            print('Google API Authentication successful. You will need to restart the webserver.')

        else:
            print('Google API already authenticated.')
