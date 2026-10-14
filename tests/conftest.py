import os
import shutil
import pytest
from werkzeug.security import generate_password_hash
from app import app as flask_app, db as _db, User

@pytest.fixture
def app(tmp_path):
    test_db = tmp_path / "test.db"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    flask_app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{test_db}",
        "UPLOAD_FOLDER": str(upload_dir),
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "test-secret-key-for-pytest",
        "SERVER_NAME": "localhost",
    })

    with flask_app.app_context():
        _db.create_all()
        yield flask_app
        _db.session.remove()
        _db.drop_all()

    # Clean up uploaded files if any
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def csrf_client(app):
    app.config["WTF_CSRF_ENABLED"] = True
    client = app.test_client()
    yield client
    app.config["WTF_CSRF_ENABLED"] = False


@pytest.fixture
def user1(app):
    with app.app_context():
        user = User(
            name="Alice Student",
            email="alice@college.edu",
            password=generate_password_hash("password123"),
            year="2nd Year",
            branch="Computer Science",
            role="user"
        )
        _db.session.add(user)
        _db.session.commit()
        return user.id


@pytest.fixture
def user2(app):
    with app.app_context():
        user = User(
            name="Bob Student",
            email="bob@college.edu",
            password=generate_password_hash("password123"),
            year="2nd Year",
            branch="Information Technology",
            role="user"
        )
        _db.session.add(user)
        _db.session.commit()
        return user.id


@pytest.fixture
def senior_user(app):
    with app.app_context():
        user = User(
            name="Senior Sam",
            email="sam@college.edu",
            password=generate_password_hash("password123"),
            year="3rd Year",
            branch="Computer Science",
            role="user"
        )
        _db.session.add(user)
        _db.session.commit()
        return user.id


@pytest.fixture
def junior_user(app):
    with app.app_context():
        user = User(
            name="Junior Jim",
            email="jim@college.edu",
            password=generate_password_hash("password123"),
            year="1st Year",
            branch="Mechanical",
            role="user"
        )
        _db.session.add(user)
        _db.session.commit()
        return user.id


@pytest.fixture
def admin_user(app):
    with app.app_context():
        user = User(
            name="Admin Officer",
            email="admin@college.edu",
            password=generate_password_hash("adminpassword123"),
            year="Faculty / Staff",
            branch="Administration",
            role="admin"
        )
        _db.session.add(user)
        _db.session.commit()
        return user.id


@pytest.fixture
def auth(client):
    class AuthActions:
        def login(self, email="alice@college.edu", password="password123"):
            return client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)

        def logout(self):
            return client.get('/logout', follow_redirects=True)

    return AuthActions()
