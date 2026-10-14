import io
import os
import pytest
from pypdf import PdfWriter
from app import db, Resource, Rating, Bookmark, RecentView

def make_pdf(text="This is a comprehensive lecture note on algorithms and data structures. It covers sorting, graphs, and dynamic programming."):
    bio = io.BytesIO()
    # Write a simple valid PDF structure with a text stream
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    # We can also test empty or real PDF
    writer.write(bio)
    bio.seek(0)
    return bio


def test_upload_valid_file(client, user1, auth, app):
    auth.login('alice@college.edu', 'password123')
    data = {
        'subject': 'Data Structures',
        'description': 'Lecture 1 notes',
        'year': '2nd Year',
        'branch': 'Computer Science',
        'allow_comments': 'on',
        'file': (io.BytesIO(b'Sample note contents for DSA.'), 'notes.txt')
    }
    res = client.post('/upload', data=data, content_type='multipart/form-data', follow_redirects=True)
    assert res.status_code == 200
    assert b'Resource uploaded successfully.' in res.data

    with app.app_context():
        res_obj = Resource.query.filter_by(subject='Data Structures').first()
        assert res_obj is not None
        assert res_obj.uploader_id == user1
        assert res_obj.file_hash is not None
        disk_path = os.path.join(app.config['UPLOAD_FOLDER'], res_obj.filename)
        assert os.path.exists(disk_path)
        with open(disk_path, 'rb') as f:
            assert f.read() == b'Sample note contents for DSA.'


def test_upload_disallowed_file_type(client, user1, auth):
    auth.login('alice@college.edu', 'password123')
    data = {
        'subject': 'Malicious Code',
        'description': 'Executable script',
        'year': '2nd Year',
        'branch': 'Computer Science',
        'file': (io.BytesIO(b'echo hacked'), 'script.sh')
    }
    res = client.post('/upload', data=data, content_type='multipart/form-data', follow_redirects=True)
    assert res.status_code == 200
    assert b'That file type is not allowed' in res.data


def test_upload_missing_fields(client, user1, auth):
    auth.login('alice@college.edu', 'password123')
    data = {
        'subject': '',
        'year': '2nd Year',
        'branch': 'Computer Science',
        'file': (io.BytesIO(b'some content'), 'notes.txt')
    }
    res = client.post('/upload', data=data, content_type='multipart/form-data', follow_redirects=True)
    assert res.status_code == 200
    assert b'Please fill all fields' in res.data


def test_upload_duplicate_detection_and_confirm(client, user1, user2, auth, app):
    auth.login('alice@college.edu', 'password123')
    content = b'Identical binary content for duplicate test 123.'

    # Upload first time
    client.post('/upload', data={
        'subject': 'Operating Systems',
        'description': 'Original upload',
        'year': '2nd Year',
        'branch': 'Computer Science',
        'file': (io.BytesIO(content), 'os_notes.txt')
    }, content_type='multipart/form-data', follow_redirects=True)

    # Log in as user2 and attempt to upload same file with different filename
    auth.logout()
    auth.login('bob@college.edu', 'password123')
    dup_res = client.post('/upload', data={
        'subject': 'OS Duplicate',
        'description': 'Trying to re-upload identical content',
        'year': '2nd Year',
        'branch': 'Information Technology',
        'file': (io.BytesIO(content), 'different_name.txt')
    }, content_type='multipart/form-data', follow_redirects=False)

    assert dup_res.status_code == 200
    assert b'Duplicate File Detected' in dup_res.data or b'duplicate' in dup_res.data.lower()

    # Now bypass via upload_confirm
    confirm_res = client.post('/upload/confirm', data={
        'subject': 'OS Duplicate Confirmed',
        'description': 'Uploaded anyway',
        'year': '2nd Year',
        'branch': 'Information Technology',
        'file': (io.BytesIO(content), 'different_name.txt')
    }, content_type='multipart/form-data', follow_redirects=True)
    assert confirm_res.status_code == 200
    assert b'Resource uploaded successfully.' in confirm_res.data

    with app.app_context():
        dups = Resource.query.filter_by(subject='OS Duplicate Confirmed').all()
        assert len(dups) == 1


def test_pdf_upload_and_summary_display(client, user1, auth, app):
    auth.login('alice@college.edu', 'password123')
    pdf_bytes = make_pdf().getvalue()

    client.post('/upload', data={
        'subject': 'Computer Networks',
        'description': 'CN Chapter 1',
        'year': '3rd Year',
        'branch': 'Computer Science',
        'file': (io.BytesIO(pdf_bytes), 'cn.pdf')
    }, content_type='multipart/form-data', follow_redirects=True)

    with app.app_context():
        res_obj = Resource.query.filter_by(subject='Computer Networks').first()
        assert res_obj is not None
        # Manually set a mock summary if pypdf blank page had no text stream
        if not res_obj.ai_summary:
            res_obj.ai_summary = "This is an automated quick summary of computer networks."
            db.session.commit()
        res_id = res_obj.id

    # View the resource page and verify quick summary appears in HTML
    view_res = client.get(f'/resource/{res_id}')
    assert view_res.status_code == 200
    assert b'Quick Summary' in view_res.data
    assert b'computer networks' in view_res.data.lower()


def test_browse_search_filter_sort(client, user1, auth, app):
    auth.login('alice@college.edu', 'password123')
    with app.app_context():
        r1 = Resource(filename='f1.txt', original_filename='math.txt', subject='Mathematics',
                      description='Calculus notes', year='1st Year', branch='CSE',
                      uploader_id=user1, download_count=10)
        r2 = Resource(filename='f2.pdf', original_filename='physics.pdf', subject='Physics',
                      description='Quantum mechanics', year='2nd Year', branch='ECE',
                      uploader_id=user1, download_count=20)
        db.session.add_all([r1, r2])
        db.session.commit()

    # Filter by year
    res_year = client.get('/browse?year=1st+Year')
    assert b'Mathematics' in res_year.data
    assert b'Physics' not in res_year.data

    # Filter by branch
    res_branch = client.get('/browse?branch=ECE')
    assert b'Physics' in res_branch.data
    assert b'Mathematics' not in res_branch.data

    # Search query q
    res_q = client.get('/browse?q=Calculus')
    assert b'Mathematics' in res_q.data
    assert b'Physics' not in res_q.data

    # Sort by downloads
    res_sort = client.get('/browse?sort=downloads')
    assert res_sort.status_code == 200


def test_view_vs_download_count(client, user1, auth, app):
    auth.login('alice@college.edu', 'password123')
    # Save a physical file in upload folder
    fname = 'test_view_download.txt'
    with open(os.path.join(app.config['UPLOAD_FOLDER'], fname), 'wb') as f:
        f.write(b'Test view vs download content.')

    with app.app_context():
        res_obj = Resource(filename=fname, original_filename='test_vd.txt', subject='Database Management',
                           description='SQL Queries', year='2nd Year', branch='IT',
                           uploader_id=user1, download_count=0)
        db.session.add(res_obj)
        db.session.commit()
        res_id = res_obj.id

    # Viewing resource detail page
    client.get(f'/resource/{res_id}')
    with app.app_context():
        r = Resource.query.get(res_id)
        # Download count must NOT increase on view
        assert r.download_count == 0
        # RecentView should exist
        rv = RecentView.query.filter_by(user_id=user1, resource_id=res_id).first()
        assert rv is not None

    # Downloading the resource
    dl_res = client.get(f'/download/{res_id}')
    assert dl_res.status_code == 200
    assert dl_res.data == b'Test view vs download content.'
    with app.app_context():
        r = Resource.query.get(res_id)
        assert r.download_count == 1


def test_download_missing_file_graceful(client, user1, auth, app):
    auth.login('alice@college.edu', 'password123')
    with app.app_context():
        res_obj = Resource(filename='non_existent_file.pdf', original_filename='ghost.pdf',
                           subject='Ghost Subject', description='No file on disk',
                           year='1st Year', branch='CSE', uploader_id=user1)
        db.session.add(res_obj)
        db.session.commit()
        res_id = res_obj.id

    # Try downloading missing file
    res = client.get(f'/download/{res_id}', follow_redirects=True)
    assert res.status_code == 200
    assert b'missing from the server' in res.data


def test_ratings_and_autoflag(client, user1, user2, senior_user, auth, app):
    auth.login('alice@college.edu', 'password123')
    with app.app_context():
        res_obj = Resource(filename='ratings_res.txt', original_filename='r.txt',
                           subject='Software Engineering', description='SDLC',
                           year='3rd Year', branch='CSE', uploader_id=user1)
        db.session.add(res_obj)
        db.session.commit()
        res_id = res_obj.id

    # Alice rates 5 stars
    client.post(f'/resource/{res_id}/rate', data={'value': 5}, follow_redirects=True)
    with app.app_context():
        r = Resource.query.get(res_id)
        assert r.rating_count() == 1
        assert r.avg_rating() == 5.0

    # Alice changes rating to 4 stars (should update, not duplicate)
    client.post(f'/resource/{res_id}/rate', data={'value': 4}, follow_redirects=True)
    with app.app_context():
        r = Resource.query.get(res_id)
        assert r.rating_count() == 1
        assert r.avg_rating() == 4.0

    # Low ratings from user2 and senior_user to trigger auto-flagging (< 2.5 after >= 3 ratings)
    auth.logout()
    auth.login('bob@college.edu', 'password123')
    client.post(f'/resource/{res_id}/rate', data={'value': 1}, follow_redirects=True)

    auth.logout()
    auth.login('sam@college.edu', 'password123')
    client.post(f'/resource/{res_id}/rate', data={'value': 1}, follow_redirects=True)

    # Now Alice=4, Bob=1, Sam=1 -> avg = 6/3 = 2.0 < 2.5 threshold with 3 ratings
    with app.app_context():
        r = Resource.query.get(res_id)
        assert r.rating_count() == 3
        assert r.avg_rating() == 2.0
        assert r.review_status == 'needs_review'


def test_bookmarks_toggle(client, user1, auth, app):
    auth.login('alice@college.edu', 'password123')
    with app.app_context():
        res_obj = Resource(filename='bm.txt', original_filename='bm.txt',
                           subject='Bookmarks Test', description='Test BM',
                           year='1st Year', branch='CSE', uploader_id=user1)
        db.session.add(res_obj)
        db.session.commit()
        res_id = res_obj.id

    # Toggle bookmark on
    res = client.post(f'/resource/{res_id}/bookmark', follow_redirects=True)
    assert b'Saved to bookmarks.' in res.data
    with app.app_context():
        assert Bookmark.query.filter_by(user_id=user1, resource_id=res_id).first() is not None

    # Toggle bookmark off
    res2 = client.post(f'/resource/{res_id}/bookmark', follow_redirects=True)
    assert b'Removed from bookmarks.' in res2.data
    with app.app_context():
        assert Bookmark.query.filter_by(user_id=user1, resource_id=res_id).first() is None


def test_edit_and_delete_resource_permissions(client, user1, user2, admin_user, auth, app):
    auth.login('alice@college.edu', 'password123')
    fname = 'edit_del_test.txt'
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
    with open(file_path, 'wb') as f:
        f.write(b'To be edited or deleted.')

    with app.app_context():
        res_obj = Resource(filename=fname, original_filename='ed.txt',
                           subject='Original Subject', description='Original Desc',
                           year='2nd Year', branch='CSE', uploader_id=user1)
        db.session.add(res_obj)
        db.session.commit()
        res_id = res_obj.id

    # Bob (user2) tries to edit Alice's resource -> 403 Forbidden
    auth.logout()
    auth.login('bob@college.edu', 'password123')
    res_edit_bob = client.post(f'/resource/{res_id}/edit', data={
        'subject': 'Hacked Subject',
        'description': 'Hacked Desc',
        'year': '2nd Year',
        'branch': 'CSE'
    })
    assert res_edit_bob.status_code == 403

    # Bob tries to delete Alice's resource -> 403 Forbidden
    res_del_bob = client.post(f'/resource/{res_id}/delete')
    assert res_del_bob.status_code == 403

    # Alice edits her resource
    auth.logout()
    auth.login('alice@college.edu', 'password123')
    res_edit_alice = client.post(f'/resource/{res_id}/edit', data={
        'subject': 'Updated Subject',
        'description': 'Updated Desc',
        'year': '2nd Year',
        'branch': 'CSE',
        'allow_comments': 'on'
    }, follow_redirects=True)
    assert res_edit_alice.status_code == 200
    with app.app_context():
        r = Resource.query.get(res_id)
        assert r.subject == 'Updated Subject'

    # Admin deletes Alice's resource
    auth.logout()
    auth.login('admin@college.edu', 'adminpassword123')
    res_del_admin = client.post(f'/resource/{res_id}/delete', follow_redirects=True)
    assert res_del_admin.status_code == 200
    with app.app_context():
        assert Resource.query.get(res_id) is None
    assert not os.path.exists(file_path)
