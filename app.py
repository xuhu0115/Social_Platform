# app.py

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_mysqldb import MySQL
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

# 初始化MySQL连接
mysql = MySQL(app)

# 初始化加密库和登录管理器
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'  # 未登录时访问受保护路由会重定向到 'login'

# 用户模型类，用于管理登录会话
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id            # 用户ID
        self.username = username # 用户名

# 定义用户加载函数，获取用户实例
@login_manager.user_loader
def load_user(user_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, username FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    if user:
        return User(id=user[0], username=user[1])  # 返回用户对象
    return None

# 用户注册路由
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # 获取注册表单中的用户名和密码
        username = request.form['username']
        password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
        
        # 存储用户数据到数据库
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, password))
        mysql.connection.commit()
        cur.close()
        
        flash("Registration successful!")  # 提示用户注册成功
        return redirect(url_for('login'))  # 重定向到登录页面
    return render_template('register.html')  # 渲染注册页面

# 用户登录路由
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # 获取登录表单中的用户名和密码
        username = request.form['username']
        password = request.form['password']
        
        # 查询用户数据
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, password FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        
        # 验证用户名和密码
        if user and bcrypt.check_password_hash(user[1], password):
            login_user(User(id=user[0], username=username))
            return redirect(url_for('index'))
        else:
            flash("Login failed. Check your credentials.")  # 登录失败提示
    return render_template('login.html')  # 渲染登录页面

# 用户注销路由
@app.route('/logout')
@login_required
def logout():
    logout_user()  # 退出登录
    return redirect(url_for('login'))  # 重定向到登录页面

# 首页路由，显示用户自己和好友的状态
@app.route('/')
@login_required
def index():
    cur = mysql.connection.cursor()
    
    # 查询当前用户和所有已接受好友的发布内容
    cur.execute("""
        SELECT posts.id, users.username, posts.content 
        FROM posts 
        JOIN users ON posts.user_id = users.id
        WHERE posts.user_id = %s 
        OR posts.user_id IN (
            SELECT friend_id FROM friends WHERE user_id = %s AND status = 'accepted'
        )
        OR posts.user_id IN (
            SELECT user_id FROM friends WHERE friend_id = %s AND status = 'accepted'
        )
    """, (current_user.id, current_user.id, current_user.id))
    
    posts = cur.fetchall()
    cur.close()
    return render_template('index.html', posts=posts)




# 发布状态路由
@app.route('/post', methods=['GET', 'POST'])
@login_required
def post():
    if request.method == 'POST':
        # 获取状态内容
        content = request.form['content']
        
        # 存储状态到数据库
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO posts (user_id, content) VALUES (%s, %s)", (current_user.id, content))
        mysql.connection.commit()
        cur.close()
        
        return redirect(url_for('index'))  # 发布成功后重定向到主页
    return render_template('post.html')  # 渲染发布状态页面

# 添加好友路由
@app.route('/add_friend', methods=['GET', 'POST'])
@login_required
def add_friend():
    if request.method == 'POST':
        friend_username = request.form['friend_username']
        
        # 查询用户名对应的用户ID
        cur = mysql.connection.cursor()
        cur.execute("SELECT id FROM users WHERE username = %s", (friend_username,))
        friend = cur.fetchone()
        
        if friend:
            friend_id = friend[0]
            # 检查是否已发送好友请求或已经是好友
            cur.execute("SELECT * FROM friends WHERE user_id = %s AND friend_id = %s", (current_user.id, friend_id))
            existing_request = cur.fetchone()
            
            if not existing_request:
                # 插入好友请求记录，状态为 'pending'
                cur.execute("INSERT INTO friends (user_id, friend_id, status) VALUES (%s, %s, 'pending')", (current_user.id, friend_id))
                mysql.connection.commit()
                flash(f"Friend request sent to {friend_username}!")
            else:
                flash(f"Friend request to {friend_username} is already pending or accepted.")
        else:
            flash("User not found.")
        
        cur.close()
    return render_template('add_friend.html')

# 查看好友请求路由
@app.route('/friend_requests')
@login_required
def friend_requests():
    cur = mysql.connection.cursor()
    # 查询待确认的好友请求
    cur.execute("""
        SELECT friends.id, users.username 
        FROM friends 
        JOIN users ON friends.user_id = users.id
        WHERE friends.friend_id = %s AND friends.status = 'pending'
    """, (current_user.id,))
    requests = cur.fetchall()
    cur.close()
    return render_template('friend_requests.html', requests=requests)

# 处理好友请求接受/拒绝的路由
@app.route('/respond_friend_request/<int:request_id>/<action>')
@login_required
def respond_friend_request(request_id, action):
    cur = mysql.connection.cursor()
    
    # 检查好友请求的有效性
    cur.execute("SELECT * FROM friends WHERE id = %s AND friend_id = %s", (request_id, current_user.id))
    friend_request = cur.fetchone()
    
    if friend_request:
        if action == "accept":
            # 更新好友关系状态为 'accepted'
            cur.execute("UPDATE friends SET status = 'accepted' WHERE id = %s", (request_id,))
            
            # 双向添加好友关系
            cur.execute("INSERT INTO friends (user_id, friend_id, status) VALUES (%s, %s, 'accepted')", 
                        (current_user.id, friend_request[1]))
            flash("Friend request accepted!")
            
        elif action == "reject":
            cur.execute("UPDATE friends SET status = 'rejected' WHERE id = %s", (request_id,))
            flash("Friend request rejected.")
        
        mysql.connection.commit()
    else:
        flash("Invalid friend request.")
    
    cur.close()
    return redirect(url_for('friend_requests'))




if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port = 5008)  # 启动应用
