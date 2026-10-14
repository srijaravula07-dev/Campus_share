import os
import pytest
from app import (
    db, User, Resource, Comment, Rating, Bookmark, Report,
    Doubt, DoubtAnswer, Mentor, RecentView, Notification, ResourceRequest,
    delete_user_account
)

def test_complete_account_deletion_zero_orphans(client, user1, user2, auth, app):
    # Setup extensive relational graph for user1 (Alice):
    # 1. Alice creates a physical resource file on disk
    fname = 'alice_course_pack.pdf'
    fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
    with open(fpath, 'wb') as f:
        f.write(b'%PDF-1.4 Alice Course Pack Contents')

    with app.app_context():
        # Alice's resource
        alice_res = Resource(
            filename=fname, original_filename='pack.pdf', subject='Database Design',
            description='Full pack', year='3rd Year', branch='CSE', uploader_id=user1
        )
        # Bob's resource
        bob_res = Resource(
            filename='bob_notes.txt', original_filename='b.txt', subject='Operating Systems',
            description='Bob notes', year='3rd Year', branch='CSE', uploader_id=user2
        )
        db.session.add_all([alice_res, bob_res])
        db.session.flush()

        # Alice's interactions on Bob's resource
        alice_comment = Comment(content='Nice notes Bob', user_id=user1, resource_id=bob_res.id)
        alice_rating = Rating(value=5, user_id=user1, resource_id=bob_res.id)
        alice_bm = Bookmark(user_id=user1, resource_id=bob_res.id)
        alice_report = Report(reason='Wrong information', description='Reported by Alice',
                              user_id=user1, resource_id=bob_res.id)
        alice_view = RecentView(user_id=user1, resource_id=bob_res.id)

        # Bob's doubt & Alice's answer
        bob_doubt = Doubt(user_id=user2, subject='OS', title='What is a Semaphore?',
                          description='Need explanation')
        db.session.add(bob_doubt)
        db.session.flush()

        alice_doubt_ans = DoubtAnswer(doubt_id=bob_doubt.id, user_id=user1, content='A semaphore is a variable...')

        # Alice's own doubt
        alice_doubt = Doubt(user_id=user1, subject='DB', title='ACID properties in NoSQL?',
                            description='How is consistency maintained?')

        # Alice's mentor profile
        alice_mentor = Mentor(user_id=user1, bio='Senior database mentor', subjects='Databases', is_active=True)

        # Alice's notification
        alice_notif = Notification(user_id=user1, message='Welcome Alice')

        # Alice's resource request
        alice_req = ResourceRequest(title='Need past papers', subject='DB', year='3rd Year',
                                    branch='CSE', user_id=user1)

        # Bob's resource request fulfilled by Alice's resource
        bob_req = ResourceRequest(title='Need DB pack', subject='DB', year='3rd Year',
                                  branch='CSE', user_id=user2,
                                  fulfilled_resource_id=alice_res.id, status='fulfilled')

        db.session.add_all([
            alice_comment, alice_rating, alice_bm, alice_report, alice_view,
            alice_doubt_ans, alice_doubt, alice_mentor, alice_notif,
            alice_req, bob_req
        ])
        db.session.commit()

        alice_res_id = alice_res.id
        bob_res_id = bob_res.id
        bob_doubt_id = bob_doubt.id
        bob_req_id = bob_req.id

    assert os.path.exists(fpath)

    # Perform account deletion via Settings UI endpoint
    auth.login('alice@college.edu', 'password123')
    res = client.post('/settings', data={
        'action': 'delete_account',
        'confirm_text': 'DELETE'
    }, follow_redirects=True)
    assert res.status_code == 200
    assert b'Your account has been deleted.' in res.data

    # Verify physical file was purged from disk
    assert not os.path.exists(fpath)

    # Verify complete zero-orphan cleanup in DB
    with app.app_context():
        # User is deleted
        assert User.query.get(user1) is None

        # User's uploaded resources are deleted
        assert Resource.query.filter_by(uploader_id=user1).count() == 0
        assert Resource.query.get(alice_res_id) is None

        # User's comments are deleted
        assert Comment.query.filter_by(user_id=user1).count() == 0

        # User's ratings are deleted
        assert Rating.query.filter_by(user_id=user1).count() == 0

        # User's bookmarks are deleted
        assert Bookmark.query.filter_by(user_id=user1).count() == 0

        # User's reports are deleted
        assert Report.query.filter_by(user_id=user1).count() == 0

        # User's doubts are deleted
        assert Doubt.query.filter_by(user_id=user1).count() == 0

        # User's answers are deleted
        assert DoubtAnswer.query.filter_by(user_id=user1).count() == 0

        # User's mentor profile is deleted
        assert Mentor.query.filter_by(user_id=user1).count() == 0

        # User's recent views are deleted
        assert RecentView.query.filter_by(user_id=user1).count() == 0

        # User's notifications are deleted
        assert Notification.query.filter_by(user_id=user1).count() == 0

        # User's resource requests are deleted
        assert ResourceRequest.query.filter_by(user_id=user1).count() == 0

        # Bob's request has fulfilled_resource_id safely set to None (no dangling foreign key)
        r_bob_req = ResourceRequest.query.get(bob_req_id)
        assert r_bob_req is not None
        assert r_bob_req.fulfilled_resource_id is None

        # Bob's data remains intact
        assert User.query.get(user2) is not None
        assert Resource.query.get(bob_res_id) is not None
        assert Doubt.query.get(bob_doubt_id) is not None
