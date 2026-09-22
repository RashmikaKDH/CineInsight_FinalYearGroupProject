import os
import tempfile
from functools import wraps

# Load environment variables from .env before accessing os.getenv / os.environ
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import mysql.connector
from flask import Flask, redirect, render_template, request, session, url_for, jsonify, Response, stream_with_context, flash
from werkzeug.security import check_password_hash, generate_password_hash
import yt_dlp
import json
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from main import process_youtube_review_generator

# ---------------------------------------------------------------------------
# Search pipeline service imports
# ---------------------------------------------------------------------------
import logging

auth_logger = logging.getLogger("cineinsight.auth")
if not auth_logger.handlers:
    auth_handler = logging.StreamHandler()
    auth_formatter = logging.Formatter("[%(asctime)s] %(levelname)s in %(name)s: %(message)s")
    auth_handler.setFormatter(auth_formatter)
    auth_logger.addHandler(auth_handler)
    auth_logger.setLevel(logging.INFO)

from services.youtube_search import search_movie_reviews
from services.subtitle_service import download_subtitles, cleanup_subtitle_files
from services.subtitle_parser import parse_vtt_to_text
from services.language_detector import get_detector
from services.trace_logger import logger as trace_logger
from services.db_service import (
    get_or_create_video,
    create_analysis,
    create_reasoning_report,
    init_password_reset_table,
    invalidate_user_reset_tokens,
    create_password_reset_token,
)
from services.email_service import send_reset_email, send_password_reset_email
from services.rate_limiter import rate_limiter


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cineinsight-dev-secret-key')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# YouTube Data API v3 key (set in environment or .env file)
YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY', '')



# ---------------------------------------------------------------------------
# Access Control Decorators
# ---------------------------------------------------------------------------

def login_required(f):
    """Redirect to sign-in if the user is not authenticated."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('signin'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Allow access only to Admin-role users."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('signin'))
        if session.get('user_role') != 'Admin':
            return redirect(url_for('profile'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def index():
    return render_template('index.html')


def get_db_connection():
    return mysql.connector.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASSWORD', ''),
        database=os.environ.get('DB_NAME', 'cineinsight_db'),
        port=int(os.environ.get('DB_PORT', 3306)),
    )


# Automatically ensure password_reset_tokens table exists on startup
try:
    init_password_reset_table()
except Exception:
    pass


def get_client_ip():
    """Extract real client IP address, respecting reverse proxies if configured."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers['X-Forwarded-For'].split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'


RESET_NEUTRAL_MESSAGE = 'If an account exists for this email, a password reset link has been sent.'


@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password:
            return render_template('signin.html', error='Please enter both email and password.')

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                'SELECT User_Id, Name, Email, Password, Role FROM `USER` WHERE Email = %s LIMIT 1',
                (email,)
            )
            user = cursor.fetchone()

            if user and check_password_hash(user['Password'], password):
                session.clear()
                session['user_id'] = user['User_Id']
                session['user_name'] = user['Name']
                session['user_email'] = user['Email']
                session['user_role'] = user['Role']
                return redirect(url_for('dashboard'))

            return render_template('signin.html', error='Invalid email or password.')
        except mysql.connector.Error:
            return render_template('signin.html', error='Database error. Please try again.')
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

    return render_template('signin.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not name or not email or not password:
            return render_template('signup.html', error='Please fill in all required fields.')

        if len(password) < 8:
            return render_template('signup.html', error='Password must be at least 8 characters long.')

        if password != confirm_password:
            return render_template('signup.html', error='Passwords do not match.')

        hashed_password = generate_password_hash(password)

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor()
            cursor.execute('SELECT 1 FROM `USER` WHERE Email = %s LIMIT 1', (email,))
            existing_user = cursor.fetchone()

            if existing_user:
                return render_template('signup.html', error='An account with this email already exists.')

            cursor.execute(
                'INSERT INTO `USER` (Name, Email, Password) VALUES (%s, %s, %s)',
                (name, email, hashed_password)
            )
            connection.commit()
            flash('Account created successfully! Please sign in.', 'success')
            return redirect(url_for('signin'))
        except mysql.connector.Error:
            if connection is not None:
                connection.rollback()
            return render_template('signup.html', error='Database error. Please try again.')
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

    return render_template('signup.html')


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


@app.route('/analysis')
def analysis():
    return render_template('analysis.html')


# ---------------------------------------------------------------------------
# Forgot Password & Password Reset Flow
# ---------------------------------------------------------------------------

@app.route('/forgot', methods=['GET', 'POST'])
def forgot():
    """
    Renders forgot-password page (GET) or processes form submission (POST).
    Always returns a neutral response to prevent account enumeration.
    """
    if request.method == 'POST':
        client_ip = get_client_ip()
        email = request.form.get('email', '').strip().lower()

        # Rate limit checks
        ip_allowed, _ = rate_limiter.check_and_record(client_ip, 'forgot_ip', max_requests=5, window_seconds=900)
        if not ip_allowed:
            return render_template('forgot.html', error='Too many password reset requests. Please try again later.')

        email_allowed, _ = rate_limiter.check_and_record(email, 'forgot_email', max_requests=3, window_seconds=900)
        if not email_allowed:
            return render_template('forgot.html', error='Too many reset requests for this email. Please try again later.')

        email_pattern = re.compile(r'^[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}$')
        if not email or not email_pattern.match(email):
            return render_template('forgot.html', error='Please enter a valid email address.')

        connection = None
        cursor = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute('SELECT User_Id, Name, Email FROM `user` WHERE Email = %s LIMIT 1', (email,))
            user = cursor.fetchone()

            if user:
                # 1. Invalidate any existing unused tokens for this account
                invalidate_user_reset_tokens(cursor, user['User_Id'])

                # 2. Generate cryptographically secure token & SHA-256 hash
                raw_token = secrets.token_urlsafe(32)
                token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
                expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')

                # 3. Store hash in password_reset_tokens
                create_password_reset_token(cursor, user['User_Id'], token_hash, expires_at)
                connection.commit()

                # 4. Dispatch email with reset URL
                reset_base_url = os.environ.get('RESET_PASSWORD_URL', 'http://127.0.0.1:5000/reset-password').rstrip('/')
                reset_url = f"{reset_base_url}?token={raw_token}"
                send_reset_email(user['Email'], reset_url)

        except Exception as e:
            if connection is not None:
                connection.rollback()
            auth_logger.error("Error processing password reset request: %s", str(e))
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

        # Always return the neutral success message
        return render_template('forgot.html', success=True, message=RESET_NEUTRAL_MESSAGE)

    return render_template('forgot.html')


@app.route('/api/auth/forgot-password', methods=['POST'])
def api_forgot_password():
    """
    REST API endpoint for forgot-password.
    Accepts: {"email": "user@example.com"}
    Always returns: {"message": "If an account exists for this email, a password reset link has been sent."}
    """
    client_ip = get_client_ip()
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    email = data.get('email', '').strip().lower()

    # 1. Rate limiting
    ip_allowed, retry_after = rate_limiter.check_and_record(client_ip, 'forgot_ip', max_requests=5, window_seconds=900)
    if not ip_allowed:
        return jsonify({'error': 'Too many password reset requests. Please try again later.', 'retry_after': retry_after}), 429

    email_allowed, retry_after = rate_limiter.check_and_record(email, 'forgot_email', max_requests=3, window_seconds=900)
    if not email_allowed:
        return jsonify({'error': 'Too many password reset requests for this email. Please try again later.', 'retry_after': retry_after}), 429

    # 2. Email format validation
    email_pattern = re.compile(r'^[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}$')
    if not email or not email_pattern.match(email):
        return jsonify({'error': 'Please provide a valid email address.'}), 400

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute('SELECT User_Id, Name, Email FROM `user` WHERE Email = %s LIMIT 1', (email,))
        user = cursor.fetchone()

        if user:
            invalidate_user_reset_tokens(cursor, user['User_Id'])
            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')

            create_password_reset_token(cursor, user['User_Id'], token_hash, expires_at)
            connection.commit()

            reset_base_url = os.environ.get('RESET_PASSWORD_URL', 'http://127.0.0.1:5000/reset-password').rstrip('/')
            reset_url = f"{reset_base_url}?token={raw_token}"
            send_reset_email(user['Email'], reset_url)

    except Exception as e:
        if connection is not None:
            connection.rollback()
        auth_logger.error("Error during api_forgot_password: %s", str(e))
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    return jsonify({'message': RESET_NEUTRAL_MESSAGE}), 200


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    """
    Renders password reset page (GET) or updates password (POST).
    Includes Referrer-Policy: no-referrer header.
    """
    if request.method == 'POST':
        client_ip = get_client_ip()
        ip_allowed, _ = rate_limiter.check_and_record(client_ip, 'reset_ip', max_requests=5, window_seconds=900)
        if not ip_allowed:
            resp = render_template('reset-password.html', error='Too many password reset attempts. Please try again later.')
            return Response(resp, status=429, headers={'Referrer-Policy': 'no-referrer'})

        token = request.form.get('token', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not token:
            resp = render_template('reset-password.html', error='Missing reset token. Please request a new link.')
            return Response(resp, status=400, headers={'Referrer-Policy': 'no-referrer'})

        if not password or len(password) < 8:
            resp = render_template('reset-password.html', error='Password must be at least 8 characters long.', token=token)
            return Response(resp, status=400, headers={'Referrer-Policy': 'no-referrer'})

        if password != confirm_password:
            resp = render_template('reset-password.html', error='Passwords do not match.', token=token)
            return Response(resp, status=400, headers={'Referrer-Policy': 'no-referrer'})

        success, err_msg = _execute_password_reset(token, password)
        if not success:
            resp = render_template('reset-password.html', error=err_msg, token=token)
            return Response(resp, status=400, headers={'Referrer-Policy': 'no-referrer'})

        resp = render_template('reset-password.html', success=True)
        return Response(resp, status=200, headers={'Referrer-Policy': 'no-referrer'})

    # GET request
    token = request.args.get('token', '').strip()
    if not token:
        resp = render_template('reset-password.html', error='No reset token provided. Please use the link sent to your email.')
    else:
        resp = render_template('reset-password.html', token=token)

    return Response(
        resp,
        headers={
            'Referrer-Policy': 'no-referrer',
            'Cache-Control': 'no-store, no-cache, must-revalidate',
        }
    )


@app.route('/api/auth/reset-password', methods=['POST'])
def api_reset_password():
    """
    REST API endpoint for resetting password with a token.
    Accepts:
    {
      "token": "reset-token-from-email",
      "new_password": "NewSecurePassword123"
    }
    """
    client_ip = get_client_ip()
    ip_allowed, retry_after = rate_limiter.check_and_record(client_ip, 'reset_ip', max_requests=5, window_seconds=900)
    if not ip_allowed:
        return jsonify({'error': 'Too many password reset attempts. Please try again later.', 'retry_after': retry_after}), 429

    data = request.get_json(silent=True) or request.form.to_dict() or {}
    token = data.get('token', '').strip()
    new_password = data.get('new_password') or data.get('password') or ''
    confirm_password = data.get('confirm_password')

    if not token:
        return jsonify({'error': 'Reset token is required.'}), 400

    if not new_password or len(new_password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters long.'}), 400

    if confirm_password is not None and new_password != confirm_password:
        return jsonify({'error': 'Passwords do not match.'}), 400

    success, err_msg = _execute_password_reset(token, new_password)
    if not success:
        return jsonify({'error': err_msg}), 400

    return jsonify({'message': 'Password has been reset successfully. Please sign in with your new password.'}), 200


def _execute_password_reset(raw_token: str, new_password: str) -> tuple[bool, str]:
    """
    Internal helper to validate token and update password inside an atomic transaction.
    Uses SELECT ... FOR UPDATE on password_reset_tokens to prevent concurrent reuse.
    """
    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # 1. Lock the token record for atomic update
        cursor.execute(
            """
            SELECT id, user_id, expires_at, used_at
            FROM password_reset_tokens
            WHERE token_hash = %s
            FOR UPDATE
            """,
            (token_hash,)
        )
        token_record = cursor.fetchone()

        if not token_record:
            connection.rollback()
            return False, 'Invalid or expired password reset link.'

        if token_record['used_at'] is not None:
            connection.rollback()
            return False, 'This password reset link has already been used.'

        expires_at = token_record['expires_at']
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)

        if expires_at < now:
            connection.rollback()
            return False, 'This password reset link has expired. Please request a new one.'

        # 2. Hash new password with existing secure hashing method (scrypt)
        hashed_password = generate_password_hash(new_password)

        # 3. Update user password
        cursor.execute(
            'UPDATE `user` SET Password = %s WHERE User_Id = %s',
            (hashed_password, token_record['user_id'])
        )

        # 4. Mark token as used
        cursor.execute(
            'UPDATE password_reset_tokens SET used_at = UTC_TIMESTAMP() WHERE id = %s',
            (token_record['id'],)
        )

        connection.commit()

        # Invalidate active session for the resetting user
        session.clear()

        return True, ''

    except Exception as e:
        if connection is not None:
            connection.rollback()
        auth_logger.error("Error executing password reset: %s", str(e))
        return False, 'Database error while resetting password. Please try again.'
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()



@app.route('/google-login')
def google_login():
    return render_template('google-login.html')


@app.route('/api/search')
def api_search():
    """
    New search pipeline:
      1. YouTube Data API v3  → top 20 movie review videos
      2. yt-dlp               → subtitle download only (no video)
      3. subtitle_parser      → .vtt → plain text
      4. fastText             → English detection
      5. Return first 8 English videos
    """
    query = request.args.get('q', '')
    duration = request.args.get('duration', 'medium')  # 'any','short','medium','long'
    # Validate to prevent arbitrary API params
    if duration not in ('any', 'short', 'medium', 'long'):
        duration = 'medium'
    if not query:
        return jsonify({'error': 'No query provided'}), 400

    # --- Check API key ---
    if not YOUTUBE_API_KEY:
        return jsonify({
            'error': 'YOUTUBE_API_KEY is not configured. '
                     'Set it as an environment variable.'
        }), 500

    # --- Load fastText detector (lazy, singleton) ---
    try:
        detector = get_detector()
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 500

    # --- Step 1: YouTube Data API v3 search → top 50 videos ---
    try:
        candidates = search_movie_reviews(query, max_results=50, video_duration=duration)
    except (ValueError, RuntimeError) as e:
        return jsonify({'error': str(e)}), 500

    results          = []
    total_processed  = 0
    TARGET           = 8

    # Use a single temp directory for all subtitle downloads this request
    with tempfile.TemporaryDirectory() as tmp_dir:
        for video in candidates:
            if len(results) >= TARGET:
                break

            video_id = video['video_id']
            total_processed += 1
            
            # Fetch the log dictionary created by youtube_search.py
            vlog = logger.get_video_log(video_id)
            if not vlog:
                continue

            # --- Step 2: Download subtitles (no video download) ---
            try:
                vtt_path, subtitle_type = download_subtitles(video_id, tmp_dir)
                vlog["subtitle_status"] = subtitle_type
            except Exception:
                vlog["subtitle_status"] = "error"
                continue   # Network/permission error — skip this video

            if vtt_path is None:
                # No subtitles available — skip
                vlog["subtitle_status"] = "none"
                cleanup_subtitle_files(tmp_dir, video_id)
                continue

            # --- Step 3: Parse .vtt → plain text ---
            try:
                transcript = parse_vtt_to_text(vtt_path)
                vlog["transcript_snippet"] = transcript[:500] if transcript else ""
            except Exception:
                cleanup_subtitle_files(tmp_dir, video_id)
                continue

            if not transcript or len(transcript.strip()) < 30:
                # Empty or near-empty transcript — skip
                cleanup_subtitle_files(tmp_dir, video_id)
                continue

            # --- Step 4: fastText language detection ---
            try:
                lang_info = detector.detect_with_score(transcript)
                vlog["layer4_detected_lang"] = lang_info.get('lang', 'unknown')
                vlog["layer4_score"] = lang_info.get('score', 0.0)
                vlog["layer4_lang_pass"] = (vlog["layer4_detected_lang"] == 'en')
            except Exception:
                vlog["layer4_lang_pass"] = False
                cleanup_subtitle_files(tmp_dir, video_id)
                continue

            if not vlog["layer4_lang_pass"]:
                cleanup_subtitle_files(tmp_dir, video_id)
                continue

            # --- Step 5: English video confirmed — add to results ---
            vlog["final_status"] = "accepted"
            results.append({
                'video_id':     video_id,
                'title':        video['title'],
                'channel':      video['channel'],
                'thumbnail':    video['thumbnail'],
                'duration':     video['duration'],
                'published':    video['published'],
                'url':          video['url'],
                'transcript':   transcript
            })
            
            cleanup_subtitle_files(tmp_dir, video_id)

    # Save the trace to disk for debug_app to read
    logger.save_trace()

    return jsonify({
        'query':           query,
        'total_processed': total_processed,
        'english_videos':  len(results),
        'results':         results,
    })


import re

def is_english_review(title):
    if not title:
        return False
    # Reject Non-Latin scripts (Hindi/Devanagari, Tamil, Telugu, Malayalam, Sinhala, CJK, Arabic, Cyrillic, etc.)
    non_latin_pattern = re.compile(r'[\u0900-\u0DFF\u0E00-\u0E7F\u0D80-\u0DFF\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\u0600-\u06FF\u0400-\u04FF]')
    if non_latin_pattern.search(title):
        return False

    # Reject explicit non-English language tags in video title
    non_english_tags = [
        'hindi', 'tamil', 'telugu', 'malayalam', 'kannada', 'sinhala',
        'marathi', 'bengali', 'punjabi', 'gujarati', 'urdu', 'korean',
        'japanese', 'spanish', 'french', 'german', 'italian', 'russian', 'chinese', 'bahasa'
    ]
    title_lower = title.lower()
    for tag in non_english_tags:
        if re.search(r'\b' + re.escape(tag) + r'\b', title_lower):
            return False

    return True


TRENDING_CACHE = {
    'timestamp': 0,
    'data': []
}

@app.route('/api/trending-reviews')
def api_trending_reviews():
    import time
    current_time = time.time()
    # Cache results for 30 minutes (1800 seconds) for fast page load
    if TRENDING_CACHE['data'] and (current_time - TRENDING_CACHE['timestamp']) < 1800:
        return jsonify({'results': TRENDING_CACHE['data']})

    query = "trending english movie review"
    requested_limit = int(request.args.get('limit', '8'))
    # Fetch extra items from YouTube search to filter down to English-only reviews
    fetch_limit = requested_limit * 3

    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'force_generic_extractor': False
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_query = f"ytsearch{fetch_limit}:{query}"
            info = ydl.extract_info(search_query, download=False)

            results = []
            if 'entries' in info:
                for entry in info['entries']:
                    title = entry.get('title', '')
                    
                    # Filter out non-English reviews
                    if not is_english_review(title):
                        continue

                    duration = entry.get('duration')
                    if duration:
                        m, s = divmod(int(duration), 60)
                        h, m = divmod(m, 60)
                        if h > 0:
                            duration_str = f"{h}:{m:02d}:{s:02d}"
                        else:
                            duration_str = f"{m}:{s:02d}"
                    else:
                        duration_str = "N/A"

                    views = entry.get('view_count')
                    view_str = "0 views"
                    if views:
                        if views >= 1000000:
                            view_str = f"{(views/1000000):.1f}M views"
                        elif views >= 1000:
                            view_str = f"{(views/1000):.1f}K views"
                        else:
                            view_str = f"{views} views"

                    thumbs = entry.get('thumbnails', [])
                    thumb_url = thumbs[-1]['url'] if thumbs else '../static/assets/dune_thumb.png'

                    results.append({
                        'id': entry.get('id'),
                        'title': title,
                        'url': entry.get('url'),
                        'duration_str': duration_str,
                        'view_str': view_str,
                        'thumbnail': thumb_url
                    })

                    # Stop once we have reached the requested limit of English reviews
                    if len(results) >= requested_limit:
                        break

            TRENDING_CACHE['timestamp'] = current_time
            TRENDING_CACHE['data'] = results
            return jsonify({'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analyze')
def api_analyze():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    # Capture user_id before entering the generator (session not accessible in threads)
    user_id = session.get('user_id')

    def generate():
        try:
            for json_str in process_youtube_review_generator(url):
                data = json.loads(json_str)

                # When the pipeline finishes successfully, save everything to the DB
                if data.get('status') == 'completed' and user_id is not None:
                    try:
                        # 1. Get or create the youtube_video record
                        video_id = get_or_create_video(
                            title=data.get('title', url),
                            url=data.get('url', url),
                        )

                        # 2. Create the analysis record (with mock scores for now)
                        analysis_id = create_analysis(
                            user_id=user_id,
                            video_id=video_id,
                            overall_sentiment_score=data.get('overall_sentiment_score', 0.0),
                            sarcasm_flag=data.get('sarcasm_flag', False),
                            aspect_wise_report=data.get('aspect_wise_report'),
                        )

                        # 3. Create the reasoning_report record
                        create_reasoning_report(
                            analysis_id=analysis_id,
                            generated_text=data.get(
                                'reasoning_report_text',
                                'Reasoning report under development.'
                            ),
                        )

                        # Attach db IDs to the response so the frontend can reference them
                        data['db_video_id'] = video_id
                        data['db_analysis_id'] = analysis_id

                    except Exception as db_err:
                        # Non-fatal: surface the DB error in the response without crashing
                        data['db_save_warning'] = f'DB save failed: {str(db_err)}'

                # SSE format: "data: {json}\n\n"
                yield f"data: {json.dumps(data)}\n\n"
        except Exception as e:
            error_json = json.dumps({"status": "error", "message": f"Pipeline Error: {str(e)}"})
            yield f"data: {error_json}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


# ---------------------------------------------------------------------------
# Debug — LLM Aspect Extraction Viewer
# ---------------------------------------------------------------------------

@app.route('/debug/aspect')
def debug_aspect():
    """Standalone debug UI to inspect the last LLM aspect extraction result."""
    return render_template('debug_aspect.html')


@app.route('/api/debug/aspect-data')
def api_debug_aspect_data():
    """Return the latest debug_aspect_trace.json written by the pipeline."""
    trace_path = os.path.join(os.path.dirname(__file__), 'debug_aspect_trace.json')
    if not os.path.exists(trace_path):
        return jsonify({'error': 'No trace file found. Run an analysis first.'}), 404
    try:
        with open(trace_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': f'Could not read trace: {str(e)}'}), 500


# ---------------------------------------------------------------------------
# Profile & Admin Routes
# ---------------------------------------------------------------------------

@app.route('/profile')
@login_required
def profile():
    """Show the logged-in user's profile details."""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            'SELECT User_Id, Name, Email, Role FROM `USER` WHERE User_Id = %s',
            (session['user_id'],)
        )
        user = cursor.fetchone()
        return render_template('profile.html', user=user)
    except mysql.connector.Error:
        return redirect(url_for('dashboard'))
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@app.route('/admin')
@admin_required
def admin_panel():
    """Admin-only: list all registered users."""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute('SELECT User_Id, Name, Email, Role FROM `USER` ORDER BY User_Id ASC')
        users = cursor.fetchall()
        return render_template('admin.html', users=users)
    except mysql.connector.Error:
        return render_template('admin.html', users=[], error='Database error.')
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@app.route('/admin/delete/<int:user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    """Admin-only: permanently delete a user account."""
    # Prevent admin from deleting their own account
    if user_id == session.get('user_id'):
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('admin_panel'))

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Fetch user before deletion to get their name for the message
        cursor.execute('SELECT Name FROM `USER` WHERE User_Id = %s', (user_id,))
        target = cursor.fetchone()

        if not target:
            flash('User not found.', 'error')
            return redirect(url_for('admin_panel'))

        cursor.execute('DELETE FROM `USER` WHERE User_Id = %s', (user_id,))
        connection.commit()
        flash(f"User '{target['Name']}' was deleted successfully.", 'success')
    except mysql.connector.Error:
        if connection: connection.rollback()
        flash('Database error. Could not delete user.', 'error')
    finally:
        if cursor: cursor.close()
        if connection: connection.close()

    return redirect(url_for('admin_panel'))


@app.route('/logout', methods=['POST'])
def logout():
    """Clear session and redirect to sign-in."""
    session.clear()
    return redirect(url_for('signin'))


if __name__ == '__main__':
    app.run(debug=True)
    