import os

import mysql.connector
from flask import Flask, redirect, render_template, request, session, url_for, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cineinsight-dev-secret-key')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')


@app.route('/')
def index():
    return render_template('index.html')


def get_db_connection():
    return mysql.connector.connect(
        host='localhost',
        user='root',
        password='',
        database='cineinsight_db',
    )


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
def dashboard():
    return render_template('dashboard.html')


@app.route('/analysis')
def analysis():
    return render_template('analysis.html')


@app.route('/forgot')
def forgot():
    return render_template('forgot.html')


@app.route('/google-login')
def google_login():
    return render_template('google-login.html')


if __name__ == '__main__':
    app.run(debug=True)
    