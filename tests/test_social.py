import pytest
from app import db, Resource, Comment, Doubt, DoubtAnswer, Mentor, ResourceRequest, User

def test_comment_creation_allowed(client, user1, user2, auth, app):
    with app.app_context():
        res = Resource(filename='c1.txt', original_filename='c1.txt', subject='Physics 101',
                       description='Notes', year='1st Year', branch='ECE', uploader_id=user1,
                       allow_comments=True)
        db.session.add(res)
        db.session.commit()
        res_id = res.id

    auth.login('bob@college.edu', 'password123')
    client.post(f'/resource/{res_id}', data={'content': 'Great notes, thank you!'}, follow_redirects=True)
    with app.app_context():
        c = Comment.query.filter_by(resource_id=res_id).first()
        assert c is not None
        assert c.content == 'Great notes, thank you!'
        assert c.user_id == user2


def test_comment_blocked_when_disabled_backend_enforced(client, user1, user2, auth, app):
    with app.app_context():
        res = Resource(filename='c2.txt', original_filename='c2.txt', subject='Chemistry',
                       description='Notes', year='1st Year', branch='ECE', uploader_id=user1,
                       allow_comments=False)
        db.session.add(res)
        db.session.commit()
        res_id = res.id

    auth.login('bob@college.edu', 'password123')
    # Try POSTing directly to the comment endpoint
    resp = client.post(f'/resource/{res_id}', data={'content': 'Trying to comment anyway'}, follow_redirects=True)
    assert b'disabled comments' in resp.data
    with app.app_context():
        assert Comment.query.filter_by(resource_id=res_id).first() is None


def test_comment_edit_permissions(client, user1, user2, auth, app):
    with app.app_context():
        res = Resource(filename='c3.txt', original_filename='c3.txt', subject='Math',
                       description='Notes', year='1st Year', branch='CSE', uploader_id=user1)
        db.session.add(res)
        db.session.flush()
        c = Comment(content='Initial comment', user_id=user1, resource_id=res.id)
        db.session.add(c)
        db.session.commit()
        comment_id = c.id
        res_id = res.id

    # Bob (user2) tries to edit Alice's comment -> 403
    auth.login('bob@college.edu', 'password123')
    res_unauth = client.post(f'/comment/{comment_id}/edit', data={'content': 'Hacked comment'})
    assert res_unauth.status_code == 403

    # Alice edits her comment
    auth.logout()
    auth.login('alice@college.edu', 'password123')
    res_auth = client.post(f'/comment/{comment_id}/edit', data={'content': 'Updated comment'}, follow_redirects=True)
    assert res_auth.status_code == 200
    with app.app_context():
        updated_c = Comment.query.get(comment_id)
        assert updated_c.content == 'Updated comment'


def test_comment_delete_permissions(client, user1, user2, senior_user, admin_user, auth, app):
    with app.app_context():
        # Alice uploads resource
        res = Resource(filename='c4.txt', original_filename='c4.txt', subject='Biology',
                       description='Notes', year='1st Year', branch='CSE', uploader_id=user1)
        db.session.add(res)
        db.session.flush()
        # Bob comments on Alice's resource
        c1 = Comment(content='Bob comment 1', user_id=user2, resource_id=res.id)
        c2 = Comment(content='Bob comment 2', user_id=user2, resource_id=res.id)
        c3 = Comment(content='Bob comment 3', user_id=user2, resource_id=res.id)
        db.session.add_all([c1, c2, c3])
        db.session.commit()
        c1_id, c2_id, c3_id = c1.id, c2.id, c3.id

    # Sam (senior_user, unrelated) tries to delete Bob's comment -> 403
    auth.login('sam@college.edu', 'password123')
    res_sam = client.post(f'/comment/{c1_id}/delete')
    assert res_sam.status_code == 403

    # Bob (comment author) deletes c1 -> Allowed
    auth.logout()
    auth.login('bob@college.edu', 'password123')
    res_bob = client.post(f'/comment/{c1_id}/delete', follow_redirects=True)
    assert res_bob.status_code == 200
    with app.app_context():
        assert Comment.query.get(c1_id) is None

    # Alice (resource uploader) deletes c2 -> Allowed
    auth.logout()
    auth.login('alice@college.edu', 'password123')
    res_alice = client.post(f'/comment/{c2_id}/delete', follow_redirects=True)
    assert res_alice.status_code == 200
    with app.app_context():
        assert Comment.query.get(c2_id) is None

    # Admin deletes c3 -> Allowed
    auth.logout()
    auth.login('admin@college.edu', 'adminpassword123')
    res_admin = client.post(f'/comment/{c3_id}/delete', follow_redirects=True)
    assert res_admin.status_code == 200
    with app.app_context():
        assert Comment.query.get(c3_id) is None


def test_doubt_lifecycle_and_accepted_answer_revert(client, user1, user2, auth, app):
    # Alice posts a doubt
    auth.login('alice@college.edu', 'password123')
    client.post('/doubts/new', data={
        'subject': 'Data Structures',
        'title': 'Difference between B-tree and B+ tree?',
        'description': 'Can someone explain the key differences?',
        'tag': 'Trees'
    }, follow_redirects=True)

    with app.app_context():
        doubt = Doubt.query.filter_by(title='Difference between B-tree and B+ tree?').first()
        assert doubt is not None
        assert doubt.status == 'open'
        doubt_id = doubt.id

    # Bob posts an answer
    auth.logout()
    auth.login('bob@college.edu', 'password123')
    client.post(f'/doubts/{doubt_id}', data={'content': 'B+ tree stores keys only in leaf nodes.'}, follow_redirects=True)

    with app.app_context():
        ans = DoubtAnswer.query.filter_by(doubt_id=doubt_id).first()
        assert ans is not None
        ans_id = ans.id

    # Bob edits his answer
    client.post(f'/doubts/answer/{ans_id}/edit', data={'content': 'Updated explanation for B+ tree.'}, follow_redirects=True)
    with app.app_context():
        assert DoubtAnswer.query.get(ans_id).content == 'Updated explanation for B+ tree.'

    # Bob tries to accept his own answer -> 403 Forbidden (only doubt author can accept)
    res_unauth_accept = client.post(f'/doubts/answer/{ans_id}/accept')
    assert res_unauth_accept.status_code == 403

    # Alice (doubt author) accepts Bob's answer
    auth.logout()
    auth.login('alice@college.edu', 'password123')
    client.post(f'/doubts/answer/{ans_id}/accept', follow_redirects=True)
    with app.app_context():
        a = DoubtAnswer.query.get(ans_id)
        d = Doubt.query.get(doubt_id)
        assert a.is_accepted is True
        assert d.status == 'resolved'

    # Bob deletes his accepted answer -> status must revert to 'open'
    auth.logout()
    auth.login('bob@college.edu', 'password123')
    client.post(f'/doubts/answer/{ans_id}/delete', follow_redirects=True)
    with app.app_context():
        assert DoubtAnswer.query.get(ans_id) is None
        d = Doubt.query.get(doubt_id)
        assert d.status == 'open'


def test_senior_connect_eligibility_and_settings_sync(client, junior_user, senior_user, auth, app):
    # Junior (1st Year) tries to create mentor profile -> rejected server-side
    auth.login('jim@college.edu', 'password123')
    res_junior = client.get('/mentors/profile', follow_redirects=True)
    assert b'Only 3rd and 4th year students' in res_junior.data

    res_junior_post = client.post('/mentors/profile', data={
        'bio': 'I am a 1st year mentor',
        'subjects': 'Math',
        'is_active': 'on'
    }, follow_redirects=True)
    assert b'Only 3rd and 4th year students' in res_junior_post.data

    # Senior (3rd Year) creates mentor profile -> allowed
    auth.logout()
    auth.login('sam@college.edu', 'password123')
    res_senior_post = client.post('/mentors/profile', data={
        'bio': 'Experienced senior helping with CS',
        'subjects': 'Algorithms, Systems',
        'is_active': 'on'
    }, follow_redirects=True)
    assert res_senior_post.status_code == 200
    assert b'Mentor profile saved.' in res_senior_post.data

    with app.app_context():
        m = Mentor.query.filter_by(user_id=senior_user).first()
        assert m is not None
        assert m.is_active is True

    # Check that Senior Sam appears as a mentor card in /mentors list
    list_res = client.get('/mentors')
    assert b'<h3>Senior Sam</h3>' in list_res.data

    # Sam changes year to 2nd Year in Settings -> Mentor profile must automatically deactivate
    client.post('/settings', data={
        'action': 'update_profile',
        'name': 'Senior Sam',
        'email': 'sam@college.edu',
        'year': '2nd Year',
        'branch': 'Computer Science'
    }, follow_redirects=True)

    with app.app_context():
        m_after = Mentor.query.filter_by(user_id=senior_user).first()
        assert m_after.is_active is False

    # Sam should no longer appear in mentor cards on /mentors
    list_res_after = client.get('/mentors')
    assert b'<h3>Senior Sam</h3>' not in list_res_after.data
    assert b'No mentors are currently available' in list_res_after.data


def test_resource_requests_lifecycle(client, user1, user2, auth, app):
    # Alice posts a resource request
    auth.login('alice@college.edu', 'password123')
    client.post('/requests/new', data={
        'title': 'Need Compiler Design past papers',
        'description': 'Looking for 2024 end sem papers',
        'subject': 'Compiler Design',
        'year': '3rd Year',
        'branch': 'CSE'
    }, follow_redirects=True)

    with app.app_context():
        req = ResourceRequest.query.filter_by(title='Need Compiler Design past papers').first()
        assert req is not None
        assert req.status == 'open'
        req_id = req.id
        # Also create a candidate resource
        res = Resource(filename='cd.pdf', original_filename='cd.pdf', subject='Compiler Design',
                       year='3rd Year', branch='CSE', uploader_id=user2)
        db.session.add(res)
        db.session.commit()
        res_id = res.id

    # Bob fulfills Alice's request with the existing resource
    auth.logout()
    auth.login('bob@college.edu', 'password123')
    client.post(f'/requests/{req_id}', data={
        'action': 'fulfill_existing',
        'resource_id': res_id
    }, follow_redirects=True)

    with app.app_context():
        r_fulfilled = ResourceRequest.query.get(req_id)
        assert r_fulfilled.status == 'fulfilled'
        assert r_fulfilled.fulfilled_resource_id == res_id

    # Alice marks status back to closed
    auth.logout()
    auth.login('alice@college.edu', 'password123')
    client.post(f'/requests/{req_id}', data={
        'action': 'mark_status',
        'status': 'closed'
    }, follow_redirects=True)

    with app.app_context():
        r_closed = ResourceRequest.query.get(req_id)
        assert r_closed.status == 'closed'
