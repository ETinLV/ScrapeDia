import getpass
import json
import re
import sys
import time

import requests

client = requests.session()

# TOR proxies setup. Must have TOR installed and running on machine to work
proxies = {
    'http': 'socks5h://127.0.0.1:9050',
    'https': 'socks5h://127.0.0.1:9050'
}

# Diaspora Darkweb URLS
BASE_URL = 'http://7qzmtqy2itl7dwuu.onion'
SIGN_IN_URL = BASE_URL + '/users/sign_in'
STREAM_URL = BASE_URL + '/stream'


def get_tokens():
    """Make request to sign-in page and return the CSRF token."""
    r = client.get(SIGN_IN_URL, proxies=proxies)
    if r.status_code != 200:
        raise Exception("Unable to connect to URL, is TOR running?")

    # I originally used beautifulSoup to scrape the token, but because I didn't use BS4 anywhere else, regex was faster
    pattern = '\"csrf-token\" content=\"([^\"]*)'
    content = r.content.decode('utf-8')
    csrf_token = re.search(pattern=pattern, string=content)[1]
    return csrf_token


def authenticate(csrf_token):
    """Authenticate with Diaspora using the CSRF token."""
    # Try to import Username and Pass from secrets.py (if exists), else ask for password
    try:
        from secrets import username, password
    except ImportError:
        username = input("Please Enter A Username")
        password = getpass.getpass('Password:')

    data = [
        ('authenticity_token', csrf_token),
        ('user[username]', username),
        ('user[password]', password),
        ('user[remember_me]', '1'),
    ]

    r = client.post(SIGN_IN_URL, data=data, proxies=proxies)
    if re.search('(Invalid Username or password)', r.content.decode()):
        print("\033[91mUnable to authenticate with provided credentials.")
        sys.exit()
    return


def make_max_time():
    """Generator to create the max_time Parameter for going further back into the stream."""
    current_time = int(round(time.time() * 1000))

    # Each request returns a max of 15 posts, so we need to go back in time enough to get 15 posts, but not too far
    # that we miss other posts.
    # 10^6ms seemed to be the the smallest I could use and consistently get new posts.
    offset_interval = 2.3 * (10 ** 6)

    # This is the default offset Diaspora uses
    max_time = (current_time - (1.5045093 * (10 ** 12)))

    # I used a generator here because we can go back as many times as we want, and a generator makes it easy to
    # simply subtract the offset over and over
    while max_time > 0:
        yield int(max_time)
        max_time -= offset_interval


def get_stream(max_time, time_in_ms, ):
    """Get JSON Stream of Activity from Diaspora."""

    headers = {
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
    }

    params = (
        ('max_time', max_time),
        ('_', time_in_ms)
    )
    r = client.get(STREAM_URL, headers=headers, params=params, proxies=proxies)
    return json.loads(r.content)


def sum_activity(post):
    """Calculate the total activity of a post."""
    interactions = post['interactions']
    activity = interactions['likes_count'] + interactions['comments_count'] + interactions['reshares_count']
    return activity


def parse_streams():
    """Create JSON object of Most Active User and Post from last 100 posts."""
    time_in_ms = int(round(time.time() * 1000))

    # Because the API will return the same results if there are no older posts,
    # we need to check that each post hasn't already been added. We can use a set for this
    # because it is O(1) lookup time and also enforces that each value is unique
    total_posts = set()

    users_post_count = {}
    most_active_post = {'id': None, 'activity': 0}
    max_time = make_max_time()
    counter = 0  # Counter to limit how many times we run in case there are not 100 posts
    while len(total_posts) < 100 and counter < 20:
        content = get_stream(next(max_time), time_in_ms)
        for post in content:
            if post['id'] not in total_posts:
                total_posts.add(post['id'])
                author_name = post['author']['name']
                users_post_count[author_name] = users_post_count.get(author_name, 0) + 1
                activity = sum_activity(post)
                if activity > most_active_post['activity']:
                    most_active_post['id'] = post['id']
                    most_active_post['text'] = post['text']
                    most_active_post['activity'] = activity

        counter += 1

    most_active_user = max(users_post_count, key=users_post_count.get)
    return json.dumps(
        {'total_posts_found': len(total_posts),
         'most_active_user': {'name': most_active_user, 'post_count': users_post_count[most_active_user]},
         'most_active_post': most_active_post})


if __name__ == '__main__':
    token = get_tokens()
    authenticate(token)
    results = parse_streams()
    print(results)
