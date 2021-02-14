import calendar
import json
import logging

from urllib.parse import quote as make_url_safe

import requests
import requests.exceptions

from ffcsa.core import dropsites
from ffcsa.shop.orders import get_order_window_for_user

if __name__ == '__main__':
    from ffcsa.ffcsa import settings

    print('sendinblue.py :: loading settings.py directly')
else:
    from django.conf import settings

logger = logging.getLogger(__name__)

_API_KEY = settings.SENDINBLUE_API_KEY
if settings.SENDINBLUE_ENABLED and _API_KEY is None:
    raise Exception('SENDINBLUE_API_KEY is not defined in local_settings.py')

_DEFAULT_HEADERS = {
    'accept': 'application/json',
    'content-type': 'application/json',
    'api-key': _API_KEY
}

_BASE_ENDPOINT = 'https://api.sendinblue.com/v3/'

NEW_USER_LISTS = ['WEEKLY_NEWSLETTER', 'WEEKLY_REMINDER', 'MEMBERS']

NEW_USER_LISTS_TO_REMOVE = ['PROSPECTIVE_MEMBERS']

_HOME_DELIVERY_LIST = 'Home Delivery - {}'
_PACKOUT_DAY_LIST = 'Packout - {}'


# --------
# General helper functions

def send_request(endpoint, method='GET', query=None, data=None, headers=None):
    """
    Wrapper to simplify Sendinblue request handling

    @param endpoint: Everything after api.sendinblue.com/v3/
    @param method: Relevant HTTP verb for endpoint
    @param query: Dictionary of query parameters for GET requests
    @param data: Dictionary of request payload for POST requests
    @param headers: Dictionary of request headers - 'content-type' and 'api-key' will be overwritten if provided

    @return: Dictionary containing the JSON response; raises descriptive exceptions upon failure
    """

    endpoint = _BASE_ENDPOINT + endpoint.lstrip('/')
    data = json.dumps(data) if data is not None else None
    headers = {} if headers is None else headers
    headers.update(_DEFAULT_HEADERS)

    response = requests.request(method, endpoint, headers=headers, data=data, params=query)

    if response.status_code >= 400:
        if response.status_code < 500:
            response_json = response.json()
            response_error = response_json.get('error', response_json)['message']  # SIB error format is not consistent
            raise Exception('Sendinblue error: HTTP {}: {}'.format(response.status_code, response_error))

        else:
            response_json = response.json()
            response_error = response_json.get('error', response_json)['message']  # SIB error format is not consistent
            raise Exception(
                'Sendinblue internal server error: HTTP {}: {}'.format(response.status_code, response_error))

    try:
        return response.json()
    except json.decoder.JSONDecodeError:
        return response.text


def _initialize_drop_site_lists():
    # Create a dictionary of {drop_site_name: id} of the SIB drop site mailing lists
    # If drop sites in settings.py do not have corresponding lists on SIB, this will create them

    try:
        # 50 is the max results the api will return. If we every have more then 50 dropsites, we will need to fix this
        existing_lists = send_request('contacts/folders/{}/lists'.format(settings.SENDINBLUE_DROP_SITE_FOLDER_ID),
                                      query={'limit': 50})

    except requests.exceptions.ConnectionError as ex:
        if settings.DEBUG:
            logger.critical('The connection to Sendinblue failed while trying to initialize the drop site list. '
                            'Using placeholder IDs.')

            stub_ids = (_ for _ in range(len(dropsites.DROPSITE_CHOICES)))
            return {ds[0]: ds_id for ds, ds_id in zip(dropsites.DROPSITE_CHOICES, stub_ids)}

        else:
            raise ex

    drop_site_ids = {_list['name'].replace('Dropsite - ', ''): int(_list['id'])
                     for _list in existing_lists['lists']
                     if _list['name'].startswith('Dropsite')}

    # Get the names of the drop_sites from settings.py and diff them with the folders on SIB
    missing_on_sib = [d[0] for d in dropsites.DROPSITE_CHOICES if d[0] not in drop_site_ids.keys()]

    for city in settings.HOME_DELIVERY_CITIES:
        list = _HOME_DELIVERY_LIST.format(city)
        if list not in drop_site_ids.keys():
            missing_on_sib.append(list)

    for missing_drop_site in missing_on_sib:
        list_name = 'Dropsite - {}'.format(missing_drop_site)
        logger.warning('Drop site list "{}" is missing on Sendinblue; creating...'.format(list_name))
        response = send_request('contacts/lists', method='POST',
                                data={'name': list_name, 'folderId': settings.SENDINBLUE_DROP_SITE_FOLDER_ID})
        drop_site_ids[missing_drop_site] = int(response['id'])

    return drop_site_ids


def _initialize_packout_day_lists():
    # If the order window packout day in settings.py do not have corresponding lists on SIB, this will create them

    # 50 is the max results the api will return.
    existing_lists = send_request('contacts/folders/{}/lists'.format(settings.SENDINBLUE_PACKOUT_DAY_FOLDER_ID),
                                  query={'limit': 50})

    day_ids = {_list['name']: int(_list['id'])
               for _list in existing_lists['lists']
               if _list['name'].startswith('Packout')} if existing_lists else {}

    # Get the names of the drop_sites from settings.py and diff them with the folders on SIB
    missing_on_sib = []

    for window in settings.ORDER_WINDOWS:
        list_name = _PACKOUT_DAY_LIST.format(calendar.day_name[window['packDay'] - 1])
        if list_name not in day_ids.keys():
            missing_on_sib.append(list_name)

    for list_name in missing_on_sib:
        logger.warning('Packout day list "{}" is missing on Sendinblue; creating...'.format(list_name))
        response = send_request('contacts/lists', method='POST',
                                data={'name': list_name, 'folderId': settings.SENDINBLUE_PACKOUT_DAY_FOLDER_ID})
        day_ids[list_name] = int(response['id'])

    return day_ids


if settings.SENDINBLUE_ENABLED:
    _DROP_SITE_IDS = _initialize_drop_site_lists()
    _PACKOUT_DAY_IDS = _initialize_packout_day_lists()


def get_packout_list_for_user(user):
    list_name = None

    window = get_order_window_for_user(user)
    if window:
        list_name = _PACKOUT_DAY_LIST.format(calendar.day_name[window['packDay'] - 1])

    return list_name


# --------
# User (contact) management

def _format_phone_number(phone_number):
    # Returns formatted phone number on success, False on failure

    for char in (' ', '-', '(', ')'):
        phone_number = phone_number.replace(char, '')

    if 0 < len(phone_number) < 10:
        return False

    # Lacking country code; assume US
    elif len(phone_number) == 10:
        return '1' + phone_number

    # SIB requires a leading +
    elif len(phone_number) == 11:
        return '' + phone_number

    return phone_number


def get_user(email=None, phone_number=None):
    """
    Returns user data from SIB; either email or phone_number must be provided

    @param email: User's email
    @param phone_number: User's cell phone number (optional; can be used instead of email)

    @return: Dictionary with keys 'email', 'first_name', 'last_name', 'phone_number', 'drop_site', and 'list_ids' on success, False on failure
    """

    if not settings.SENDINBLUE_ENABLED:
        raise Exception('Attempted to get SendInBlue user while SIB is disabled')

    if email is None and phone_number is None:
        raise Exception('Either email or phone_number must be provided')

    # Look up user, trying email first (if provided)
    identifier = email.lower() if email is not None else phone_number
    user = None
    try:
        user = send_request('contacts/{}'.format(make_url_safe(identifier)))
    except Exception as ex:
        if 'Contact does not exist' in str(ex):
            if phone_number is None:
                # Email not found and phone number not provided
                return False
        else:
            raise ex

    if user is None:
        # Failed to look up by email, try phone number
        identifier = phone_number

        try:
            user = send_request('contacts/{}'.format(make_url_safe(identifier)))
        except Exception as ex:
            if 'Contact does not exist' in str(ex):
                # User could not be found using the provided phone number
                return False
            else:
                raise ex

    attributes = user['attributes']
    list_ids = user['listIds']
    drop_site = [name for name, site_list_id in _DROP_SITE_IDS.items() if site_list_id in list_ids]
    drop_site = drop_site[0] if len(drop_site) != 0 else None
    packout_list = None
    for list_name, id in _PACKOUT_DAY_IDS.items():
        if id in list_ids:
            packout_list = list_name
            break

    return {
        'identifier': user['email'],
        'email': user['email'],
        'first_name': attributes.get('FIRSTNAME', None),
        'last_name': attributes.get('LASTNAME', None),
        'phone_number': attributes.get('sms', attributes).get('SMS', None),
        'drop_site': drop_site,
        'packout_list': packout_list,
        'list_ids': list_ids
    }


def add_user(email, first_name, last_name, drop_site, phone_number=None):
    """
    Add a new user to SIB. Adds user to the Weekly Newsletter, Weekly Reminder, Members, and provided drop site list

    @param email: Email of user to be added
    @param first_name: User's first name
    @param last_name: User's last name
    @param drop_site: Drop site name, ex: 'Hollywood'
    @param phone_number: User's cellphone number, not required

    @return: (True, '') on success, (False, '<some error message>') on failure
    """

    if not settings.SENDINBLUE_ENABLED:
        return True, ''

    if drop_site not in _DROP_SITE_IDS.keys():
        msg = 'Drop site {} does not exist in settings.DROPSITES'.format(drop_site)
        logger.error(msg)
        return False, msg

    drop_site_list_id = int(_DROP_SITE_IDS[drop_site])

    phone_number = _format_phone_number(phone_number) if phone_number is not None else None
    if phone_number is False:
        msg = 'Invalid phone number'
        logger.error(msg)
        return False, msg

    body = {
        'updateEnabled': False,
        'email': email.lower(),
        'attributes': {
            'FIRSTNAME': first_name,
            'LASTNAME': last_name,
        },
        'listIds': [drop_site_list_id] + [int(settings.SENDINBLUE_LISTS[desired]) for desired in NEW_USER_LISTS],
        'unlinkListIds': [int(settings.SENDINBLUE_LISTS[unwanted]) for unwanted in NEW_USER_LISTS_TO_REMOVE]
    }

    if phone_number is not None:
        body['attributes']['SMS'] = phone_number

    try:
        send_request('contacts', 'POST', data=body)

    except Exception as ex:
        if 'Contact already exist' in str(ex):
            msg = 'User already exists'
            logger.error(msg)
            return False, msg
        logger.error(ex)

    return True, ''


def update_or_add_user(user, lists_to_add=None, lists_to_remove=None, remove_member=False):
    """
    Updates a user on SIB, or creates a new one should they not exist

    @param user: User object
    @param lists_to_add: List of list names that the user desires to be on (other than drop site)
    @param lists_to_remove: List of list names the user does not want to be on (other than drop site)
    @param remove_member: Is this user being removed from active membership

    @return: (True, '') on success, (False, '<some error message>') on failure
    """

    if not settings.SENDINBLUE_ENABLED:
        return True, ''

    if lists_to_add is None:
        lists_to_add = []
    if lists_to_remove is None:
        lists_to_remove = []

    drop_site = _HOME_DELIVERY_LIST.format(user.profile.delivery_address.city) if user.profile.home_delivery \
        else user.profile.drop_site

    if remove_member:
        lists_to_add.extend(['FORMER_MEMBERS'])
        to_remove = NEW_USER_LISTS.copy()
        to_remove.append(get_packout_list_for_user(user))
        lists_to_remove.extend(to_remove)
        drop_site = None

    if not remove_member and not user.profile.home_delivery and drop_site not in dropsites._DROPSITE_DICT:
        msg = 'Drop site {} does not exist in settings.DROPSITES'.format(drop_site)
        logger.error(msg)
        return False, msg

    phone_number = _format_phone_number(user.profile.phone_number) if user.profile.phone_number is not None else None
    if phone_number is False:
        msg = 'Invalid phone number'
        logger.error(msg)
        return False, msg

    body = {'attributes': {}, 'listIds': [], 'unlinkListIds': []}

    # Diff the old and new user info
    try:
        old_user_info = get_user(user.email, phone_number)
    except Exception as ex:
        logger.error(ex)
        return False, str(ex)

    # User could not be found on Sendinblue; create a new one
    if not old_user_info:
        add_success, add_msg = add_user(user.email, user.first_name, user.last_name, drop_site, phone_number)

        if not add_success:
            logger.error(add_msg)
            return False, add_msg

        old_user_info = get_user(user.email, phone_number)

    # Tried to add a user with a phone number that already exists in SIB
    if not old_user_info:
        logger.info(
            'New SIB user {} has existing phone number {}; dropping phone number.'.format(user.email, phone_number))
        add_success, add_msg = add_user(user.email, user.first_name, user.last_name, drop_site, phone_number=None)

        if not add_success:
            logger.error(add_msg)
            return False, add_msg

        old_user_info = get_user(user.email, phone_number)

    # Something unexpected went wrong; if this message is seen it should be debugged
    if not old_user_info:
        msg = 'Unexpectedly failed to add or update user with this info:\n' + \
              'Email: "{}" FNAME: "{}" LNAME: "{}" DROPSITE: "{}" PHONE: "{}"'.format(
                  user.email, user.first_name, user.last_name, drop_site, phone_number)
        logger.error(msg)
        return False, msg

    identifier = old_user_info.pop('identifier')

    packout_list = get_packout_list_for_user(user)
    new_user_info = {'email': user.email.lower(), 'first_name': user.first_name, 'last_name': user.last_name,
                     'drop_site': drop_site, 'phone_number': phone_number, 'packout_list': packout_list}

    to_set = [(k, v) for k, v in new_user_info.items() if old_user_info[k] != v]

    # Nothing to update
    if len(to_set) == 0 and len(lists_to_add) == 0 and len(lists_to_remove) == 0:
        return True, ''

    # Loop through and set attributes in query to their SIB equivalent
    translate_table = {'email': 'EMAIL', 'first_name': 'FIRSTNAME', 'last_name': 'LASTNAME', 'phone_number': 'SMS'}
    for attr_name, attr_value in to_set:
        sib_attr_name = translate_table.get(attr_name, None)

        if sib_attr_name is not None:  # Ignore drop site
            if attr_name == 'phone_number' and attr_value is None:
                body['attributes'][sib_attr_name] = ''
            elif attr_value != '':
                body['attributes'][sib_attr_name] = attr_value

    # Swap drop sites or remove drop site
    old_user_drop_site = old_user_info['drop_site']
    if old_user_drop_site != drop_site:
        if drop_site is not None:
            body['listIds'].append(int(_DROP_SITE_IDS[drop_site]))
        if old_user_drop_site is not None:
            body['unlinkListIds'].append(int(_DROP_SITE_IDS[old_user_drop_site]))

    # Swap packout day or remove
    old_user_packout_list = old_user_info['packout_list']
    if old_user_packout_list != packout_list:
        if not remove_member and packout_list is not None:
            body['listIds'].append(int(_PACKOUT_DAY_IDS[packout_list]))
        if old_user_packout_list is not None:
            body['unlinkListIds'].append(int(_PACKOUT_DAY_IDS[old_user_packout_list]))

    # Add/remove lists
    body['listIds'].extend([int(settings.SENDINBLUE_LISTS[desired]) for desired in lists_to_add])
    body['unlinkListIds'].extend([int(settings.SENDINBLUE_LISTS[unwanted]) for unwanted in lists_to_remove])

    # Remove empty lists from query
    if len(body['listIds']) == 0:
        del body['listIds']
    if len(body['unlinkListIds']) == 0:
        del body['unlinkListIds']

    try:
        send_request('contacts/{}'.format(make_url_safe(identifier)), 'PUT', data=body)

    except Exception as ex:
        if 'Invalid phone number' in str(ex):
            msg = 'Invalid phone number'
            logger.error(msg)
            return False, msg

        logger.error('SendInBlue error: %s - Identifier: %s - Body: %s - Old User Info: %s', str(ex), identifier, body,
                     old_user_info)
        return False, str(ex)

    return True, ''


def on_user_cancel_subscription(user):
    return update_or_add_user(user, remove_member=True)


def on_user_resubscribe(user):
    return update_or_add_user(user, lists_to_add=NEW_USER_LISTS.copy(), lists_to_remove=['FORMER_MEMBERS'])

# --------
# Email management

def _get_transactional_email_templates(pprint=True):
    # Gets and pretty-prints the names and IDs of all transactional templates,
    # mostly for easy reference while working in the back-end

    templates = send_request('smtp/templates', query={"templateStatus": True})

    templates = templates.get('templates', None)
    if templates is None:
        raise Exception('Sendinblue error: Could not get transactional email templates')

    templates = {t['name']: t['id'] for t in templates}

    if pprint:
        print('Sendinblue Templates: <name>: <id>')
        print(str(templates).replace('{', '{\n\t').replace('}', '\n}').replace(', ', '\n\t'))
    else:
        return templates


def get_template_last_modified_date(template_name):
    """
    Get the timestamp at which the specified template was last modified

    @param template_name: Name of the Sendinblue template as found in settings.SENDINBLUE_TRANSACTIONAL_TEMPLATES
    @return: Timestamp in format 'YYYY-MM-DDTHH:MM:SS.000+00:00' on success, False on failure
    """

    template_id = settings.SENDINBLUE_TRANSACTIONAL_TEMPLATES.get(template_name, None)

    if template_id is None:
        logger.critical('Sendinblue error: Transactional template "{}" is missing in settings.py'.format(template_name))
        return False

    try:
        response = send_request('smtp/templates/{}'.format(template_id), 'GET')
        return response.get('modifiedAt', None)  # Date template was last modified

    except Exception as ex:
        logger.error(str(ex))
        return False


def send_transactional_email(template_name, recipient_email, params={}):
    """
    Send a transactional email using the provided details

    @param template_name: The name of a template as defined in settings.py
    @param recipient_email: Email of recipient
    @return: True upon success, False on failure
    """

    if not settings.SENDINBLUE_ENABLED:
        return True

    template_id = settings.SENDINBLUE_TRANSACTIONAL_TEMPLATES.get(template_name, None)

    if template_id is None:
        logger.critical('Sendinblue error: Transactional template "{}" is missing in settings.py'.format(template_name))
        return False

    data = {
        'templateId': template_id,
        'replyTo': {'name': 'Full Farm CSA', 'email': settings.DEFAULT_FROM_EMAIL},
        'to': [{'email': recipient_email}],
        'params': params
    }

    try:
        response = send_request('smtp/email', 'POST', data=data)

    except Exception as ex:
        logger.error(str(ex))
        return False

    if 'messageId' not in response.keys():
        logger.error('Sendinblue error: Unexpected response contents: "{}"'.format(response.keys()))
        return False

    return get_template_last_modified_date(template_name)
