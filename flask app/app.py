from flask import Flask, render_template, redirect, url_for, session, request, flash, jsonify
from dbhelperPostgres import * 
from flask_caching import Cache
import redis
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime, timedelta



app = Flask(__name__)
app.config['SESSION_TYPE'] = 'redis'
app.permanent_session_lifetime = timedelta(hours=1)
app.config['SESSION_REDIS'] = redis.StrictRedis.from_url('redis://red-cuis0p23esus739lbi20:6379')
app.config['CACHE_TYPE'] = 'redis'
app.config['CACHE_REDIS_URL'] = 'redis://red-cuis0p23esus739lbi20:6379'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300

app.secret_key = '%:%:'
socketio = SocketIO(app, cors_allowed_origins="*")

active_users_dict = {}  # Dictionary to store active users (username -> session ID)

@socketio.on('connect')
def handle_connect():
    if 'username' in session:
        username = session['username']
        if not username.startswith('admin-'):  # Exclude admin users
            sid = request.sid  # Get unique session ID
            active_users_dict[username] = sid  # Store session ID for each user
            emit('update_active_users', list(active_users_dict.keys()), broadcast=True)  # Send updates

@socketio.on('disconnect')
def handle_disconnect():
    username = None
    for user, sid in list(active_users_dict.items()):
        if sid == request.sid:
            username = user
            break

    if username:
        del active_users_dict[username]  # Remove user on disconnect
        emit('update_active_users', list(active_users_dict.keys()), broadcast=True)

@socketio.on('user_login')
def handle_user_login(username):
    if not username.startswith('admin-'):  # Exclude admin users
        sid = request.sid  # Get unique session ID
        active_users_dict[username] = sid  # Store session ID for each user
        emit('update_active_users', list(active_users_dict.keys()), broadcast=True)

@socketio.on('user_logout')
def handle_user_logout(username):
    if username in active_users_dict:
        del active_users_dict[username]  # Remove user on logout
        emit('update_active_users', list(active_users_dict.keys()), broadcast=True)


@app.after_request
def after_request(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    if hasattr(session, 'username') and 'username' not in session:
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
    return response


@app.route('/', methods=['GET', 'POST'])
def login():
    pagetitle = "Login"
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash("Username and Password are required", 'error')
            return redirect(url_for('login'))

        user = get_user_by_credentials(username, password)

        if user:
            session['username'] = username  
            student_id = user['id']
            lastname = user['lastname']  # Get lastname
            firstname = user['firstname']  # Get firstname
            session_token = generate_session_token()

            # ✅ Pass lastname and firstname to save_session()
            if save_session(student_id, session_token, lastname, firstname):
                socketio.emit('user_login', {'username': username, 'session_token': session_token}, to='/')
                flash("Login successful!", 'success')
                return redirect(url_for('student_dashboard'))
            else:
                flash("Error saving session", 'error')
                return redirect(url_for('login'))
        else:
            flash("Invalid username or password", 'error')
            return redirect(url_for('login'))

    return render_template('client/login.html', pagetitle=pagetitle)


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')  
        new_password = request.form.get('new_password')  

        if email and new_password:
            student = get_student_by_email(email)
            if not student:
                flash('Student does not exist.', 'error')
                return redirect(url_for('forgot_password'))

            result = update_record('students', email=email, password=new_password)
            
            if result:
                flash('Password updated successfully!', 'success')
                return redirect(url_for('login'))  
            else:
                flash('Error updating password. Please try again.', 'warning')
                return redirect(url_for('forgot_password'))

        flash('Invalid input. Please provide both email and new password.', 'warning')
        return redirect(url_for('forgot_password'))

    return render_template('client/forgotpassword.html')


@app.route('/student_dashboard')
def student_dashboard():
    pagetitle = "Student Dashboard"
    if 'username' not in session:
        flash("You need to login first", 'warning')
        return redirect(url_for('login'))
    student = get_student_by_username(session['username'])
    if not student:
        flash("Student not found", 'danger')
        return redirect(url_for('login'))
    return render_template('client/studentdashboard.html', student=student, pagetitle=pagetitle)



@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        idno = request.form.get('idno')
        lastname = request.form.get('lastname')
        firstname = request.form.get('firstname')
        midname = request.form.get('midname')
        course = request.form.get('course')
        year_level = request.form.get('year_level')
        email = request.form.get('email')
        username = request.form.get('username')
        password = request.form.get('password')

        if not all([idno, lastname, firstname, course, username, password]):
            flash("All fields are required.", 'error')
            return redirect(url_for('login'))

        existing_student = get_student_by_id(idno)
        if existing_student:
            flash("Student ID already exists.", 'error')
            return redirect(url_for('register'))

        existing_email = get_student_by_email(email)
        if existing_email:
            flash("Email already exists.", 'error')
            return redirect(url_for('register'))

        student_data = {
            'idno': idno,
            'lastname': lastname,
            'firstname': firstname,
            'midname': midname,
            'course': course,
            'year_level': year_level,
            'email': email,
            'username': username,
            'password': password
        }

        if add_record('students', **student_data):
            flash("Registration successful!", 'success')
            return redirect(url_for('login'))
        else:
            flash("Registration failed. Try again.", 'error')

    return render_template('client/register.html')



@app.route('/admin', methods=['GET', 'POST'])  
def admin_login():
    pagetitle = 'Administrator Login'
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash("Username and Password are required", 'error')
            return redirect(url_for('login'))

        admin = get_admin_user_by_credentials(username, password)

        if admin:
            session['username'] = username  
            flash("Login successful!", 'success')
            return redirect(url_for('dashboard'))  
        else:
            flash("Invalid username or password", 'error')
            return redirect(url_for('admin_login'))

    return render_template('admin/adminlogin.html', pagetitle=pagetitle)


@app.route('/admin/super-secret-admin-register', methods=['GET', 'POST'])
def admin_register():
    if request.method == 'POST':
        secret_key = request.form.get('secret_key')
        admin_username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        name = request.form.get('name')

        if secret_key != "kimperor123":
            flash("Unauthorized access!", 'error')
            return render_template('admin/adminregister.html')  

        if not admin_username.startswith("admin-"):
            flash("Invalid admin username format!", 'error')
            return render_template('admin/adminregister.html')  

        existing_admin = get_admin_by_username(admin_username)
        if existing_admin:
            flash("Admin username already exists!", 'error')
            return render_template('admin/adminregister.html')  

        if add_record('admin_users', admin_username=admin_username, password=password, email=email, name=name):
            flash("Admin registered successfully!", 'success')
            return redirect(url_for('admin_login')) 
        else:
            flash("Error registering admin. Please try again.", 'error')
            return render_template('admin/adminregister.html') 
    
    return render_template('admin/adminregister.html')


@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        flash("You need to login first", 'warning')
        return redirect(url_for('admin_login'))
    
    student_count = get_count_students()
    
    return render_template('admin/dashboard.html', student_count=student_count)

@app.route('/get_user_count')
def get_user_count():
    return jsonify(student_count=get_count_students())

@app.route('/adminLogout')
def adminLogout():
    if 'admin_username' in session:
        session.pop('admin_username', None)  # Logs out only the admin
        flash("Admin has been logged out.", 'info')
    return redirect(url_for('admin_login'))


@app.route('/logout')
def logout():
    username = session.get('username')
    
    # Fetch student details (modify this function as needed)
    student = get_student_by_username(username)  # Use existing function

    if not student:
        flash("Error: Student not found", 'error')
        return redirect(url_for('login'))

    student_id = student.get('id')  # Adjust according to your function's return value
    session.pop('username', None)

    connection = connect_to_db()
    if not connection:
        return redirect(url_for('login'))

    timeout = datetime.now()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE student_sessions 
                SET timeout = %s 
                WHERE student_id = %s 
                AND timeout IS NULL
                """,
                (timeout, student_id)
            )
            connection.commit()

            # DEBUGGING: Check if the row was actually updated
            cursor.execute(
                "SELECT timeout FROM student_sessions WHERE student_id = %s ORDER BY id DESC LIMIT 1", 
                (student_id,)
            )
            result = cursor.fetchone()
            print(f"Updated timeout: {result[0] if result else 'No update'}")  # Debugging

    except Exception as e:
        print(f"Error during logout: {e}")

    socketio.emit('user_logout', {'username': username}, to='/')
    flash("Logout successful", 'info')
    return redirect(url_for('login'))



if __name__ == "__main__":
    socketio.run(app, debug=True)