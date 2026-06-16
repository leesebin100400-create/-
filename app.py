from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
import pymysql
import hashlib
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_assignment'

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def get_db_connection():
    return pymysql.connect(
        host='localhost',
        user='board_user',
        password='1234',
        db='board_db',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

@app.route('/')
def index():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM boards")
        boards = cursor.fetchall()
    conn.close()
    
    html = ""
    if 'username' in session:
        html += f"<div><strong>{session['username']}</strong>님 환영합니다! <a href='/logout'>[로그아웃]</a></div>"
    else:
        html += "<div><a href='/login'>[로그인]</a> | <a href='/register'>[회원가입]</a></div>"
        
    html += "<h1>온라인 게시판 메인</h1><h3>게시판을 선택하세요:</h3><ul>"
    for board in boards:
        html += f"<li><a href='/board/{board['id']}'>{board['name']}</a></li>"
    html += "</ul>"
    
    html += """
    <hr>
    <h3>🔍 유저 검색</h3>
    <form action="/search/user" method="GET">
        <input type="text" name="keyword" placeholder="검색할 유저명 입력" required>
        <button type="submit">검색</button>
    </form>
    """
    return html

@app.route('/search/user')
def search_user():
    keyword = request.args.get('keyword', '')
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT id, username, created_at FROM users WHERE username LIKE %s", (f"%{keyword}%",))
        users = cursor.fetchall()
    conn.close()
    
    html = f"<h1>'{keyword}' 유저 검색 결과</h1><a href='/'>[메인으로]</a><br><br><table border='1'>"
    html += "<tr><th>유저 고유번호</th><th>아이디</th><th>가입일</th></tr>"
    for user in users:
        html += f"<tr><td>{user['id']}</td><td>{user['username']}</td><td>{user['created_at']}</td></tr>"
    html += "</table>"
    return html

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        raw_password = request.form['password']
        hashed_pwd = hash_password(raw_password)
        
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                sql = "INSERT INTO users (username, password) VALUES (%s, %s)"
                cursor.execute(sql, (username, hashed_pwd))
            conn.commit()
            conn.close()
            return "<script>alert('회원가입 성공!'); location.href='/login';</script>"
        except pymysql.err.IntegrityError:
            return "<script>alert('이미 존재하는 아이디입니다.'); history.back();</script>"
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        raw_password = request.form['password']
        hashed_pwd = hash_password(raw_password)
        
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT * FROM users WHERE username = %s AND password = %s"
            cursor.execute(sql, (username, hashed_pwd))
            user = cursor.fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('index'))
        else:
            return "<script>alert('아이디 또는 비밀번호가 틀렸습니다.'); history.back();</script>"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# [정렬 및 순번 버그가 해결된] 게시판 조회 라우터
@app.route('/board/<int:board_id>')
def view_board(board_id):
    search_keyword = request.args.get('search', '')
    sort_order = request.args.get('sort', 'desc') # 기본값은 desc (최신순)
    
    order_sql = "ORDER BY p.created_at DESC" if sort_order == 'desc' else "ORDER BY p.created_at ASC"
    
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT name FROM boards WHERE id = %s", (board_id,))
        board = cursor.fetchone()
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

    html = ""
    if 'username' in session:
        html += f"<div><strong>{session['username']}</strong>님 로그인 중 | <a href='/logout'>[로그아웃]</a></div>"
    else:
        html += f"<div><a href='/login'>[로그인]</a> 후 글을 작성할 수 있습니다.</div>"

    html += f"<h1>{board_name}</h1>"
    html += "<a href='/'>[메인으로 돌아가기]</a>"
    if 'username' in session:
        html += f" | <a href='/board/{board_id}/write'><strong>[새 글 쓰기]</strong></a>"
        
    html += f"""
    <br><br>
    <div>
        정렬 방식 옵션: 
        <a href="/board/{board_id}?search={search_keyword}&sort=desc"><strong>[최신순]</strong></a> | 
        <a href="/board/{board_id}?search={search_keyword}&sort=asc"><strong>[오래된순]</strong></a>
    </div>
    """
        
    html += f"""
    <form action="/board/{board_id}" method="GET">
        <input type="hidden" name="sort" value="{sort_order}">
        <input type="text" name="search" value="{search_keyword}" placeholder="게시글 제목 검색">
        <button type="submit">검색</button>
    </form>
    """
        
    html += "<br><table border='1' width='600'><tr><th>번호</th><th>제목</th><th>작성자</th><th>작성일</th></tr>"
    if not posts:
        html += "<tr><td colspan='4' align='center'>등록된 게시글이 없습니다.</td></tr>"
    else:
        # 💡 [핵심 버그 수정] 총 게시글 개수를 바탕으로 화면에 보여줄 순번 계산
        total_posts = len(posts)
        
        for index, post in enumerate(posts):
            # 최신순일 때는 번호가 큰 것부터 내려가고, 오래된순일 때는 1번부터 올라가도록 설정
            if sort_order == 'desc':
                display_num = total_posts - index
            else:
                display_num = index + 1
                
            # {post['id']} 대신 계산된 가상 번호 {display_num}을 첫 번째 칸에 출력합니다.
            # 상세 보기 링크(<a href='/post/...'>)는 원래 고유 ID인 post['id']를 유지해야 정상 접속됩니다!
            html += f"<tr><td align='center'>{display_num}</td><td><a href='/post/{post['id']}'>>{post['title']}</a></td><td align='center'>{post['username']}</td><td align='center'>{post['created_at']}</td></tr>"
            
    html += "</table>"
    return html
@app.route('/board/<int:board_id>/write', methods=['GET', 'POST'])
def write_post(board_id):
    if 'user_id' not in session:
        return "<script>alert('로그인이 필요한 서비스입니다.'); location.href='/login';</script>"
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        author_id = session['user_id']
        
        file = request.files.get('file')
        filename = ""
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "INSERT INTO posts (title, content, author_id, board_id) VALUES (%s, %s, %s, %s)"
            cursor.execute(sql, (title, content, author_id, board_id))
            post_id = cursor.lastrowid
            
            if filename:
                sql_file = "INSERT INTO attachments (post_id, original_name, stored_path) VALUES (%s, %s, %s)"
                cursor.execute(sql_file, (post_id, filename, filename))
                
        conn.commit()
        conn.close()
        return redirect(f'/board/{board_id}')
    return render_template('write.html', board_id=board_id)

@app.route('/post/<int:post_id>')
def view_post(post_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        sql_post = "SELECT p.*, u.username FROM posts p INNER JOIN users u ON p.author_id = u.id WHERE p.id = %s"
        cursor.execute(sql_post, (post_id,))
        post = cursor.fetchone()
        
        cursor.execute("SELECT * FROM attachments WHERE post_id = %s", (post_id,))
        file_info = cursor.fetchone()
        
        sql_comments = "SELECT c.*, u.username FROM comments c INNER JOIN users u ON c.author_id = u.id WHERE c.post_id = %s ORDER BY c.created_at ASC"
        cursor.execute(sql_comments, (post_id,))
        comments = cursor.fetchall()
    conn.close()
    return render_template('view.html', post=post, comments=comments, file_info=file_info)

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)


# [수정 및 강화] 게시글 수정 시 파일 데이터 변경/수정 로직 완벽 연동
@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
def edit_post(post_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM posts WHERE id = %s", (post_id,))
        post = cursor.fetchone()
    if session.get('user_id') != post['author_id']:
        conn.close()
        return "<script>alert('권한이 없습니다.'); history.back();</script>"
        
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        
        # 새 수정 파일 확인
        file = request.files.get('file')
        filename = ""
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            
        with conn.cursor() as cursor:
            # 1. 글 제목 및 본문 업데이트
            cursor.execute("UPDATE posts SET title = %s, content = %s WHERE id = %s", (title, content, post_id))
            
            # 2. 새로운 파일이 업로드되었다면 파일 테이블도 연동 갱신
            if filename:
                # 기존 파일 기록이 있는지 체크
                cursor.execute("SELECT * FROM attachments WHERE post_id = %s", (post_id,))
                existing_file = cursor.fetchone()
                if existing_file:
                    cursor.execute("UPDATE attachments SET original_name = %s, stored_path = %s WHERE post_id = %s", (filename, filename, post_id))
                else:
                    cursor.execute("INSERT INTO attachments (post_id, original_name, stored_path) VALUES (%s, %s, %s)", (post_id, filename, filename))
                    
        conn.commit()
        conn.close()
        return redirect(f'/post/{post_id}')
    conn.close()
    return render_template('edit.html', post=post)

@app.route('/post/<int:post_id>/delete')
def delete_post(post_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM posts WHERE id = %s", (post_id,))
        post = cursor.fetchone()
    if session.get('user_id') != post['author_id']:
        conn.close()
        return "<script>alert('권한이 없습니다.'); history.back();</script>"
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM posts WHERE id = %s", (post_id,))
    conn.commit()
    conn.close()
    return redirect(f'/board/{post["board_id"]}')

@app.route('/post/<int:post_id>/comment', methods=['POST'])
def add_comment(post_id):
    if 'user_id' not in session:
        return "<script>alert('로그인이 필요합니다.'); location.href='/login';</script>"
    content = request.form['comment_content']
    author_id = session['user_id']
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO comments (post_id, author_id, content) VALUES (%s, %s, %s)", (post_id, author_id, content))
    conn.commit()
    conn.close()
    return redirect(f'/post/{post_id}')


# [신규 추가] 댓글 수정 처리 라우터 연동 (UPDATE 구문 사용)
@app.route('/comment/<int:comment_id>/edit', methods=['POST'])
def edit_comment(comment_id):
    post_id = request.form.get('post_id')
    new_content = request.form.get('content')
    
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM comments WHERE id = %s", (comment_id,))
        comment = cursor.fetchone()
        
    if not comment or session.get('user_id') != comment['author_id']:
        conn.close()
        return "<script>alert('권한이 없습니다.'); history.back();</script>"
        
    with conn.cursor() as cursor:
        cursor.execute("UPDATE comments SET content = %s WHERE id = %s", (new_content, comment_id))
    conn.commit()
    conn.close()
    return redirect(f'/post/{post_id}')


@app.route('/comment/<int:comment_id>/delete')
def delete_comment(comment_id):
    post_id = request.args.get('post_id')
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM comments WHERE id = %s", (comment_id,))
        comment = cursor.fetchone()
    if session.get('user_id') != comment['author_id']:
        conn.close()
        return "<script>alert('권한이 없습니다.'); history.back();</script>"
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM comments WHERE id = %s", (comment_id,))
    conn.commit()
    conn.close()
    return redirect(f'/post/{post_id}')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
