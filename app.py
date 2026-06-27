from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, abort
from flask_wtf.csrf import CSRFProtect
import pymysql
import bcrypt
import os
import mimetypes
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

app.secret_key = os.environ.get('SECRET_KEY', os.urandom(32))

csrf = CSRFProtect(app)

app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'zip', 'docx', 'xlsx'}
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_db_connection():
    return pymysql.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        user=os.environ.get('DB_USER', 'board_user'),
        password=os.environ.get('DB_PASSWORD', ''),
        db=os.environ.get('DB_NAME', 'board_db'),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )


def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


@app.route('/')
def index():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM boards")
        boards = cursor.fetchall()
    conn.close()
    return render_template('index.html', boards=boards)


@app.route('/search/user')
def search_user():
    keyword = request.args.get('keyword', '').strip()
    users = []
    if keyword:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, created_at FROM users WHERE username LIKE %s",
                (f"%{keyword}%",)
            )
            users = cursor.fetchall()
        conn.close()
    return render_template('search_user.html', users=users, keyword=keyword)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        raw_password = request.form.get('password', '')

        if not username or len(username) < 3 or len(username) > 20:
            return render_template('register.html', error='아이디는 3~20자 사이여야 합니다.')
        if not raw_password or len(raw_password) < 8:
            return render_template('register.html', error='비밀번호는 8자 이상이어야 합니다.')

        hashed_pwd = hash_password(raw_password)
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (username, password) VALUES (%s, %s)",
                    (username, hashed_pwd)
                )
            conn.commit()
            conn.close()
            return redirect(url_for('login'))
        except pymysql.err.IntegrityError:
            conn.close()
            return render_template('register.html', error='이미 존재하는 아이디입니다.')
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        raw_password = request.form.get('password', '')

        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
        conn.close()

        if user and check_password(raw_password, user['password']):
            session.clear()  # 세션 고정 공격 방지
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='아이디 또는 비밀번호가 틀렸습니다.')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/board/<int:board_id>')
def view_board(board_id):
    search_keyword = request.args.get('search', '').strip()
    sort_order = request.args.get('sort', 'desc')
    if sort_order not in ('asc', 'desc'):
        sort_order = 'desc'

    order_sql = "ORDER BY p.created_at DESC" if sort_order == 'desc' else "ORDER BY p.created_at ASC"

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT name FROM boards WHERE id = %s", (board_id,))
        board = cursor.fetchone()
        if not board:
            conn.close()
            abort(404)
        board_name = board['name']

        if search_keyword:
            sql = f"""
                SELECT p.id, p.title, u.username, p.created_at
                FROM posts p
                INNER JOIN users u ON p.author_id = u.id
                WHERE p.board_id = %s AND p.title LIKE %s
                {order_sql}
            """
            cursor.execute(sql, (board_id, f"%{search_keyword}%"))
        else:
            sql = f"""
                SELECT p.id, p.title, u.username, p.created_at
                FROM posts p
                INNER JOIN users u ON p.author_id = u.id
                WHERE p.board_id = %s
                {order_sql}
            """
            cursor.execute(sql, (board_id,))
        posts = cursor.fetchall()
    conn.close()

    total_posts = len(posts)
    for index, post in enumerate(posts):
        post['display_num'] = total_posts - index if sort_order == 'desc' else index + 1

    return render_template('board.html',
                           board_id=board_id,
                           board_name=board_name,
                           posts=posts,
                           search_keyword=search_keyword,
                           sort_order=sort_order)


@app.route('/board/<int:board_id>/write', methods=['GET', 'POST'])
@login_required
def write_post(board_id):
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()

        if not title or len(title) > 200:
            return render_template('write.html', board_id=board_id, error='제목은 1~200자 사이여야 합니다.')
        if not content:
            return render_template('write.html', board_id=board_id, error='본문을 입력해주세요.')

        author_id = session['user_id']

        file = request.files.get('file')
        filename = None
        if file and file.filename != '':
            if not allowed_file(file.filename):
                return render_template('write.html', board_id=board_id,
                                       error=f'허용되지 않는 파일 형식입니다. 허용: {", ".join(ALLOWED_EXTENSIONS)}')
            original_name = secure_filename(file.filename)
            import uuid
            filename = f"{uuid.uuid4().hex}_{original_name}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO posts (title, content, author_id, board_id) VALUES (%s, %s, %s, %s)",
                (title, content, author_id, board_id)
            )
            post_id = cursor.lastrowid
            if filename:
                cursor.execute(
                    "INSERT INTO attachments (post_id, original_name, stored_path) VALUES (%s, %s, %s)",
                    (post_id, original_name, filename)
                )
        conn.commit()
        conn.close()
        return redirect(url_for('view_board', board_id=board_id))
    return render_template('write.html', board_id=board_id)


@app.route('/post/<int:post_id>')
def view_post(post_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT p.*, u.username FROM posts p INNER JOIN users u ON p.author_id = u.id WHERE p.id = %s",
            (post_id,)
        )
        post = cursor.fetchone()
        if not post:
            conn.close()
            abort(404)

        cursor.execute("SELECT * FROM attachments WHERE post_id = %s", (post_id,))
        file_info = cursor.fetchone()

        cursor.execute(
            "SELECT c.*, u.username FROM comments c INNER JOIN users u ON c.author_id = u.id WHERE c.post_id = %s ORDER BY c.created_at ASC",
            (post_id,)
        )
        comments = cursor.fetchall()
    conn.close()
    return render_template('view.html', post=post, comments=comments, file_info=file_info)


@app.route('/download/<int:file_id>')
def download_file(file_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM attachments WHERE id = %s", (file_id,))
        attachment = cursor.fetchone()
    conn.close()

    if not attachment:
        abort(404)

    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        attachment['stored_path'],
        as_attachment=True,
        download_name=attachment['original_name']
    )


@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM posts WHERE id = %s", (post_id,))
        post = cursor.fetchone()

    if not post:
        conn.close()
        abort(404)

    if session.get('user_id') != post['author_id']:
        conn.close()
        return render_template('error.html', message='수정 권한이 없습니다.'), 403

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()

        if not title or len(title) > 200:
            conn.close()
            return render_template('edit.html', post=post, error='제목은 1~200자 사이여야 합니다.')

        file = request.files.get('file')
        new_filename = None
        original_name = None
        if file and file.filename != '':
            if not allowed_file(file.filename):
                conn.close()
                return render_template('edit.html', post=post,
                                       error=f'허용되지 않는 파일 형식입니다. 허용: {", ".join(ALLOWED_EXTENSIONS)}')
            original_name = secure_filename(file.filename)
            import uuid
            new_filename = f"{uuid.uuid4().hex}_{original_name}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], new_filename))

        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE posts SET title = %s, content = %s WHERE id = %s",
                (title, content, post_id)
            )
            if new_filename:
                cursor.execute("SELECT * FROM attachments WHERE post_id = %s", (post_id,))
                existing = cursor.fetchone()
                if existing:
                    cursor.execute(
                        "UPDATE attachments SET original_name = %s, stored_path = %s WHERE post_id = %s",
                        (original_name, new_filename, post_id)
                    )
                else:
                    cursor.execute(
                        "INSERT INTO attachments (post_id, original_name, stored_path) VALUES (%s, %s, %s)",
                        (post_id, original_name, new_filename)
                    )
        conn.commit()
        conn.close()
        return redirect(url_for('view_post', post_id=post_id))

    conn.close()
    return render_template('edit.html', post=post)


@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM posts WHERE id = %s", (post_id,))
        post = cursor.fetchone()

    if not post:
        conn.close()
        abort(404)

    if session.get('user_id') != post['author_id']:
        conn.close()
        return render_template('error.html', message='삭제 권한이 없습니다.'), 403

    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM posts WHERE id = %s", (post_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('view_board', board_id=post['board_id']))


@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def add_comment(post_id):
    content = request.form.get('comment_content', '').strip()
    if not content or len(content) > 1000:
        return redirect(url_for('view_post', post_id=post_id))

    author_id = session['user_id']
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO comments (post_id, author_id, content) VALUES (%s, %s, %s)",
            (post_id, author_id, content)
        )
    conn.commit()
    conn.close()
    return redirect(url_for('view_post', post_id=post_id))


@app.route('/comment/<int:comment_id>/edit', methods=['POST'])
@login_required
def edit_comment(comment_id):
    post_id = request.form.get('post_id')
    new_content = request.form.get('content', '').strip()

    if not new_content or len(new_content) > 1000:
        return redirect(url_for('view_post', post_id=post_id))

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM comments WHERE id = %s", (comment_id,))
        comment = cursor.fetchone()

    if not comment or session.get('user_id') != comment['author_id']:
        conn.close()
        return render_template('error.html', message='수정 권한이 없습니다.'), 403

    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE comments SET content = %s WHERE id = %s",
            (new_content, comment_id)
        )
    conn.commit()
    conn.close()
    return redirect(url_for('view_post', post_id=post_id))


@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    post_id = request.form.get('post_id')
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM comments WHERE id = %s", (comment_id,))
        comment = cursor.fetchone()

    if not comment or session.get('user_id') != comment['author_id']:
        conn.close()
        return render_template('error.html', message='삭제 권한이 없습니다.'), 403

    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM comments WHERE id = %s", (comment_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('view_post', post_id=post_id))


@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', message='페이지를 찾을 수 없습니다.'), 404


@app.errorhandler(413)
def too_large(e):
    return render_template('error.html', message='파일 크기가 너무 큽니다. (최대 10MB)'), 413


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
