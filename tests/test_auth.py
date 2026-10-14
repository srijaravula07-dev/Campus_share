import re
import pytest
from flask import url_for
from app import db, User

def test_registration_success(client, app):
    res = client.post('/register', data={
        'name': 'Test Newbie',
        'email': 'newbie@college.edu',
        'password': 'secretpassword',
        'confirm_password': 'secretpassword',
        'year': '1st Year',
        'branch': 'Computer Science'
    }, follow_redirects=True)
    assert res.status_code == 200
    with app.app_context():
        user = User.query.filter_by(email='newbie@college.edu').first()
        assert user is not None
        assert user.name == 'Test Newbie'
        assert user.password != 'secretpassword'
        assert user.password.startswith('scrypt:') or user.password.startswith('pbkdf2:')


def test_registration_duplicate_email(client, user1):
    res = client.post('/register', data={
        'name': 'Duplicate User',
        'email': 'alice@college.edu',
        'password': 'password123',
        'confirm_password': 'password123',
        'year': '2nd Year',
        'branch': 'Computer Science'
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b'already exists' in res.data


def test_registration_short_password(client):
    res = client.post('/register', data={
        'name': 'Short Pass',
        'email': 'short@college.edu',
        'password': '123',
        'confirm_password': '123',
        'year': '1st Year',
        'branch': 'Civil'
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b'at least 6 characters' in res.data


def test_registration_password_mismatch(client):
    res = client.post('/register', data={
        'name': 'Mismatch User',
        'email': 'mismatch@college.edu',
        'password': 'password123',
        'confirm_password': 'password456',
        'year': '1st Year',
        'branch': 'Civil'
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b'do not match' in res.data


def test_registration_missing_fields(client):
    res = client.post('/register', data={
        'name': '',
        'email': 'empty@college.edu',
        'password': 'password123',
        'confirm_password': 'password123',
        'year': '1st Year',
        'branch': 'Civil'
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b'Please fill in all fields' in res.data


def test_login_success(client, user1):
    res = client.post('/login', data={
        'email': 'alice@college.edu',
        'password': 'password123'
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b'Logged in successfully' in res.data or b'Logout' in res.data


def test_login_invalid_password(client, user1):
    res = client.post('/login', data={
        'email': 'alice@college.edu',
        'password': 'wrongpassword'
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b'Incorrect password' in res.data


def test_login_nonexistent_email(client):
    res = client.post('/login', data={
        'email': 'ghost@college.edu',
        'password': 'password123'
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b'No account found with that email' in res.data


def test_logout(client, user1, auth):
    auth.login('alice@college.edu', 'password123')
    res = auth.logout()
    assert res.status_code == 200
    assert b'Logged out.' in res.data
    # Trying to access protected route after logout should redirect to login
    res2 = client.get('/', follow_redirects=False)
    assert res2.status_code == 302
    assert '/login' in res2.headers['Location']


@pytest.mark.parametrize('path', [
    '/',
    '/upload',
    '/settings',
    '/admin',
    '/bookmarks',
    '/requests',
    '/doubts',
    '/mentors',
    '/my-uploads',
    '/recently-viewed',
    '/notifications',
])
def test_auth_wall_redirects(client, path):
    res = client.get(path, follow_redirects=False)
    assert res.status_code == 302
    assert '/login' in res.headers['Location']


def test_open_redirect_mitigation(client, user1):
    # Malicious absolute external url
    res = client.post('/login?next=https://evil.com', data={
        'email': 'alice@college.edu',
        'password': 'password123'
    }, follow_redirects=False)
    assert res.status_code == 302
    assert 'https://evil.com' not in res.headers['Location']
    assert res.headers['Location'] in ('/', '/browse')

    # Protocol-relative url
    client.get('/logout')
    res2 = client.post('/login?next=//evil.com', data={
        'email': 'alice@college.edu',
        'password': 'password123'
    }, follow_redirects=False)
    assert res2.status_code == 302
    assert '//evil.com' not in res2.headers['Location']
    assert res2.headers['Location'] in ('/', '/browse')

    # Safe local target
    client.get('/logout')
    res3 = client.post('/login?next=/bookmarks', data={
        'email': 'alice@college.edu',
        'password': 'password123'
    }, follow_redirects=False)
    assert res3.status_code == 302
    assert '/bookmarks' in res3.headers['Location']


def test_csrf_protection_enforced(csrf_client, user1):
    # POST without CSRF token should be caught by CSRF handler and flash session error
    res = csrf_client.post('/login', data={
        'email': 'alice@college.edu',
        'password': 'password123'
    }, follow_redirects=True)
    assert b'Your session expired or the form submission was invalid' in res.data
    # Verify user was NOT logged in
    res_browse = csrf_client.get('/', follow_redirects=False)
    assert res_browse.status_code == 302
    assert '/login' in res_browse.headers['Location']

    # Obtain CSRF token from GET /login form
    get_res = csrf_client.get('/login')
    assert get_res.status_code == 200
    token_match = re.search(r'name="csrf_token" value="([^"]+)"', get_res.data.decode('utf-8'))
    assert token_match is not None
    csrf_token = token_match.group(1)

    # POST with valid token should succeed and log the user in
    post_res = csrf_client.post('/login', data={
        'email': 'alice@college.edu',
        'password': 'password123',
        'csrf_token': csrf_token
    }, follow_redirects=True)
    assert post_res.status_code == 200
    assert b'Logged in successfully' in post_res.data or b'Logout' in post_res.data
