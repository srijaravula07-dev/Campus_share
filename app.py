import os
import re
import hashlib
from datetime import datetime
from functools import wraps
from urllib.parse import urlsplit

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Environment & Config
FLASK_ENV = os.environ.get('FLASK_ENV', '').lower()
APP_ENV = os.environ.get('APP_ENV', '').lower()
IS_PRODUCTION = (FLASK_ENV == 'production' or APP_ENV == 'production')

SECRET_KEY = os.environ.get('SECRET_KEY')
if IS_PRODUCTION and not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable must be set in production!")
if not SECRET_KEY:
    SECRET_KEY = 'dev-secret-key-change-in-production'

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
else:
    DATABASE_URL = 'sqlite:///' + os.path.join(BASE_DIR, 'campus_share.db')

UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'static', 'uploads'))
ALLOWED_EXTENSIONS = {'pdf', 'ppt', 'pptx', 'doc', 'docx', 'txt', 'xls', 'xlsx', 'zip', 'jpg', 'jpeg', 'png'}

# Configurable thresholds for automatic low-quality flagging
LOW_QUALITY_MIN_RATINGS = 3
LOW_QUALITY_THRESHOLD = 2.5

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH', 25 * 1024 * 1024))  # 25 MB

# Secure session cookies
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
if IS_PRODUCTION:
    app.config['SESSION_COOKIE_SECURE'] = True

csrf = CSRFProtect(app)
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

YEARS = ['1st Year', '2nd Year', '3rd Year', '4th Year']
BRANCHES = ['CSE', 'ECE', 'EEE', 'MECH', 'CIVIL', 'IT', 'OTHER']
REPORT_REASONS = ['Wrong information', 'Misleading content', 'Broken file', 'Duplicate resource', 'Inappropriate content', 'Other']


# ================= Models =================

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    year = db.Column(db.String(20), nullable=False)
    branch = db.Column(db.String(20), nullable=False)
    role = db.Column(db.String(20), default='student', nullable=False)  # 'student' or 'admin'

    theme = db.Column(db.String(10), default='light', nullable=False)  # light / dark
    notify_comments = db.Column(db.Boolean, default=True, nullable=False)
    notify_requests = db.Column(db.Boolean, default=True, nullable=False)
    notify_ratings = db.Column(db.Boolean, default=True, nullable=False)
    notify_moderation = db.Column(db.Boolean, default=True, nullable=False)
    show_profile_on_uploads = db.Column(db.Boolean, default=True, nullable=False)

    is_mentor = db.Column(db.Boolean, default=False, nullable=False)
    mentor_subjects = db.Column(db.String(300), nullable=True)  # comma-separated subject names
    mentor_bio = db.Column(db.String(300), nullable=True)

    resources = db.relationship('Resource', backref='uploader', lazy=True)
    comments = db.relationship('Comment', backref='author', lazy=True)

    def is_admin(self):
        return self.role == 'admin'

    def mentor_subject_list(self):
        if not self.mentor_subjects:
            return []
        return [s.strip() for s in self.mentor_subjects.split(',') if s.strip()]


class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    year = db.Column(db.String(20), nullable=False)
    branch = db.Column(db.String(20), nullable=False)
    allow_comments = db.Column(db.Boolean, default=True, nullable=False)
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)

    file_hash = db.Column(db.String(64), nullable=True, index=True)
    download_count = db.Column(db.Integer, default=0, nullable=False)
    review_status = db.Column(db.String(20), default='ok', nullable=False)  # ok / needs_review / removed
    ai_summary = db.Column(db.Text, nullable=True)

    comments = db.relationship('Comment', backref='resource', lazy=True, cascade='all, delete-orphan')
    ratings = db.relationship('Rating', backref='resource', lazy=True, cascade='all, delete-orphan')
    reports = db.relationship('Report', backref='resource', lazy=True, cascade='all, delete-orphan')
    bookmarks = db.relationship('Bookmark', backref='resource', lazy=True, cascade='all, delete-orphan')

    def avg_rating(self):
        if not self.ratings:
            return 0
        return round(sum(r.value for r in self.ratings) / len(self.ratings), 1)

    def rating_count(self):
        return len(self.ratings)


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class RecentView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow)

    resource = db.relationship('Resource')

    __table_args__ = (db.UniqueConstraint('user_id', 'resource_id', name='uq_user_resource_view'),)


class Rating(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    value = db.Column(db.Integer, nullable=False)  # 1-5
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'resource_id', name='uq_user_resource_rating'),)


class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)
    reason = db.Column(db.String(60), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='open', nullable=False)  # open / resolved / dismissed
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    reporter = db.relationship('User')

    __table_args__ = (db.UniqueConstraint('user_id', 'resource_id', 'reason', name='uq_user_resource_reason'),)


class Bookmark(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'resource_id', name='uq_user_resource_bookmark'),)


class ResourceRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    subject = db.Column(db.String(120), nullable=False)
    year = db.Column(db.String(20), nullable=False)
    branch = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='open', nullable=False)  # open / fulfilled / closed
    fulfilled_resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    requester = db.relationship('User', foreign_keys=[user_id])
    fulfilled_resource = db.relationship('Resource', foreign_keys=[fulfilled_resource_id])


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(255), nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class Doubt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject = db.Column(db.String(120), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    tag = db.Column(db.String(80), nullable=True)
    status = db.Column(db.String(20), default='open', nullable=False)  # open / resolved
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    asker = db.relationship('User')
    answers = db.relationship('DoubtAnswer', backref='doubt', lazy=True, cascade='all, delete-orphan')

    def answer_count(self):
        return len(self.answers)


class DoubtAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    doubt_id = db.Column(db.Integer, db.ForeignKey('doubt.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_accepted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = db.relationship('User')


MENTOR_ELIGIBLE_YEARS = {'3rd Year', '4th Year'}


class Mentor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    bio = db.Column(db.Text, nullable=True)
    subjects = db.Column(db.String(300), nullable=False, default='')  # comma-separated
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User')

    def subject_list(self):
        return [s.strip() for s in self.subjects.split(',') if s.strip()]


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ================= Helpers =================

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def file_ext(filename):
    return filename.rsplit('.', 1)[1].lower() if '.' in filename else ''


app.jinja_env.filters['file_ext'] = file_ext


def hash_file(file_storage):
    """Compute sha256 of an uploaded file stream, then reset the pointer."""
    file_storage.stream.seek(0)
    sha256 = hashlib.sha256()
    for chunk in iter(lambda: file_storage.stream.read(8192), b''):
        sha256.update(chunk)
    file_storage.stream.seek(0)
    return sha256.hexdigest()


def generate_pdf_summary(file_path, max_sentences=5):
    """
    Auto-generate a short summary of a PDF's content.

    This extracts real text from the PDF (title/heading cues + opening
    sentences from the first few pages) and condenses it — no external
    AI API is called. It's a lightweight extractive summary, labeled as
    such to students, not a paid LLM summarization.
    """
    if PdfReader is None:
        return None
    try:
        reader = PdfReader(file_path)
        if getattr(reader, 'is_encrypted', False):
            return None
        text_parts = []
        for page in reader.pages[:6]:  # first few pages is enough context
            try:
                extracted = page.extract_text()
                if extracted:
                    text_parts.append(extracted)
            except Exception:
                continue
        full_text = ' '.join(text_parts)
        full_text = re.sub(r'\s+', ' ', full_text).strip()
        if not full_text:
            return None

        sentences = re.split(r'(?<=[.!?])\s+', full_text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 25]
        summary = ' '.join(sentences[:max_sentences])
        if len(summary) > 600:
            summary = summary[:600].rsplit(' ', 1)[0] + '…'
        return summary or None
    except Exception:
        return None


def is_safe_redirect_url(target):
    """Ensure redirect URL is local and cannot escape the host."""
    if not target:
        return False
    # Must start with single '/', and not '//' or '/\\'
    if not target.startswith('/') or target.startswith('//') or target.startswith('/\\'):
        return False
    # Disallow backslashes and control characters
    if '\\' in target or any(ord(c) < 32 for c in target):
        return False
    if not target.startswith('/') or target.startswith('//') or '\\' in target:
        return False
    try:
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            return False
    except Exception:
        return False
    return True


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    flash('Your session expired or the form submission was invalid. Please try again.', 'danger')
    return redirect(request.referrer or url_for('login' if not current_user.is_authenticated else 'index'))


def notify(user_id, message, link=None):
    db.session.add(Notification(user_id=user_id, message=message, link=link))


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def check_low_quality(resource):
    """Auto-flag a resource as needs_review if it has enough low ratings."""
    if resource.review_status == 'removed':
        return
    if resource.rating_count() >= LOW_QUALITY_MIN_RATINGS and resource.avg_rating() < LOW_QUALITY_THRESHOLD:
        if resource.review_status != 'needs_review':
            resource.review_status = 'needs_review'
    elif resource.review_status == 'needs_review':
        if resource.rating_count() < LOW_QUALITY_MIN_RATINGS or resource.avg_rating() >= LOW_QUALITY_THRESHOLD:
            resource.review_status = 'ok'


def delete_user_account(user_id):
    """Safely delete a user and all dependent records in a single transaction with physical file cleanup."""
    user = User.query.get(user_id)
    if not user:
        return False

    # 1. Collect user's uploaded resources and physical file paths
    user_resources = Resource.query.filter_by(uploader_id=user_id).all()
    resource_ids = [r.id for r in user_resources]
    files_to_remove = [os.path.join(app.config['UPLOAD_FOLDER'], r.filename) for r in user_resources]

    # 2. Nullify fulfilled_resource_id on any ResourceRequests pointing to user's resources
    if resource_ids:
        ResourceRequest.query.filter(ResourceRequest.fulfilled_resource_id.in_(resource_ids)).update(
            {'fulfilled_resource_id': None}, synchronize_session=False
        )
        # 3. Delete other users' RecentViews on user's resources
        RecentView.query.filter(RecentView.resource_id.in_(resource_ids)).delete(synchronize_session=False)

    # 4. Delete user's resources (cascades comments, ratings, reports, bookmarks on those resources)
    for r in user_resources:
        db.session.delete(r)

    # 5. Delete user's direct records across all tables
    Mentor.query.filter_by(user_id=user_id).delete()
    Bookmark.query.filter_by(user_id=user_id).delete()
    RecentView.query.filter_by(user_id=user_id).delete()
    Rating.query.filter_by(user_id=user_id).delete()
    Report.query.filter_by(user_id=user_id).delete()
    Comment.query.filter_by(user_id=user_id).delete()
    Notification.query.filter_by(user_id=user_id).delete()
    ResourceRequest.query.filter_by(user_id=user_id).delete()

    # 6. Delete user's doubts (cascades to answers on user's doubts)
    for d in Doubt.query.filter_by(user_id=user_id).all():
        db.session.delete(d)

    # 7. Delete user's answers on other people's doubts & recalculate status if accepted
    user_answers = DoubtAnswer.query.filter_by(user_id=user_id).all()
    for ans in user_answers:
        if ans.is_accepted:
            parent_doubt = Doubt.query.get(ans.doubt_id)
            if parent_doubt:
                other_accepted = [a for a in parent_doubt.answers if a.id != ans.id and a.is_accepted]
                if not other_accepted:
                    parent_doubt.status = 'open'
        db.session.delete(ans)

    # 8. Delete the User record
    db.session.delete(user)

    # 9. Commit transaction and clean up physical files
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    for fpath in files_to_remove:
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except OSError:
                pass

    return True


@app.before_request
def require_login():
    open_endpoints = {'login', 'register', 'static'}
    if request.endpoint and request.endpoint not in open_endpoints and not current_user.is_authenticated:
        return redirect(url_for('login', next=request.path))


@app.context_processor
def inject_globals():
    unread_count = 0
    if current_user.is_authenticated:
        unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return dict(unread_notif_count=unread_count)


# ================= Auth =================

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        year = request.form.get('year', '')
        branch = request.form.get('branch', '')

        if not all([name, email, password, confirm_password, year, branch]):
            flash('Please fill in all fields.', 'danger')
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('register'))

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists.', 'danger')
            return redirect(url_for('register'))

        user = User(
            name=name, email=email, password=generate_password_hash(password),
            year=year, branch=branch,
        )
        db.session.add(user)
        db.session.commit()
        flash('Account created. Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', years=YEARS, branches=BRANCHES)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()

        user = User.query.filter_by(email=email).first()
        if not user:
            flash('No account found with that email. Please register first.', 'danger')
            return redirect(url_for('login'))
        if not check_password_hash(user.password, password):
            flash('Incorrect password. Please try again.', 'danger')
            return redirect(url_for('login'))

        login_user(user)
        flash('Logged in successfully.', 'success')
        next_page = request.args.get('next')
        if next_page and not is_safe_redirect_url(next_page):
            next_page = None
        return redirect(next_page or url_for('index'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out.', 'info')
    return redirect(url_for('login'))


# ================= Browse / Home =================

@app.route('/')
@app.route('/browse')
def index():
    year = request.args.get('year', '')
    branch = request.args.get('branch', '')
    subject = request.args.get('subject', '')
    q = request.args.get('q', '').strip()
    ftype = request.args.get('type', '')
    sort = request.args.get('sort', 'latest')

    query = Resource.query.filter(Resource.review_status != 'removed').options(db.selectinload(Resource.ratings))

    if year:
        query = query.filter_by(year=year)
    if branch:
        query = query.filter_by(branch=branch)
    if subject:
        query = query.filter(Resource.subject.ilike(f'%{subject}%'))
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Resource.subject.ilike(like), Resource.description.ilike(like),
                                     Resource.original_filename.ilike(like)))

    resources = query.all()

    if ftype:
        resources = [r for r in resources if file_ext(r.filename) == ftype]

    if sort == 'downloads':
        resources.sort(key=lambda r: r.download_count, reverse=True)
    elif sort == 'rating':
        resources.sort(key=lambda r: (r.avg_rating(), r.rating_count()), reverse=True)
    else:
        resources.sort(key=lambda r: r.upload_date or datetime.min, reverse=True)

    file_types = sorted({file_ext(r.filename) for r in Resource.query.filter(Resource.review_status != 'removed').all()})

    return render_template(
        'index.html', resources=resources, years=YEARS, branches=BRANCHES, file_types=file_types,
        selected_year=year, selected_branch=branch, selected_subject=subject,
        selected_q=q, selected_type=ftype, selected_sort=sort,
    )


# ================= Upload =================

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        description = request.form.get('description', '').strip()
        year = request.form.get('year', '')
        branch = request.form.get('branch', '')
        allow_comments = request.form.get('allow_comments') == 'on'
        confirm_duplicate = request.form.get('confirm_duplicate') == '1'
        file = request.files.get('file')

        if not all([subject, year, branch]) or not file or file.filename == '':
            flash('Please fill all fields and choose a file.', 'danger')
            return redirect(url_for('upload'))

        if not allowed_file(file.filename):
            flash('That file type is not allowed. Allowed: PDF, PPT/PPTX, DOC/DOCX, XLS/XLSX, TXT, ZIP, JPG, PNG.', 'danger')
            return redirect(url_for('upload'))

        file_hash = hash_file(file)

        if not confirm_duplicate:
            existing = Resource.query.filter_by(file_hash=file_hash).first()
            if existing:
                return render_template('duplicate_warning.html', existing=existing,
                                        subject=subject, description=description, year=year,
                                        branch=branch, allow_comments=allow_comments)

        original_filename = secure_filename(file.filename)
        ext = original_filename.rsplit('.', 1)[1].lower()
        unique_name = f"{current_user.id}_{int(datetime.utcnow().timestamp())}.{ext}"
        saved_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
        file.save(saved_path)

        ai_summary = generate_pdf_summary(saved_path) if ext == 'pdf' else None

        resource = Resource(
            filename=unique_name, original_filename=original_filename, subject=subject,
            description=description, year=year, branch=branch, allow_comments=allow_comments,
            uploader_id=current_user.id, file_hash=file_hash, ai_summary=ai_summary,
        )
        db.session.add(resource)
        db.session.commit()

        matching_requests = ResourceRequest.query.filter_by(
            status='open', subject=subject, year=year, branch=branch
        ).all()
        for req in matching_requests:
            if req.user_id != current_user.id and req.requester and req.requester.notify_requests:
                notify(req.user_id, f'A new resource "{subject}" was uploaded that may match your request "{req.title}".',
                       link=url_for('view_resource', resource_id=resource.id))
        db.session.commit()

        flash('Resource uploaded successfully.', 'success')
        return redirect(url_for('index'))

    return render_template('upload.html', years=YEARS, branches=BRANCHES)


@app.route('/upload/confirm', methods=['POST'])
@login_required
def upload_confirm():
    """Re-submit the upload after the user chose 'upload anyway' on a duplicate warning."""
    file = request.files.get('file')
    if not file or file.filename == '':
        flash('File missing — please choose the file again.', 'danger')
        return redirect(url_for('upload'))

    subject = request.form.get('subject', '').strip()
    description = request.form.get('description', '').strip()
    year = request.form.get('year', '')
    branch = request.form.get('branch', '')
    allow_comments = request.form.get('allow_comments') == 'on'

    if not allowed_file(file.filename):
        flash('That file type is not allowed.', 'danger')
        return redirect(url_for('upload'))

    file_hash = hash_file(file)
    original_filename = secure_filename(file.filename)
    ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
    unique_name = f"{current_user.id}_{int(datetime.utcnow().timestamp())}.{ext}"
    saved_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
    file.save(saved_path)

    ai_summary = generate_pdf_summary(saved_path) if ext == 'pdf' else None

    resource = Resource(
        filename=unique_name, original_filename=original_filename, subject=subject,
        description=description, year=year, branch=branch, allow_comments=allow_comments,
        uploader_id=current_user.id, file_hash=file_hash, ai_summary=ai_summary,
    )
    db.session.add(resource)
    db.session.commit()

    matching_requests = ResourceRequest.query.filter_by(
        status='open', subject=subject, year=year, branch=branch
    ).all()
    for req in matching_requests:
        if req.user_id != current_user.id and req.requester and req.requester.notify_requests:
            notify(req.user_id, f'A new resource "{subject}" was uploaded that may match your request "{req.title}".',
                   link=url_for('view_resource', resource_id=resource.id))
    db.session.commit()

    flash('Resource uploaded successfully.', 'success')
    return redirect(url_for('index'))


# ================= Resource detail / view / download =================

@app.route('/resource/<int:resource_id>', methods=['GET', 'POST'])
@login_required
def view_resource(resource_id):
    resource = Resource.query.get_or_404(resource_id)

    if request.method == 'POST':
        if not resource.allow_comments:
            flash('The uploader has disabled comments on this resource.', 'danger')
            return redirect(url_for('view_resource', resource_id=resource.id))

        content = request.form.get('content', '').strip()
        if content:
            comment = Comment(content=content, user_id=current_user.id, resource_id=resource.id)
            db.session.add(comment)
            if resource.uploader_id != current_user.id:
                uploader = User.query.get(resource.uploader_id)
                if uploader and uploader.notify_comments:
                    notify(uploader.id, f'{current_user.name} commented on your resource "{resource.subject}".',
                           link=url_for('view_resource', resource_id=resource.id))
            db.session.commit()
        return redirect(url_for('view_resource', resource_id=resource.id))

    existing_view = RecentView.query.filter_by(user_id=current_user.id, resource_id=resource.id).first()
    if existing_view:
        existing_view.viewed_at = datetime.utcnow()
    else:
        db.session.add(RecentView(user_id=current_user.id, resource_id=resource.id))
    db.session.commit()

    comments = Comment.query.filter_by(resource_id=resource.id).order_by(Comment.timestamp.asc()).all()

    my_rating = None
    r = Rating.query.filter_by(user_id=current_user.id, resource_id=resource.id).first()
    my_rating = r.value if r else None

    is_bookmarked = Bookmark.query.filter_by(user_id=current_user.id, resource_id=resource.id).first() is not None

    related = Resource.query.filter(
        Resource.id != resource.id,
        Resource.review_status != 'removed',
        Resource.subject == resource.subject,
    ).limit(6).all()
    if len(related) < 4:
        exclude_ids = [r.id for r in related] + [resource.id]
        extra = Resource.query.filter(
            Resource.review_status != 'removed',
            Resource.year == resource.year,
            Resource.branch == resource.branch,
            ~Resource.id.in_(exclude_ids),
        ).limit(6 - len(related)).all()
        related += extra

    return render_template('resource.html', resource=resource, comments=comments, my_rating=my_rating,
                            is_bookmarked=is_bookmarked, related=related, report_reasons=REPORT_REASONS)


@app.route('/download/<int:resource_id>')
@login_required
def download(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], resource.filename)
    if not os.path.exists(file_path):
        flash('This file is missing from the server and cannot be downloaded.', 'danger')
        return redirect(url_for('view_resource', resource_id=resource.id))

    resource.download_count += 1
    db.session.commit()
    return send_from_directory(app.config['UPLOAD_FOLDER'], resource.filename,
                                as_attachment=True, download_name=resource.original_filename)


@app.route('/view-file/<int:resource_id>')
@login_required
def view_file(resource_id):
    """Inline view (e.g. PDF preview) — does not count as a download."""
    resource = Resource.query.get_or_404(resource_id)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], resource.filename)
    if not os.path.exists(file_path):
        flash('This file is missing from the server.', 'danger')
        return redirect(url_for('view_resource', resource_id=resource.id))
    return send_from_directory(app.config['UPLOAD_FOLDER'], resource.filename, as_attachment=False)


# ================= Resource management (edit / delete) =================

@app.route('/resource/<int:resource_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_resource(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    if resource.uploader_id != current_user.id and not current_user.is_admin():
        abort(403)

    if request.method == 'POST':
        resource.subject = request.form.get('subject', '').strip() or resource.subject
        resource.description = request.form.get('description', '').strip()
        resource.year = request.form.get('year', resource.year)
        resource.branch = request.form.get('branch', resource.branch)
        resource.allow_comments = request.form.get('allow_comments') == 'on'
        db.session.commit()
        flash('Resource updated.', 'success')
        return redirect(url_for('view_resource', resource_id=resource.id))

    return render_template('edit_resource.html', resource=resource, years=YEARS, branches=BRANCHES)


@app.route('/resource/<int:resource_id>/delete', methods=['POST'])
@login_required
def delete_resource(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    if resource.uploader_id != current_user.id and not current_user.is_admin():
        abort(403)

    file_path = os.path.join(app.config['UPLOAD_FOLDER'], resource.filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    RecentView.query.filter_by(resource_id=resource.id).delete()
    ResourceRequest.query.filter_by(fulfilled_resource_id=resource.id).update({'fulfilled_resource_id': None})
    db.session.delete(resource)  # cascades comments, ratings, reports, bookmarks
    db.session.commit()
    flash('Resource deleted.', 'success')
    return redirect(url_for('my_uploads'))


# ================= Comments (edit/delete) =================

@app.route('/comment/<int:comment_id>/edit', methods=['POST'])
@login_required
def edit_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.user_id != current_user.id:
        abort(403)
    content = request.form.get('content', '').strip()
    if content:
        comment.content = content
        db.session.commit()
        flash('Comment updated.', 'success')
    return redirect(url_for('view_resource', resource_id=comment.resource_id))


@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    resource_id = comment.resource_id
    resource = Resource.query.get(resource_id)
    if comment.user_id != current_user.id and resource.uploader_id != current_user.id and not current_user.is_admin():
        abort(403)
    db.session.delete(comment)
    db.session.commit()
    flash('Comment deleted.', 'success')
    return redirect(url_for('view_resource', resource_id=resource_id))


# ================= Ratings =================

@app.route('/resource/<int:resource_id>/rate', methods=['POST'])
@login_required
def rate_resource(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    try:
        value = int(request.form.get('value', 0))
    except ValueError:
        value = 0
    if value < 1 or value > 5:
        flash('Rating must be between 1 and 5 stars.', 'danger')
        return redirect(url_for('view_resource', resource_id=resource.id))

    existing = Rating.query.filter_by(user_id=current_user.id, resource_id=resource.id).first()
    if existing:
        existing.value = value
        existing.timestamp = datetime.utcnow()
    else:
        db.session.add(Rating(value=value, user_id=current_user.id, resource_id=resource.id))
        if resource.uploader_id != current_user.id:
            uploader = User.query.get(resource.uploader_id)
            if uploader and uploader.notify_ratings:
                notify(uploader.id, f'{current_user.name} rated your resource "{resource.subject}" {value}\u2605.',
                       link=url_for('view_resource', resource_id=resource.id))

    db.session.flush()
    check_low_quality(resource)
    db.session.commit()
    flash('Thanks for rating!', 'success')
    return redirect(url_for('view_resource', resource_id=resource.id))


# ================= Bookmarks =================

@app.route('/resource/<int:resource_id>/bookmark', methods=['POST'])
@login_required
def toggle_bookmark(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    existing = Bookmark.query.filter_by(user_id=current_user.id, resource_id=resource.id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        flash('Removed from bookmarks.', 'info')
    else:
        db.session.add(Bookmark(user_id=current_user.id, resource_id=resource.id))
        db.session.commit()
        flash('Saved to bookmarks.', 'success')
    return redirect(url_for('view_resource', resource_id=resource.id))


@app.route('/bookmarks')
@login_required
def bookmarks():
    marks = (Bookmark.query.filter_by(user_id=current_user.id)
             .order_by(Bookmark.timestamp.desc()).all())
    return render_template('bookmarks.html', marks=marks)


# ================= Reports =================

@app.route('/resource/<int:resource_id>/report', methods=['POST'])
@login_required
def report_resource(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    reason = request.form.get('reason', '')
    description = request.form.get('description', '').strip()

    if reason not in REPORT_REASONS:
        flash('Please choose a valid reason.', 'danger')
        return redirect(url_for('view_resource', resource_id=resource.id))

    existing = Report.query.filter_by(user_id=current_user.id, resource_id=resource.id, reason=reason).first()
    if existing:
        flash('You already reported this resource for this reason.', 'info')
        return redirect(url_for('view_resource', resource_id=resource.id))

    db.session.add(Report(user_id=current_user.id, resource_id=resource.id, reason=reason, description=description))
    uploader = User.query.get(resource.uploader_id)
    if uploader and uploader.notify_moderation:
        notify(uploader.id, f'Your resource "{resource.subject}" was reported and is under review.',
               link=url_for('view_resource', resource_id=resource.id))
    db.session.commit()
    flash('Report submitted. Our moderators will review it.', 'success')
    return redirect(url_for('view_resource', resource_id=resource.id))


# ================= Resource Requests =================

@app.route('/requests')
@login_required
def list_requests():
    status = request.args.get('status', 'open')
    query = ResourceRequest.query
    if status in ('open', 'fulfilled', 'closed'):
        query = query.filter_by(status=status)
    reqs = query.order_by(ResourceRequest.timestamp.desc()).all()
    return render_template('requests.html', requests=reqs, selected_status=status)


@app.route('/requests/new', methods=['GET', 'POST'])
@login_required
def new_request():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        subject = request.form.get('subject', '').strip()
        year = request.form.get('year', '')
        branch = request.form.get('branch', '')

        if not all([title, subject, year, branch]):
            flash('Please fill in all required fields.', 'danger')
            return redirect(url_for('new_request'))

        req = ResourceRequest(title=title, description=description, subject=subject,
                               year=year, branch=branch, user_id=current_user.id)
        db.session.add(req)
        db.session.commit()
        flash('Request posted.', 'success')
        return redirect(url_for('list_requests'))

    return render_template('new_request.html', years=YEARS, branches=BRANCHES)


@app.route('/requests/<int:request_id>', methods=['GET', 'POST'])
@login_required
def view_request(request_id):
    req = ResourceRequest.query.get_or_404(request_id)

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'fulfill_existing':
            resource_id = request.form.get('resource_id')
            resource = Resource.query.get(resource_id)
            if not resource:
                flash('Resource not found.', 'danger')
                return redirect(url_for('view_request', request_id=req.id))
            req.fulfilled_resource_id = resource.id
            req.status = 'fulfilled'
            db.session.commit()
            if req.requester.notify_requests:
                notify(req.user_id, f'{current_user.name} fulfilled your request "{req.title}".',
                       link=url_for('view_request', request_id=req.id))
                db.session.commit()
            flash('Request marked as fulfilled with that resource.', 'success')
            return redirect(url_for('view_request', request_id=req.id))

        if action == 'mark_status':
            if req.user_id != current_user.id and not current_user.is_admin():
                abort(403)
            new_status = request.form.get('status')
            if new_status in ('open', 'fulfilled', 'closed'):
                req.status = new_status
                db.session.commit()
                flash('Request status updated.', 'success')
            return redirect(url_for('view_request', request_id=req.id))

    candidate_resources = Resource.query.filter_by(subject=req.subject).filter(
        Resource.review_status != 'removed').limit(10).all()

    return render_template('request_detail.html', req=req, candidate_resources=candidate_resources)


# ================= Notifications =================

@app.route('/notifications')
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.timestamp.desc()).limit(50).all()
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return render_template('notifications.html', notifs=notifs)


# ================= My Uploads / Recently Viewed =================

@app.route('/my-uploads')
@login_required
def my_uploads():
    resources = Resource.query.filter_by(uploader_id=current_user.id).order_by(Resource.upload_date.desc()).all()
    return render_template('my_uploads.html', resources=resources)


@app.route('/recently-viewed')
@login_required
def recently_viewed():
    views = (RecentView.query.filter_by(user_id=current_user.id)
             .order_by(RecentView.viewed_at.desc()).limit(30).all())
    return render_template('recently_viewed.html', views=views)


# ================= Settings =================

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'update_profile':
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip().lower()
            year = request.form.get('year', '')
            branch = request.form.get('branch', '')
            if not all([name, email, year, branch]):
                flash('Please fill in all profile fields.', 'danger')
            elif User.query.filter(User.email == email, User.id != current_user.id).first():
                flash('That email is already in use by another account.', 'danger')
            else:
                current_user.name = name
                current_user.email = email
                current_user.year = year
                current_user.branch = branch
                if year not in MENTOR_ELIGIBLE_YEARS:
                    mentor = Mentor.query.filter_by(user_id=current_user.id).first()
                    if mentor and mentor.is_active:
                        mentor.is_active = False
                        flash('Note: Your mentor profile has been deactivated because you are not in 3rd or 4th Year.', 'info')
                db.session.commit()
                flash('Profile updated.', 'success')
            return redirect(url_for('settings'))

        if action == 'change_password':
            current_password = request.form.get('current_password', '').strip()
            new_password = request.form.get('new_password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()
            if not check_password_hash(current_user.password, current_password):
                flash('Current password is incorrect.', 'danger')
            elif new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
            elif len(new_password) < 6:
                flash('New password must be at least 6 characters.', 'danger')
            else:
                current_user.password = generate_password_hash(new_password)
                db.session.commit()
                flash('Password changed.', 'success')
            return redirect(url_for('settings'))

        if action == 'update_appearance':
            theme = request.form.get('theme', 'light')
            if theme in ('light', 'dark'):
                current_user.theme = theme
                db.session.commit()
                flash('Appearance updated.', 'success')
            return redirect(url_for('settings'))

        if action == 'update_notifications':
            current_user.notify_comments = request.form.get('notify_comments') == 'on'
            current_user.notify_requests = request.form.get('notify_requests') == 'on'
            current_user.notify_ratings = request.form.get('notify_ratings') == 'on'
            current_user.notify_moderation = request.form.get('notify_moderation') == 'on'
            db.session.commit()
            flash('Notification preferences saved.', 'success')
            return redirect(url_for('settings'))

        if action == 'update_privacy':
            current_user.show_profile_on_uploads = request.form.get('show_profile_on_uploads') == 'on'
            db.session.commit()
            flash('Privacy settings saved.', 'success')
            return redirect(url_for('settings'))

        if action == 'delete_account':
            confirm_text = request.form.get('confirm_text', '')
            if confirm_text != 'DELETE':
                flash('Type DELETE to confirm account deletion.', 'danger')
                return redirect(url_for('settings'))

            uid = current_user.id
            logout_user()
            delete_user_account(uid)
            flash('Your account has been deleted.', 'info')
            return redirect(url_for('login'))

    return render_template('settings.html', years=YEARS, branches=BRANCHES)


# ================= Admin / Moderation =================

@app.route('/admin')
@admin_required
def admin_dashboard():
    open_reports = Report.query.filter_by(status='open').order_by(Report.timestamp.desc()).all()
    needs_review = Resource.query.filter_by(review_status='needs_review').all()
    open_requests = ResourceRequest.query.filter_by(status='open').order_by(ResourceRequest.timestamp.desc()).all()
    return render_template('admin.html', open_reports=open_reports, needs_review=needs_review,
                            open_requests=open_requests, threshold=LOW_QUALITY_THRESHOLD,
                            min_ratings=LOW_QUALITY_MIN_RATINGS)


@app.route('/admin/report/<int:report_id>/<action>', methods=['POST'])
@admin_required
def admin_handle_report(report_id, action):
    report = Report.query.get_or_404(report_id)
    if action == 'resolve':
        report.status = 'resolved'
    elif action == 'dismiss':
        report.status = 'dismissed'
    elif action == 'remove_resource':
        report.status = 'resolved'
        report.resource.review_status = 'removed'
    db.session.commit()
    flash('Report updated.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/resource/<int:resource_id>/<action>', methods=['POST'])
@admin_required
def admin_handle_resource(resource_id, action):
    resource = Resource.query.get_or_404(resource_id)
    if action == 'approve':
        resource.review_status = 'ok'
    elif action == 'remove':
        resource.review_status = 'removed'
    db.session.commit()
    flash('Resource status updated.', 'success')
    return redirect(url_for('admin_dashboard'))


# ================= Doubt Box =================

@app.route('/doubts')
@login_required
def list_doubts():
    subject = request.args.get('subject', '').strip()
    q = request.args.get('q', '').strip()
    view = request.args.get('view', 'recent')  # recent / unanswered

    query = Doubt.query.options(db.selectinload(Doubt.answers), db.joinedload(Doubt.asker))
    if subject:
        query = query.filter(Doubt.subject.ilike(f'%{subject}%'))
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Doubt.title.ilike(like), Doubt.description.ilike(like)))

    doubts = query.order_by(Doubt.created_at.desc()).all()

    if view == 'unanswered':
        doubts = [d for d in doubts if d.answer_count() == 0]
    elif view == 'answered':
        doubts = [d for d in doubts if d.answer_count() > 0]

    subjects = sorted({d.subject for d in Doubt.query.all()})

    return render_template('doubts.html', doubts=doubts, subjects=subjects,
                            selected_subject=subject, selected_q=q, selected_view=view)


@app.route('/doubts/new', methods=['GET', 'POST'])
@login_required
def new_doubt():
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        tag = request.form.get('tag', '').strip()

        if not subject or not title:
            flash('Subject and question title are required.', 'danger')
            return redirect(url_for('new_doubt'))

        doubt = Doubt(user_id=current_user.id, subject=subject, title=title,
                       description=description, tag=tag or None)
        db.session.add(doubt)
        db.session.commit()
        flash('Your doubt has been posted.', 'success')
        return redirect(url_for('view_doubt', doubt_id=doubt.id))

    return render_template('new_doubt.html')


@app.route('/doubts/<int:doubt_id>', methods=['GET', 'POST'])
@login_required
def view_doubt(doubt_id):
    doubt = Doubt.query.get_or_404(doubt_id)

    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        if not content:
            flash('Answer cannot be empty.', 'danger')
            return redirect(url_for('view_doubt', doubt_id=doubt.id))

        answer = DoubtAnswer(doubt_id=doubt.id, user_id=current_user.id, content=content)
        db.session.add(answer)
        if doubt.user_id != current_user.id and doubt.asker.notify_comments:
            notify(doubt.user_id, f'{current_user.name} answered your doubt "{doubt.title}".',
                   link=url_for('view_doubt', doubt_id=doubt.id))
        db.session.commit()
        flash('Answer posted.', 'success')
        return redirect(url_for('view_doubt', doubt_id=doubt.id))

    answers = DoubtAnswer.query.filter_by(doubt_id=doubt.id).order_by(
        DoubtAnswer.is_accepted.desc(), DoubtAnswer.created_at.asc()).all()
    return render_template('doubt_detail.html', doubt=doubt, answers=answers)


@app.route('/doubts/answer/<int:answer_id>/edit', methods=['POST'])
@login_required
def edit_doubt_answer(answer_id):
    answer = DoubtAnswer.query.get_or_404(answer_id)
    if answer.user_id != current_user.id:
        abort(403)
    content = request.form.get('content', '').strip()
    if content:
        answer.content = content
        db.session.commit()
        flash('Answer updated.', 'success')
    return redirect(url_for('view_doubt', doubt_id=answer.doubt_id))


@app.route('/doubts/answer/<int:answer_id>/delete', methods=['POST'])
@login_required
def delete_doubt_answer(answer_id):
    answer = DoubtAnswer.query.get_or_404(answer_id)
    doubt_id = answer.doubt_id
    if answer.user_id != current_user.id and not current_user.is_admin():
        abort(403)
    was_accepted = answer.is_accepted
    db.session.delete(answer)
    if was_accepted:
        doubt = Doubt.query.get(doubt_id)
        if doubt:
            remaining_accepted = DoubtAnswer.query.filter(
                DoubtAnswer.doubt_id == doubt_id,
                DoubtAnswer.id != answer_id,
                DoubtAnswer.is_accepted == True
            ).first()
            if not remaining_accepted:
                doubt.status = 'open'
    db.session.commit()
    flash('Answer deleted.', 'success')
    return redirect(url_for('view_doubt', doubt_id=doubt_id))


@app.route('/doubts/answer/<int:answer_id>/accept', methods=['POST'])
@login_required
def accept_doubt_answer(answer_id):
    answer = DoubtAnswer.query.get_or_404(answer_id)
    doubt = Doubt.query.get_or_404(answer.doubt_id)
    if doubt.user_id != current_user.id:
        abort(403)

    for a in doubt.answers:
        a.is_accepted = (a.id == answer.id)
    doubt.status = 'resolved'
    db.session.commit()

    if answer.user_id != current_user.id:
        notify(answer.user_id, f'Your answer was accepted on "{doubt.title}".',
               link=url_for('view_doubt', doubt_id=doubt.id))
        db.session.commit()

    flash('Marked as accepted answer.', 'success')
    return redirect(url_for('view_doubt', doubt_id=doubt.id))


# ================= Senior Connect =================

@app.route('/mentors')
@login_required
def list_mentors():
    subject = request.args.get('subject', '').strip()
    branch = request.args.get('branch', '')
    year = request.args.get('year', '')

    query = (Mentor.query.filter_by(is_active=True)
             .join(User)
             .filter(User.year.in_(MENTOR_ELIGIBLE_YEARS))
             .options(db.joinedload(Mentor.user)))
    if branch:
        query = query.filter(User.branch == branch)
    if year:
        query = query.filter(User.year == year)

    mentors = query.all()
    if subject:
        mentors = [m for m in mentors if any(subject.lower() in s.lower() for s in m.subject_list())]

    my_mentor_profile = Mentor.query.filter_by(user_id=current_user.id).first()
    is_eligible = current_user.year in MENTOR_ELIGIBLE_YEARS

    return render_template('mentors.html', mentors=mentors, years=YEARS, branches=BRANCHES,
                            selected_subject=subject, selected_branch=branch, selected_year=year,
                            my_mentor_profile=my_mentor_profile, is_eligible=is_eligible)


@app.route('/mentors/profile', methods=['GET', 'POST'])
@login_required
def mentor_profile():
    if current_user.year not in MENTOR_ELIGIBLE_YEARS:
        flash('Only 3rd and 4th year students can become mentors.', 'danger')
        return redirect(url_for('list_mentors'))

    profile = Mentor.query.filter_by(user_id=current_user.id).first()

    if request.method == 'POST':
        bio = request.form.get('bio', '').strip()
        subjects = request.form.get('subjects', '').strip()
        is_active = request.form.get('is_active') == 'on'

        if not subjects:
            flash('Please list at least one subject you can help with.', 'danger')
            return redirect(url_for('mentor_profile'))

        if profile:
            profile.bio = bio
            profile.subjects = subjects
            profile.is_active = is_active
        else:
            profile = Mentor(user_id=current_user.id, bio=bio, subjects=subjects, is_active=is_active)
            db.session.add(profile)

        db.session.commit()
        flash('Mentor profile saved.', 'success')
        return redirect(url_for('list_mentors'))

    return render_template('mentor_profile.html', profile=profile)


# ================= Errors =================

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403


with app.app_context():
    db.create_all()


if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() in ('1', 'true', 'yes')
    app.run(debug=debug_mode)
