"""
CineInsight — Admin Account Setup Script
=========================================
Run this script ONCE to create the default admin account in your local database.

Usage:
    python setup_admin.py

Requirements:
    - MySQL / MariaDB running locally (XAMPP, WAMP, etc.)
    - cineinsight_db database already imported from cineinsight_db.sql
    - Project venv activated  (venv\\Scripts\\activate)
"""

import sys

try:
    import mysql.connector
    from werkzeug.security import generate_password_hash
except ImportError:
    print("[ERROR] Missing dependencies. Activate the venv first:")
    print("        venv\\Scripts\\activate   (Windows)")
    print("        source venv/bin/activate (Mac/Linux)")
    sys.exit(1)

# ── Database connection settings ──────────────────────────────────────────
DB_CONFIG = {
    'host':     'localhost',
    'user':     'root',
    'password': '',           # Change if your MySQL root has a password
    'database': 'cineinsight_db',
}

# ── Admin account details ─────────────────────────────────────────────────
ADMIN_NAME     = 'CineInsight Admin'
ADMIN_EMAIL    = 'admin@cineinsight.com'
ADMIN_PASSWORD = 'Admin@123'

# ─────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("  CineInsight — Admin Setup")
    print("=" * 50)

    try:
        conn   = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
    except mysql.connector.Error as e:
        print(f"\n[ERROR] Cannot connect to database: {e}")
        print("\nMake sure:")
        print("  1. XAMPP / MySQL is running")
        print("  2. cineinsight_db is imported from cineinsight_db.sql")
        print("  3. DB_CONFIG at the top of this file matches your setup")
        sys.exit(1)

    # Check if admin already exists
    cursor.execute(
        "SELECT User_Id, Name, Email FROM `USER` WHERE Email = %s LIMIT 1",
        (ADMIN_EMAIL,)
    )
    existing = cursor.fetchone()

    if existing:
        print(f"\n[INFO] Admin account already exists:")
        print(f"       Name  : {existing['Name']}")
        print(f"       Email : {existing['Email']}")
        print(f"       ID    : #{existing['User_Id']}")
        print("\nNo changes made.")
    else:
        hashed = generate_password_hash(ADMIN_PASSWORD)
        cursor.execute(
            "INSERT INTO `USER` (Name, Email, Password, Role) VALUES (%s, %s, %s, %s)",
            (ADMIN_NAME, ADMIN_EMAIL, hashed, 'Admin')
        )
        conn.commit()

        print("\n[SUCCESS] Admin account created!")
        print(f"  Name    : {ADMIN_NAME}")
        print(f"  Email   : {ADMIN_EMAIL}")
        print(f"  Password: {ADMIN_PASSWORD}")
        print(f"  Role    : Admin")
        print("\nYou can now sign in at http://127.0.0.1:5000/signin")

    cursor.close()
    conn.close()
    print("=" * 50)


if __name__ == '__main__':
    main()
