from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps
import os
from dotenv import load_dotenv

from models import db, User, Video, Material, Task, TaskSubmission, Comment, Message, Notification

load_dotenv()

app = Flask(__name__)
csrf = CSRFProtect(app)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')

# Ensure instance folder exists
instance_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
os.makedirs(instance_path, exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(instance_path, "mancera.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))  # 16MB

# Extensoes permitidas para upload
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt', 'jpg', 'jpeg', 'png', 'gif', 'ppt', 'pptx', 'xls', 'xlsx', 'zip', 'rar', '7z'}

def allowed_file(filename):
    """Verifica se o arquivo tem uma extensao permitida"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'submissions'), exist_ok=True)

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Por favor, faça login para acessar esta página.'

# Add template context processor
@app.context_processor
def utility_processor():
    def now():
        return datetime.utcnow()
    return dict(now=now)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Custom decorator for role-based access
def professor_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'professor':
            flash('Acesso negado. Apenas professores podem acessar esta página.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'student':
            flash('Acesso negado.', 'danger')
            return redirect(url_for('login'))
        
        # Check if student account is active and not expired
        if not current_user.is_active:
            flash('Sua conta está desativada. Entre em contato com o professor.', 'warning')
            logout_user()
            return redirect(url_for('login'))
        
        if current_user.is_subscription_expired():
            current_user.is_active = False
            db.session.commit()
            flash('Sua assinatura expirou. Entre em contato com o professor.', 'warning')
            logout_user()
            return redirect(url_for('login'))
        
        return f(*args, **kwargs)
    return decorated_function

# Helper function to create notifications
def create_notification(user_id, title, message, notif_type, reference_id=None):
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        type=notif_type,
        reference_id=reference_id
    )
    db.session.add(notification)

# Helper function to notify all students
def notify_all_students(title, message, notif_type, reference_id=None):
    students = User.query.filter_by(role='student', is_active=True).all()
    for student in students:
        create_notification(student.id, title, message, notif_type, reference_id)

# Auto-migration function to add missing columns
def auto_migrate():
    """Adiciona colunas faltantes automaticamente"""
    import sqlite3
    db_path = os.path.join(instance_path, "mancera.db")
    
    if not os.path.exists(db_path):
        return  # Banco sera criado pelo create_all()
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    def get_columns(table):
        cursor.execute(f"PRAGMA table_info({table})")
        return [row[1] for row in cursor.fetchall()]
    
    def add_column(table, column, col_type, default=None):
        if column not in get_columns(table):
            default_clause = ""
            if default is not None:
                if isinstance(default, str):
                    default_clause = f" DEFAULT '{default}'"
                elif isinstance(default, bool):
                    default_clause = f" DEFAULT {1 if default else 0}"
                else:
                    default_clause = f" DEFAULT {default}"
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}")
                print(f"[Migration] Coluna '{column}' adicionada em '{table}'")
            except Exception as e:
                print(f"[Migration] Erro ao adicionar '{column}': {e}")
    
    # Migrações necessarias
    add_column('videos', 'file_path', 'VARCHAR(500)')
    add_column('videos', 'duration', 'VARCHAR(20)')
    add_column('tasks', 'attachment', 'VARCHAR(500)')
    add_column('tasks', 'allow_late_submission', 'BOOLEAN', default=True)
    add_column('tasks', 'external_link', 'VARCHAR(500)')
    add_column('tasks', 'external_link_type', 'VARCHAR(50)')
    add_column('tasks', 'task_type', 'VARCHAR(20)', default='normal')
    add_column('task_submissions', 'file_path', 'VARCHAR(500)')
    add_column('task_submissions', 'is_late', 'BOOLEAN', default=False)
    add_column('task_submissions', 'graded_at', 'DATETIME')
    add_column('task_submissions', 'updated_at', 'DATETIME')
    
    conn.commit()
    conn.close()

# Initialize database and create default professor
with app.app_context():
    # Executar migrações automaticas antes de criar tabelas
    auto_migrate()
    
    # Criar tabelas que nao existem
    db.create_all()
    
    # Create default professor if not exists
    professor = User.query.filter_by(email='vitor@mancera.com').first()
    if not professor:
        professor = User(
            email='vitor@mancera.com',
            name='Victor Mancera Viterbo',
            role='professor',
            phone='+55 17 99999-9999',
            bio='Mestre em Literaturas de Língua Portuguesa pela UNESP. Licenciado em Letras com formação bilíngue. Professor de Língua Portuguesa especializado em preparação para vestibulares e concursos. São José do Rio Preto, SP. Mancera Consultoria.'
        )
        professor.set_password('professor123')
        db.session.add(professor)
        db.session.commit()
        print('Professor padrão criado: vitor@mancera.com / professor123')
    else:
        # Update existing professor info if needed
        if professor.bio != 'Mestre em Literaturas de Língua Portuguesa pela UNESP. Licenciado em Letras com formação bilíngue. Professor de Língua Portuguesa especializado em preparação para vestibulares e concursos. São José do Rio Preto, SP. Mancera Consultoria.':
            professor.name = 'Victor Mancera Viterbo'
            professor.bio = 'Mestre em Literaturas de Língua Portuguesa pela UNESP. Licenciado em Letras com formação bilíngue. Professor de Língua Portuguesa especializado em preparação para vestibulares e concursos. São José do Rio Preto, SP. Mancera Consultoria.'
            db.session.commit()

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'professor':
            return redirect(url_for('professor_dashboard'))
        else:
            return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            # Check if student account is active
            if user.role == 'student':
                if not user.is_active:
                    flash('Sua conta está desativada. Entre em contato com o professor.', 'danger')
                    return redirect(url_for('login'))
                
                if user.is_subscription_expired():
                    user.is_active = False
                    db.session.commit()
                    flash('Sua assinatura expirou. Entre em contato com o professor.', 'danger')
                    return redirect(url_for('login'))
            
            login_user(user)
            flash('Login realizado com sucesso!', 'success')
            
            # Redirect based on role
            if user.role == 'professor':
                return redirect(url_for('professor_dashboard'))
            else:
                return redirect(url_for('student_dashboard'))
        else:
            flash('Email ou senha inválidos.', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logout realizado com sucesso!', 'success')
    return redirect(url_for('login'))

# PROFESSOR ROUTES
@app.route('/professor/dashboard')
@login_required
@professor_required
def professor_dashboard():
    stats = {
        'total_students': User.query.filter_by(role='student').count(),
        'total_videos': Video.query.count(),
        'total_materials': Material.query.count(),
        'total_tasks': Task.query.count(),
        'pending_submissions': TaskSubmission.query.filter_by(score=None).count()
    }
    return render_template('professor/dashboard.html', stats=stats)

@app.route('/professor/videos')
@login_required
@professor_required
def professor_videos():
    page = request.args.get('page', 1, type=int)
    per_page = 9  # 3x3 grid
    
    # Query com paginação
    pagination = Video.query.order_by(Video.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('professor/videos.html', 
                         videos=pagination.items,
                         pagination=pagination)

@app.route('/professor/videos/create', methods=['POST'])
@login_required
@professor_required
def create_video():
    title = request.form.get('title')
    description = request.form.get('description')
    video_url = request.form.get('video_url')
    category = request.form.get('category')
    difficulty = request.form.get('difficulty', 'medium')
    
    video = Video(
        title=title,
        description=description,
        video_url=video_url,
        category=category,
        difficulty=difficulty,
        author_id=current_user.id
    )
    db.session.add(video)
    db.session.commit()
    
    # Notify students
    notify_all_students(
        'Nova Videoaula Disponível',
        f'Nova videoaula: {title}',
        'video',
        video.id
    )
    db.session.commit()
    
    flash('Videoaula criada com sucesso!', 'success')
    return redirect(url_for('professor_videos'))

@app.route('/professor/videos/<int:id>/edit', methods=['POST'])
@login_required
@professor_required
def edit_video(id):
    video = Video.query.get_or_404(id)
    
    # Verificar se o vídeo pertence ao professor atual
    if video.author_id != current_user.id:
        flash('Acesso negado. Você não tem permissão para editar este vídeo.', 'danger')
        return redirect(url_for('professor_videos'))
    
    video.title = request.form.get('title')
    video.description = request.form.get('description')
    video.video_url = request.form.get('video_url')
    video.category = request.form.get('category')
    video.difficulty = request.form.get('difficulty')
    video.active = request.form.get('active') == 'true'
    
    db.session.commit()
    
    # Notificar alunos sobre a atualização
    if video.active:
        notify_all_students(
            'Videoaula Atualizada',
            f'Videoaula atualizada: {video.title}',
            'video',
            video.id
        )
    db.session.commit()
    
    flash('Videoaula atualizada com sucesso!', 'success')
    return redirect(url_for('professor_videos'))

@app.route('/professor/videos/<int:id>/delete', methods=['POST'])
@login_required
@professor_required
def delete_video(id):
    video = Video.query.get_or_404(id)
    
    # Verificar se o vídeo pertence ao professor atual
    if video.author_id != current_user.id:
        flash('Acesso negado. Você não tem permissão para excluir este vídeo.', 'danger')
        return redirect(url_for('professor_videos'))
    
    db.session.delete(video)
    db.session.commit()
    flash('Videoaula excluída com sucesso!', 'success')
    return redirect(url_for('professor_videos'))

@app.route('/professor/videos/<int:id>/toggle', methods=['POST'])
@login_required
@professor_required
def toggle_video_active(id):
    video = Video.query.get_or_404(id)
    
    # Verificar se o vídeo pertence ao professor atual
    if video.author_id != current_user.id:
        flash('Acesso negado. Você não tem permissão para alterar este vídeo.', 'danger')
        return redirect(url_for('professor_videos'))
    
    video.active = not video.active
    db.session.commit()
    
    status = 'ativada' if video.active else 'desativada'
    
    # Notificar alunos sobre a mudança de status
    if video.active:
        notify_all_students(
            'Videoaula Disponível',
            f'Videoaula disponível: {video.title}',
            'video',
            video.id
        )
    else:
        notify_all_students(
            'Videoaula Indisponível',
            f'Videoaula temporariamente indisponível: {video.title}',
            'video',
            video.id
        )
    db.session.commit()
    
    flash(f'Videoaula {status} com sucesso!', 'success')
    return redirect(url_for('professor_videos'))

@app.route('/professor/materials')
@login_required
@professor_required
def professor_materials():
    page = request.args.get('page', 1, type=int)
    per_page = 9  # 3x3 grid
    
    # Query com paginação para materiais
    materials_pagination = Material.query.order_by(Material.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Buscar submissões dos alunos que têm arquivos (com paginação separada)
    submissions_page = request.args.get('submissions_page', 1, type=int)
    student_submissions = TaskSubmission.query.filter(
        TaskSubmission.file_path.isnot(None)
    ).order_by(TaskSubmission.submitted_at.desc()).paginate(
        page=submissions_page, per_page=10, error_out=False
    )
    
    # Buscar tarefas que têm anexos
    tasks_with_attachments = Task.query.filter(
        Task.attachment.isnot(None)
    ).order_by(Task.created_at.desc()).all()
    
    return render_template('professor/materials.html', 
                         materials=materials_pagination.items,
                         materials_pagination=materials_pagination,
                         student_submissions=student_submissions.items,
                         submissions_pagination=student_submissions,
                         tasks_with_attachments=tasks_with_attachments)

@app.route('/professor/materials/create', methods=['POST'])
@login_required
@professor_required
def create_material():
    title = request.form.get('title')
    description = request.form.get('description')
    file_type = request.form.get('file_type')
    category = request.form.get('category')
    
    file_url = None
    if 'file' in request.files:
        file = request.files['file']
        if file and file.filename:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file.save(filepath)
            file_url = f'/static/uploads/{filename}'
    
    if not file_url:
        file_url = request.form.get('file_url')
    
    material = Material(
        title=title,
        description=description,
        file_type=file_type,
        file_url=file_url,
        category=category,
        author_id=current_user.id
    )
    db.session.add(material)
    db.session.commit()
    
    # Notify students
    notify_all_students(
        'Novo Material Disponível',
        f'Novo material: {title}',
        'material',
        material.id
    )
    db.session.commit()
    
    flash('Material criado com sucesso!', 'success')
    return redirect(url_for('professor_materials'))

@app.route('/professor/materials/<int:id>/delete', methods=['POST'])
@login_required
@professor_required
def delete_material(id):
    material = Material.query.get_or_404(id)
    db.session.delete(material)
    db.session.commit()
    flash('Material excluído com sucesso!', 'success')
    return redirect(url_for('professor_materials'))

@app.route('/professor/tasks')
@login_required
@professor_required
def professor_tasks():
    # Get query parameters
    search_query = request.args.get('search', '')
    filter_status = request.args.get('filter', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 9, type=int)
    
    # Base query
    query = Task.query
    
    # Apply search filter
    if search_query:
        query = query.filter(
            db.or_(
                Task.title.ilike(f'%{search_query}%'),
                Task.description.ilike(f'%{search_query}%')
            )
        )
    
    # Apply status filter
    if filter_status == 'pending':
        # Tarefas com submissões pendentes
        subquery = db.session.query(TaskSubmission.task_id).filter(
            TaskSubmission.score.is_(None)
        ).distinct()
        query = query.filter(Task.id.in_(subquery))
    elif filter_status == 'graded':
        # Tarefas com submissões corrigidas
        subquery = db.session.query(TaskSubmission.task_id).filter(
            TaskSubmission.score.isnot(None)
        ).distinct()
        query = query.filter(Task.id.in_(subquery))
    elif filter_status == 'with_links':
        # Tarefas com links externos
        query = query.filter(Task.external_link.isnot(None) & (Task.external_link != ''))
    
    # Order by due date
    query = query.order_by(Task.due_date.asc())
    
    # Pagination
    total_tasks = query.count()
    total_pages = (total_tasks + per_page - 1) // per_page
    tasks = query.offset((page - 1) * per_page).limit(per_page).all()
    
    # Get all submissions
    submissions = TaskSubmission.query.all()
    
    return render_template('professor/tasks.html', 
                         tasks=tasks, 
                         submissions=submissions,
                         search_query=search_query,
                         filter_status=filter_status,
                         page=page,
                         per_page=per_page,
                         total_tasks=total_tasks,
                         total_pages=total_pages)

@app.route('/professor/tasks/create', methods=['POST'])
@login_required
@professor_required
def create_task():
    title = request.form.get('title')
    description = request.form.get('description')
    due_date_str = request.form.get('due_date')
    max_score = float(request.form.get('max_score', 10))
    task_type = request.form.get('task_type', 'normal')  # 'normal' or 'redacao'
    external_link = request.form.get('external_link', '').strip()
    external_link_type = request.form.get('external_link_type', '').strip()
    
    # Validar max_score baseado no tipo
    if task_type == 'redacao':
        max_score = min(max(0, max_score), 1000)  # 0-1000 para redação
    else:
        max_score = min(max(0, max_score), 10)  # 0-10 para normal
    
    due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
    
    task = Task(
        title=title,
        description=description,
        due_date=due_date,
        max_score=max_score,
        task_type=task_type,
        external_link=external_link if external_link else None,
        external_link_type=external_link_type if external_link_type else None,
        author_id=current_user.id
    )
    db.session.add(task)
    db.session.commit()
    
    # Notify students
    notify_all_students(
        'Nova Tarefa Atribuída',
        f'Nova tarefa: {title} - Entrega até {due_date.strftime("%d/%m/%Y")}',
        'task',
        task.id
    )
    db.session.commit()
    
    flash('Tarefa criada com sucesso!', 'success')
    return redirect(url_for('professor_tasks'))

@app.route('/professor/tasks/<int:id>/delete', methods=['POST'])
@login_required
@professor_required
def delete_task(id):
    task = Task.query.get_or_404(id)
    
    # Delete all submissions for this task first
    TaskSubmission.query.filter_by(task_id=id).delete()
    
    db.session.delete(task)
    db.session.commit()
    flash('Tarefa excluída com sucesso!', 'success')
    return redirect(url_for('professor_tasks'))

@app.route('/professor/tasks/<int:id>/edit', methods=['POST'])
@login_required
@professor_required
def edit_task(id):
    task = Task.query.get_or_404(id)
    
    # Update task fields
    task.title = request.form.get('title')
    task.description = request.form.get('description')
    task.due_date = datetime.strptime(request.form.get('due_date'), '%Y-%m-%d')
    task.task_type = request.form.get('task_type', 'normal')  # 'normal' or 'redacao'
    
    max_score = float(request.form.get('max_score', 10))
    # Validar max_score baseado no tipo
    if task.task_type == 'redacao':
        task.max_score = min(max(0, max_score), 1000)  # 0-1000 para redação
    else:
        task.max_score = min(max(0, max_score), 10)  # 0-10 para normal
    
    external_link = request.form.get('external_link', '').strip()
    external_link_type = request.form.get('external_link_type', '').strip()
    task.external_link = external_link if external_link else None
    task.external_link_type = external_link_type if external_link_type else None
    
    db.session.commit()
    
    flash('Tarefa atualizada com sucesso!', 'success')
    return redirect(url_for('professor_tasks'))

@app.route('/api/tasks/<int:id>')
@login_required
@professor_required
def get_task_details(id):
    task = Task.query.get_or_404(id)
    return jsonify({
        'id': task.id,
        'title': task.title,
        'description': task.description,
        'due_date': task.due_date.strftime('%Y-%m-%d'),
        'max_score': task.max_score,
        'task_type': task.task_type or 'normal',
        'external_link': task.external_link or '',
        'external_link_type': task.external_link_type or ''
    })

@app.route('/professor/tasks/<int:task_id>/submissions')
@login_required
@professor_required
def view_task_submissions(task_id):
    task = Task.query.get_or_404(task_id)
    submissions = TaskSubmission.query.filter_by(task_id=task_id).all()
    return render_template('professor/task_submissions.html', 
                         task=task, 
                         submissions=submissions)

@app.route('/professor/submissions/<int:id>/grade', methods=['POST'])
@login_required
@professor_required
def grade_submission(id):
    submission = TaskSubmission.query.get_or_404(id)
    
    score = float(request.form.get('score'))
    # Validar score baseado no tipo da tarefa
    task_type = submission.task.task_type or 'normal'
    max_allowed = 1000 if task_type == 'redacao' else 10
    score = min(max(0, score), max_allowed)
    
    submission.score = score
    submission.feedback = request.form.get('feedback')
    
    # Create notification for student
    create_notification(
        submission.student_id,
        'Tarefa Corrigida',
        f'Sua tarefa "{submission.task.title}" foi corrigida. Nota: {submission.score}',
        'task',
        submission.task_id
    )
    
    db.session.commit()
    flash('Nota atribuída com sucesso!', 'success')
    return redirect(url_for('view_task_submissions', task_id=submission.task_id))

@app.route('/professor/students')
@login_required
@professor_required
def professor_students():
    page = request.args.get('page', 1, type=int)
    view_mode = request.args.get('view_mode', 'cards')
    
    # Paginação - 8 alunos por página
    students_query = User.query.filter_by(role='student').order_by(User.name.asc())
    pagination = students_query.paginate(
        page=page, 
        per_page=8, 
        error_out=False
    )
    
    # Calcular estatísticas para os contadores
    total_students = students_query.count()
    active_students = students_query.filter_by(is_active=True).count()
    inactive_students = total_students - active_students
    
    # Calcular alunos com assinatura expirada
    expired_students = 0
    for student in students_query:
        if student.is_subscription_expired():
            expired_students += 1
    
    return render_template(
        'professor/students.html', 
        students=students_query.all(),  # Para os contadores e filtros
        paginated_students=pagination.items,  # Para a lista paginada
        pagination=pagination,
        view_mode=view_mode,
        stats={
            'total': total_students,
            'active': active_students,
            'inactive': inactive_students,
            'expired': expired_students
        }
    )

@app.route('/professor/students/create', methods=['POST'])
@login_required
@professor_required
def create_student():
    email = request.form.get('email')
    
    # Check if email already exists
    existing = User.query.filter_by(email=email).first()
    if existing:
        flash('Email já cadastrado.', 'danger')
        return redirect(url_for('professor_students'))
    
    student = User(
        email=email,
        name=request.form.get('name'),
        role='student',
        phone=request.form.get('phone'),
        birth_date=request.form.get('birth_date'),
        is_active=request.form.get('is_active') == 'on'
    )
    student.set_password(request.form.get('password'))
    
    # Set subscription end date if provided
    subscription_end = request.form.get('subscription_end_date')
    if subscription_end:
        student.subscription_end_date = datetime.strptime(subscription_end, '%Y-%m-%d')
    
    db.session.add(student)
    db.session.commit()
    
    flash('Aluno cadastrado com sucesso!', 'success')
    return redirect(url_for('professor_students'))

@app.route('/professor/students/<int:id>/toggle', methods=['POST'])
@login_required
@professor_required
def toggle_student_active(id):
    student = User.query.get_or_404(id)
    student.is_active = not student.is_active
    db.session.commit()
    
    status = 'ativado' if student.is_active else 'desativado'
    flash(f'Aluno {status} com sucesso!', 'success')
    return redirect(url_for('professor_students'))

@app.route('/professor/students/<int:id>/delete', methods=['POST'])
@login_required
@professor_required
def delete_student(id):
    student = User.query.get_or_404(id)
    
    # Delete related records first
    TaskSubmission.query.filter_by(student_id=id).delete()
    Message.query.filter_by(from_user_id=id).delete()
    Message.query.filter_by(to_user_id=id).delete()
    Notification.query.filter_by(user_id=id).delete()
    
    db.session.delete(student)
    db.session.commit()
    flash('Aluno excluído com sucesso!', 'success')
    return redirect(url_for('professor_students'))

@app.route('/professor/check-email', methods=['POST'])
@login_required
@professor_required
def check_email():
    data = request.get_json()
    email = data.get('email')
    
    if not email:
        return jsonify({'exists': False})
    
    # Verificar se o email já existe
    existing_student = User.query.filter_by(email=email).first()
    
    return jsonify({'exists': existing_student is not None})

@app.route('/professor/chat')
@login_required
@professor_required
def professor_chat():
    students = User.query.filter_by(role='student').all()
    
    # Get conversations with last message
    conversations = []
    for student in students:
        last_message = Message.query.filter(
            ((Message.from_user_id == current_user.id) & (Message.to_user_id == student.id)) |
            ((Message.from_user_id == student.id) & (Message.to_user_id == current_user.id))
        ).order_by(Message.created_at.desc()).first()
        
        unread_count = Message.query.filter_by(
            from_user_id=student.id,
            to_user_id=current_user.id,
            read=False
        ).count()
        
        conversations.append({
            'user': student,
            'last_message': last_message,
            'unread_count': unread_count
        })
    
    selected_student_id = request.args.get('student_id', type=int)
    messages = []
    selected_student = None
    
    if selected_student_id:
        selected_student = User.query.get(selected_student_id)
        messages = Message.query.filter(
            ((Message.from_user_id == current_user.id) & (Message.to_user_id == selected_student_id)) |
            ((Message.from_user_id == selected_student_id) & (Message.to_user_id == current_user.id))
        ).order_by(Message.created_at.asc()).all()
        
        # Mark messages as read
        Message.query.filter_by(
            from_user_id=selected_student_id,
            to_user_id=current_user.id,
            read=False
        ).update({'read': True})
        db.session.commit()
    
    return render_template('professor/chat.html', 
                         conversations=conversations, 
                         messages=messages,
                         selected_student=selected_student,
                         timedelta=timedelta,
                         now=datetime.utcnow())

@app.route('/chat/send', methods=['POST'])
@login_required
def send_message():
    to_user_id = int(request.form.get('to_user_id'))
    content = request.form.get('content')
    
    message = Message(
        content=content,
        from_user_id=current_user.id,
        to_user_id=to_user_id
    )
    db.session.add(message)
    db.session.commit()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True})
    
    if current_user.role == 'professor':
        return redirect(url_for('professor_chat', student_id=to_user_id))
    else:
        return redirect(url_for('student_chat'))

@app.route('/notifications/<int:id>/read', methods=['POST'])
@login_required
def mark_notification_read(id):
    notification = Notification.query.get_or_404(id)
    if notification.user_id == current_user.id:
        notification.read = True
        db.session.commit()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True})
    
    return redirect(url_for('notifications'))

@app.route('/notifications')
@login_required
def notifications():
    notifications_list = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(50).all()
    return render_template('notifications.html', notifications=notifications_list)

@app.route('/notifications/mark-all-read', methods=['POST'])
@login_required
def mark_all_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, read=False).update({'read': True})
    db.session.commit()
    flash('Todas as notificações foram marcadas como lidas.', 'success')
    return redirect(url_for('notifications'))

@app.route('/notifications/<int:notification_id>/delete', methods=['POST'])
@login_required
def delete_notification(notification_id):
    notification = Notification.query.get_or_404(notification_id)
    if notification.user_id == current_user.id:
        db.session.delete(notification)
        db.session.commit()
        flash('Notificação excluída.', 'success')
    return redirect(url_for('notifications'))

# Adicionar rota update_video que está faltando (referenciada no JavaScript)
@app.route('/professor/update_video/<int:id>', methods=['POST'])
@login_required
@professor_required
def update_video(id):
    video = Video.query.get_or_404(id)
    
    if video.author_id != current_user.id:
        flash('Acesso negado.', 'danger')
        return redirect(url_for('professor_videos'))
    
    video.title = request.form.get('title')
    video.description = request.form.get('description')
    video.video_url = request.form.get('video_url')
    video.category = request.form.get('category')
    video.difficulty = request.form.get('difficulty')
    
    db.session.commit()
    flash('Videoaula atualizada com sucesso!', 'success')
    return redirect(url_for('professor_videos'))

# Rota para professor fazer download de submissão do aluno
@app.route('/professor/submissions/<int:submission_id>/download')
@login_required
@professor_required
def professor_download_submission(submission_id):
    submission = TaskSubmission.query.get_or_404(submission_id)
    if submission.file_path:
        # Verificar se o arquivo existe
        if os.path.exists(submission.file_path):
            directory = os.path.dirname(submission.file_path)
            filename = os.path.basename(submission.file_path)
            # Tentar obter o nome original do arquivo (removendo prefixos)
            parts = filename.split('_')
            if len(parts) >= 4:
                original_name = '_'.join(parts[3:])  # Pegar tudo depois do timestamp
            else:
                original_name = filename
            return send_from_directory(directory, filename, as_attachment=True, download_name=original_name)
        else:
            flash('O arquivo nao foi encontrado no servidor.', 'danger')
    else:
        flash('Nenhum arquivo anexado a esta submissao.', 'warning')
    return redirect(url_for('view_task_submissions', task_id=submission.task_id))

# Rota para professor corrigir submissão (via form do modal)
@app.route('/professor/grade-submission', methods=['POST'])
@login_required
@professor_required
def professor_grade_submission():
    submission_id = request.form.get('submission_id')
    submission = TaskSubmission.query.get_or_404(submission_id)
    
    grade = request.form.get('grade')
    feedback = request.form.get('feedback')
    
    # Validar score baseado no tipo da tarefa
    if grade:
        score = float(grade)
        task_type = submission.task.task_type or 'normal'
        max_allowed = 1000 if task_type == 'redacao' else 10
        score = min(max(0, score), max_allowed)
        submission.score = score
    else:
        submission.score = None
    submission.feedback = feedback
    submission.graded_at = datetime.utcnow()
    
    # Criar notificação para o aluno
    create_notification(
        submission.student_id,
        'Tarefa Corrigida',
        f'Sua tarefa "{submission.task.title}" foi corrigida. Nota: {submission.score}',
        'grade',
        submission.task_id
    )
    
    db.session.commit()
    flash('Correção salva com sucesso!', 'success')
    return redirect(url_for('view_task_submissions', task_id=submission.task_id))

# ============== ROTAS COMPLETAS DO ALUNO ==============

@app.route('/student/dashboard')
@login_required
@student_required
def student_dashboard():
    # Estatísticas do aluno
    total_videos = Video.query.filter_by(active=True).count()
    total_materials = Material.query.count()
    
    # Tarefas
    all_tasks = Task.query.all()
    submitted_task_ids = [s.task_id for s in TaskSubmission.query.filter_by(student_id=current_user.id).all()]
    pending_tasks = [t for t in all_tasks if t.id not in submitted_task_ids and t.due_date >= datetime.utcnow()]
    
    # Notas - calcular media usando percentual normalizado
    graded_submissions = TaskSubmission.query.filter(
        TaskSubmission.student_id == current_user.id,
        TaskSubmission.score.isnot(None)
    ).all()
    
    average_grade = 0
    if graded_submissions:
        # Calcular media usando score_percentage para normalizar notas de 0-10 e 0-1000
        percentages = [s.score_percentage for s in graded_submissions if s.score_percentage is not None]
        if percentages:
            average_grade = sum(percentages) / len(percentages)  # Media em percentual (0-100)
    
    stats = {
        'total_videos': total_videos,
        'total_materials': total_materials,
        'pending_tasks': len(pending_tasks),
        'average_grade': average_grade
    }
    
    # Notificações não lidas
    notifications_count = Notification.query.filter_by(user_id=current_user.id, read=False).count()
    
    # Tarefas pendentes (próximas 5)
    pending_tasks_list = Task.query.filter(
        Task.id.notin_(submitted_task_ids),
        Task.due_date >= datetime.utcnow()
    ).order_by(Task.due_date.asc()).limit(5).all()
    
    # Últimos vídeos
    recent_videos = Video.query.filter_by(active=True).order_by(Video.created_at.desc()).limit(4).all()
    
    # Últimos materiais
    recent_materials = Material.query.order_by(Material.created_at.desc()).limit(4).all()
    
    # Últimas notas
    recent_grades = TaskSubmission.query.filter(
        TaskSubmission.student_id == current_user.id,
        TaskSubmission.score.isnot(None)
    ).order_by(TaskSubmission.updated_at.desc()).limit(4).all()
    
    return render_template('student/dashboard.html',
        stats=stats,
        notifications_count=notifications_count,
        pending_tasks=pending_tasks_list,
        recent_videos=recent_videos,
        recent_materials=recent_materials,
        recent_grades=recent_grades,
        now=datetime.utcnow()
    )

@app.route('/student/videos')
@login_required
@student_required
def student_videos():
    videos = Video.query.filter_by(active=True).order_by(Video.created_at.desc()).all()
    categories = list(set([v.category for v in videos if v.category]))
    return render_template('student/videos.html', videos=videos, categories=categories)

@app.route('/student/videos/<int:video_id>')
@login_required
@student_required
def student_watch_video(video_id):
    video = Video.query.get_or_404(video_id)
    if not video.active:
        flash('Esta videoaula não está disponível.', 'warning')
        return redirect(url_for('student_videos'))
    
    video.views = (video.views or 0) + 1
    db.session.commit()
    
    comments = Comment.query.filter_by(video_id=video_id).order_by(Comment.created_at.asc()).all()
    return render_template('student/watch_video.html', video=video, comments=comments)

@app.route('/student/videos/<int:video_id>/comment', methods=['POST'])
@login_required
@student_required
def student_add_comment(video_id):
    video = Video.query.get_or_404(video_id)
    content = request.form.get('content')
    
    if content:
        comment = Comment(
            content=content,
            video_id=video_id,
            user_id=current_user.id
        )
        db.session.add(comment)
        db.session.commit()
        flash('Comentário adicionado!', 'success')
    
    return redirect(url_for('student_watch_video', video_id=video_id))

@app.route('/student/materials')
@login_required
@student_required
def student_materials():
    materials = Material.query.order_by(Material.created_at.desc()).all()
    categories = list(set([m.category for m in materials if m.category]))
    return render_template('student/materials.html', materials=materials, categories=categories)

@app.route('/student/materials/<int:material_id>/download')
@login_required
@student_required
def student_download_material(material_id):
    material = Material.query.get_or_404(material_id)
    if material.file_url:
        # Se for um caminho local
        if material.file_url.startswith('/static/uploads/'):
            filename = os.path.basename(material.file_url)
            return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)
        # Se for URL externa, redirecionar
        return redirect(material.file_url)
    flash('Arquivo não encontrado.', 'warning')
    return redirect(url_for('student_materials'))

@app.route('/student/materials/<int:material_id>/view')
@login_required
@student_required
def student_view_material(material_id):
    material = Material.query.get_or_404(material_id)
    if material.file_url:
        if material.file_url.startswith('/static/uploads/'):
            filename = os.path.basename(material.file_url)
            return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
        return redirect(material.file_url)
    flash('Arquivo não encontrado.', 'warning')
    return redirect(url_for('student_materials'))

@app.route('/student/tasks')
@login_required
@student_required
def student_tasks():
    all_tasks = Task.query.all()
    my_submissions = TaskSubmission.query.filter_by(student_id=current_user.id).all()
    submitted_task_ids = [s.task_id for s in my_submissions]
    
    now = datetime.utcnow()
    
    # Categorizar tarefas
    pending_tasks = []
    overdue_tasks = []
    submitted_tasks = []
    graded_tasks = []
    
    for task in all_tasks:
        submission = next((s for s in my_submissions if s.task_id == task.id), None)
        
        if submission:
            if submission.score is not None:
                graded_tasks.append(submission)
            else:
                submitted_tasks.append(submission)
        else:
            if task.due_date and task.due_date < now:
                overdue_tasks.append(task)
            else:
                pending_tasks.append(task)
    
    # Ordenar por data
    pending_tasks.sort(key=lambda x: x.due_date or datetime.max)
    overdue_tasks.sort(key=lambda x: x.due_date or datetime.max, reverse=True)
    
    return render_template('student/tasks.html',
        pending_tasks=pending_tasks,
        submitted_tasks=submitted_tasks,
        graded_tasks=graded_tasks,
        overdue_tasks=overdue_tasks,
        pending_count=len(pending_tasks),
        submitted_count=len(submitted_tasks),
        graded_count=len(graded_tasks),
        overdue_count=len(overdue_tasks)
    )

@app.route('/student/tasks/<int:task_id>')
@login_required
@student_required
def student_task_detail(task_id):
    task = Task.query.get_or_404(task_id)
    existing_submission = TaskSubmission.query.filter_by(
        task_id=task_id, 
        student_id=current_user.id
    ).first()
    
    return render_template('student/task_detail.html',
        task=task,
        existing_submission=existing_submission
    )

@app.route('/student/tasks/<int:task_id>/submit', methods=['POST'])
@login_required
@student_required
def student_submit_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    # Verificar se já enviou
    existing = TaskSubmission.query.filter_by(task_id=task_id, student_id=current_user.id).first()
    if existing:
        flash('Você já enviou esta tarefa.', 'warning')
        return redirect(url_for('student_tasks'))
    
    content = request.form.get('content', '').strip()
    file_path = None
    is_late = task.due_date and datetime.utcnow() > task.due_date
    
    # Handle file upload
    if 'file' in request.files:
        file = request.files['file']
        if file and file.filename:
            # Validar extensao do arquivo
            if not allowed_file(file.filename):
                flash('Tipo de arquivo nao permitido. Use: PDF, DOC, DOCX, TXT, imagens, ZIP, RAR.', 'danger')
                return redirect(url_for('student_task_detail', task_id=task_id))
            
            try:
                # Criar nome seguro para o arquivo
                original_filename = secure_filename(file.filename)
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                filename = f"{current_user.id}_{task_id}_{timestamp}_{original_filename}"
                
                upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'submissions')
                os.makedirs(upload_dir, exist_ok=True)
                filepath = os.path.join(upload_dir, filename)
                
                file.save(filepath)
                
                # Verificar se o arquivo foi salvo corretamente
                if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                    file_path = filepath
                else:
                    flash('Erro ao salvar arquivo. Tente novamente.', 'danger')
                    return redirect(url_for('student_task_detail', task_id=task_id))
            except Exception as e:
                flash(f'Erro ao processar arquivo: {str(e)}', 'danger')
                return redirect(url_for('student_task_detail', task_id=task_id))
    
    # Verificar se pelo menos um dos campos foi preenchido
    if not content and not file_path:
        flash('Envie pelo menos uma resposta em texto ou um arquivo.', 'warning')
        return redirect(url_for('student_task_detail', task_id=task_id))
    
    submission = TaskSubmission(
        task_id=task_id,
        student_id=current_user.id,
        content=content,
        file_path=file_path,
        is_late=is_late
    )
    db.session.add(submission)
    
    # Notificar professor
    professor = User.query.filter_by(role='professor').first()
    if professor:
        create_notification(
            professor.id,
            'Nova Submissão de Tarefa',
            f'{current_user.name} enviou a tarefa "{task.title}"',
            'task',
            task_id
        )
    
    db.session.commit()
    flash('Tarefa enviada com sucesso!', 'success')
    return redirect(url_for('student_tasks'))

@app.route('/student/submissions/<int:submission_id>')
@login_required
@student_required
def student_submission_detail(submission_id):
    submission = TaskSubmission.query.get_or_404(submission_id)
    
    if submission.student_id != current_user.id:
        flash('Acesso negado.', 'danger')
        return redirect(url_for('student_tasks'))
    
    return render_template('student/submission_detail.html', submission=submission)

@app.route('/student/submissions/<int:submission_id>/download')
@login_required
@student_required
def student_download_submission(submission_id):
    submission = TaskSubmission.query.get_or_404(submission_id)
    
    if submission.student_id != current_user.id:
        flash('Acesso negado.', 'danger')
        return redirect(url_for('student_tasks'))
    
    if submission.file_path and os.path.exists(submission.file_path):
        directory = os.path.dirname(submission.file_path)
        filename = os.path.basename(submission.file_path)
        # Tentar obter o nome original do arquivo (removendo prefixos)
        parts = filename.split('_')
        if len(parts) >= 4:
            original_name = '_'.join(parts[3:])  # Pegar tudo depois do timestamp
        else:
            original_name = filename
        return send_from_directory(directory, filename, as_attachment=True, download_name=original_name)
    
    flash('Arquivo nao encontrado.', 'warning')
    return redirect(url_for('student_submission_detail', submission_id=submission_id))

@app.route('/student/grades')
@login_required
@student_required
def student_grades():
    all_grades = TaskSubmission.query.filter(
        TaskSubmission.student_id == current_user.id,
        TaskSubmission.score.isnot(None)
    ).order_by(TaskSubmission.updated_at.desc()).all()
    
    # Separar por tipo de tarefa
    normal_grades = [g for g in all_grades if (g.task.task_type or 'normal') == 'normal']
    redacao_grades = [g for g in all_grades if (g.task.task_type or 'normal') == 'redacao']
    
    # Estatísticas gerais
    stats = {
        'graded_count': len(all_grades),
        'average_grade': 0,
        'highest_grade': 0,
        'lowest_grade': 0
    }
    
    # Estatísticas de atividades normais (0-10)
    normal_stats = {
        'graded_count': len(normal_grades),
        'average_grade': 0,
        'highest_grade': 0,
        'lowest_grade': 0
    }
    
    # Estatísticas de redações (0-1000)
    redacao_stats = {
        'graded_count': len(redacao_grades),
        'average_grade': 0,
        'highest_grade': 0,
        'lowest_grade': 0
    }
    
    if all_grades:
        scores = [g.score for g in all_grades]
        stats['average_grade'] = sum(scores) / len(scores)
        stats['highest_grade'] = max(scores)
        stats['lowest_grade'] = min(scores)
    
    if normal_grades:
        normal_scores = [g.score for g in normal_grades]
        normal_stats['average_grade'] = sum(normal_scores) / len(normal_scores)
        normal_stats['highest_grade'] = max(normal_scores)
        normal_stats['lowest_grade'] = min(normal_scores)
    
    if redacao_grades:
        redacao_scores = [g.score for g in redacao_grades]
        redacao_stats['average_grade'] = sum(redacao_scores) / len(redacao_scores)
        redacao_stats['highest_grade'] = max(redacao_scores)
        redacao_stats['lowest_grade'] = min(redacao_scores)
    
    return render_template('student/grades.html', 
                          grades=all_grades,
                          normal_grades=normal_grades,
                          redacao_grades=redacao_grades,
                          stats=stats,
                          normal_stats=normal_stats,
                          redacao_stats=redacao_stats)

@app.route('/student/profile')
@login_required
@student_required
def student_profile():
    # Estatísticas do aluno
    submitted_count = TaskSubmission.query.filter_by(student_id=current_user.id).count()
    graded = TaskSubmission.query.filter(
        TaskSubmission.student_id == current_user.id,
        TaskSubmission.score.isnot(None)
    ).all()
    
    average_grade = 0
    if graded:
        average_grade = sum(s.score for s in graded) / len(graded)
    
    days_active = 0
    if current_user.created_at:
        days_active = (datetime.utcnow() - current_user.created_at).days
    
    stats = {
        'submitted_tasks': submitted_count,
        'average_grade': average_grade,
        'days_active': days_active
    }
    
    return render_template('student/profile.html', stats=stats)

@app.route('/student/profile/update', methods=['POST'])
@login_required
@student_required
def student_update_profile():
    current_user.name = request.form.get('name')
    current_user.email = request.form.get('email')
    current_user.phone = request.form.get('phone')
    
    db.session.commit()
    flash('Perfil atualizado com sucesso!', 'success')
    return redirect(url_for('student_profile'))

@app.route('/student/profile/change-password', methods=['POST'])
@login_required
@student_required
def student_change_password():
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    if not current_user.check_password(current_password):
        flash('Senha atual incorreta.', 'danger')
        return redirect(url_for('student_profile'))
    
    if new_password != confirm_password:
        flash('As senhas não coincidem.', 'danger')
        return redirect(url_for('student_profile'))
    
    if len(new_password) < 6:
        flash('A nova senha deve ter pelo menos 6 caracteres.', 'danger')
        return redirect(url_for('student_profile'))
    
    current_user.set_password(new_password)
    db.session.commit()
    flash('Senha alterada com sucesso!', 'success')
    return redirect(url_for('student_profile'))

@app.route('/student/chat')
@login_required
@student_required
def student_chat():
    professor = User.query.filter_by(role='professor').first()
    
    if not professor:
        flash('Professor não encontrado.', 'warning')
        return redirect(url_for('student_dashboard'))
    
    messages = Message.query.filter(
        ((Message.from_user_id == current_user.id) & (Message.to_user_id == professor.id)) |
        ((Message.from_user_id == professor.id) & (Message.to_user_id == current_user.id))
    ).order_by(Message.created_at.asc()).all()
    
    # Marcar mensagens como lidas
    Message.query.filter_by(
        from_user_id=professor.id,
        to_user_id=current_user.id,
        read=False
    ).update({'read': True})
    db.session.commit()
    
    return render_template('student/chat.html', 
                          messages=messages, 
                          professor=professor,
                          timedelta=timedelta,
                          now=datetime.utcnow())

@app.route('/student/send-message', methods=['POST'])
@login_required
@student_required
def student_send_message():
    professor = User.query.filter_by(role='professor').first()
    content = request.form.get('content')
    
    if content and professor:
        message = Message(
            content=content,
            from_user_id=current_user.id,
            to_user_id=professor.id
        )
        db.session.add(message)
        db.session.commit()
    
    return redirect(url_for('student_chat'))

@app.route('/student/professor')
@login_required
@student_required
def student_professor():
    professor = User.query.filter_by(role='professor').first()
    
    if not professor:
        flash('Professor não encontrado.', 'warning')
        return redirect(url_for('student_dashboard'))
    
    # Estatísticas do professor
    stats = {
        'total_videos': Video.query.filter_by(author_id=professor.id, active=True).count(),
        'total_materials': Material.query.filter_by(author_id=professor.id).count(),
        'total_tasks': Task.query.filter_by(author_id=professor.id).count(),
        'total_students': User.query.filter_by(role='student', is_active=True).count()
    }
    
    return render_template('student/professor.html', professor=professor, stats=stats)

# Rota para professor ver detalhes de um video com comentarios
@app.route('/professor/videos/<int:video_id>')
@login_required
@professor_required
def professor_video_detail(video_id):
    video = Video.query.get_or_404(video_id)
    comments = Comment.query.filter_by(video_id=video_id).order_by(Comment.created_at.asc()).all()
    return render_template('professor/video_detail.html', video=video, comments=comments)

# Rota para professor adicionar comentario em video
@app.route('/professor/videos/<int:video_id>/comment', methods=['POST'])
@login_required
@professor_required
def professor_add_comment(video_id):
    video = Video.query.get_or_404(video_id)
    content = request.form.get('content')
    
    if content:
        comment = Comment(
            content=content,
            video_id=video_id,
            user_id=current_user.id
        )
        db.session.add(comment)
        db.session.commit()
        flash('Comentário adicionado!', 'success')
    
    return redirect(url_for('professor_video_detail', video_id=video_id))

# Rota para professor apagar comentario
@app.route('/professor/comments/<int:comment_id>/delete', methods=['POST'])
@login_required
@professor_required
def professor_delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    video_id = comment.video_id
    
    db.session.delete(comment)
    db.session.commit()
    flash('Comentário excluído!', 'success')
    
    return redirect(url_for('professor_video_detail', video_id=video_id))

@app.route('/tasks/<int:task_id>/attachment')
@login_required
def download_task_attachment(task_id):
    task = Task.query.get_or_404(task_id)
    if task.attachment and os.path.exists(task.attachment):
        directory = os.path.dirname(task.attachment)
        filename = os.path.basename(task.attachment)
        return send_from_directory(directory, filename, as_attachment=True)
    flash('Anexo não encontrado.', 'warning')
    return redirect(request.referrer or url_for('index'))

# Static files
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Rota para resetar o banco de dados (apenas para desenvolvimento)
@app.route('/reset-db')
def reset_database():
    if not app.debug:
        flash('Esta rota está disponível apenas em modo debug.', 'danger')
        return redirect(url_for('index'))
    
    # Remover o arquivo do banco de dados
    db_path = os.path.join(instance_path, "mancera.db")
    if os.path.exists(db_path):
        os.remove(db_path)
        flash('Banco de dados removido. Reinicie o servidor para recriá-lo.', 'success')
    else:
        flash('Banco de dados não encontrado.', 'warning')
    
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)