"""
db_service.py
-------------
Database helper functions for CineInsight.

Handles all INSERT / SELECT operations for:
  - youtube_video
  - analysis
  - reasoning_report

Usage (in app.py):
    from services.db_service import get_or_create_video, create_analysis, create_reasoning_report
"""

import os
import mysql.connector


# ---------------------------------------------------------------------------
# Internal: re-use the same connection factory as app.py
# ---------------------------------------------------------------------------
def _get_connection():
    return mysql.connector.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASSWORD', ''),
        database=os.environ.get('DB_NAME', 'cineinsight_db'),
        port=int(os.environ.get('DB_PORT', 3306)),
    )


# ---------------------------------------------------------------------------
# youtube_video table
# ---------------------------------------------------------------------------
def get_or_create_video(title: str, url: str) -> int:
    """
    Return the Video_Id for the given YouTube URL.
    If the video doesn't exist yet, insert it first.

    Args:
        title: Video title string.
        url:   Full YouTube URL (used as the unique identifier).

    Returns:
        Video_Id (int)
    """
    connection = _get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        # Check if this video already exists
        cursor.execute(
            'SELECT Video_Id FROM youtube_video WHERE YouTube_url = %s LIMIT 1',
            (url,)
        )
        row = cursor.fetchone()
        if row:
            return row['Video_Id']

        # Insert new video record
        cursor.execute(
            'INSERT INTO youtube_video (Title, YouTube_url) VALUES (%s, %s)',
            (title, url)
        )
        connection.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        connection.close()


# ---------------------------------------------------------------------------
# analysis table
# ---------------------------------------------------------------------------
def create_analysis(
    user_id: int,
    video_id: int,
    overall_sentiment_score: float = 0.0,
    sarcasm_flag: bool = False,
    aspect_wise_report: str = None,
) -> int:
    """
    Insert a new analysis record and return its Analysis_Id.

    Args:
        user_id:                  FK -> user.User_Id
        video_id:                 FK -> youtube_video.Video_Id
        overall_sentiment_score:  Float sentiment score (mock: 0.0 until pipeline ready)
        sarcasm_flag:             Boolean sarcasm indicator (mock: False until pipeline ready)
        aspect_wise_report:       JSON string of aspect-wise breakdown (can be None)

    Returns:
        Analysis_Id (int)
    """
    connection = _get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            '''INSERT INTO analysis
               (User_Id, Video_Id, Overall_Sentiment_Score, Sarcasm_Flag, Aspect_Vise_Report)
               VALUES (%s, %s, %s, %s, %s)''',
            (user_id, video_id, overall_sentiment_score, int(sarcasm_flag), aspect_wise_report)
        )
        connection.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        connection.close()


# ---------------------------------------------------------------------------
# reasoning_report table
# ---------------------------------------------------------------------------
def create_reasoning_report(analysis_id: int, generated_text: str) -> int:
    """
    Insert a reasoning report linked to an analysis record.

    Args:
        analysis_id:    FK -> analysis.Analysis_Id
        generated_text: The LLM-generated reasoning text.

    Returns:
        Report_Id (int)
    """
    connection = _get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            'INSERT INTO reasoning_report (Analysis_Id, Generated_Text) VALUES (%s, %s)',
            (analysis_id, generated_text)
        )
        connection.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        connection.close()


# ---------------------------------------------------------------------------
# analysis history (read) -- for profile / history pages
# ---------------------------------------------------------------------------
def get_analyses_for_user(user_id: int) -> list:
    """
    Fetch all analyses performed by a given user, ordered by most recent first.

    Returns a list of dicts with keys:
        Analysis_Id, Analysis_Date, Overall_Sentiment_Score, Sarcasm_Flag,
        Aspect_Vise_Report, Title, YouTube_url
    """
    connection = _get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            '''SELECT
                a.Analysis_Id,
                a.Analysis_Date,
                a.Overall_Sentiment_Score,
                a.Sarcasm_Flag,
                a.Aspect_Vise_Report,
                v.Title,
                v.YouTube_url
               FROM analysis a
               JOIN youtube_video v ON a.Video_Id = v.Video_Id
               WHERE a.User_Id = %s
               ORDER BY a.Analysis_Date DESC''',
            (user_id,)
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        connection.close()


# ---------------------------------------------------------------------------
# password_reset_tokens table operations
# ---------------------------------------------------------------------------
def init_password_reset_table(connection=None) -> None:
    """
    Ensure the password_reset_tokens table exists in the database.
    Safe to call repeatedly on startup.
    """
    should_close = False
    if connection is None:
        try:
            connection = _get_connection()
            should_close = True
        except Exception:
            return  # If DB is not reachable at import time, skip

    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS `password_reset_tokens` (
              `id` INT(11) NOT NULL AUTO_INCREMENT,
              `user_id` INT(11) NOT NULL,
              `token_hash` VARCHAR(64) NOT NULL,
              `expires_at` DATETIME NOT NULL,
              `used_at` DATETIME DEFAULT NULL,
              `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (`id`),
              INDEX `idx_token_hash` (`token_hash`),
              INDEX `idx_user_id` (`user_id`),
              CONSTRAINT `fk_prt_user_id` FOREIGN KEY (`user_id`) REFERENCES `user` (`User_Id`) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
            """
        )
        connection.commit()
    except Exception:
        connection.rollback()
    finally:
        cursor.close()
        if should_close:
            connection.close()


def invalidate_user_reset_tokens(cursor, user_id: int) -> None:
    """
    Mark any older, unused password reset tokens for this user as used/invalidated.
    Ensures that when a newer token is issued, older tokens become invalid.
    """
    cursor.execute(
        "UPDATE password_reset_tokens SET used_at = UTC_TIMESTAMP() WHERE user_id = %s AND used_at IS NULL",
        (user_id,)
    )


def create_password_reset_token(cursor, user_id: int, token_hash: str, expires_at_dt) -> int:
    """
    Store the SHA-256 hash of a password reset token for the given user.
    """
    cursor.execute(
        """
        INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
        VALUES (%s, %s, %s)
        """,
        (user_id, token_hash, expires_at_dt)
    )
    return cursor.lastrowid

