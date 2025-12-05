from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

# Helper para calcular percentual normalizado de notas
def normalize_score(score, task_type):
    """Normaliza uma nota para percentual (0-100) baseado no tipo de tarefa"""
    if score is None:
        return None
    max_score = 1000 if task_type == 'redacao' else 10
    return (score / max_score) * 100

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='student')  # professor or student
    phone = db.Column(db.String(20))
    birth_date = db.Column(db.String(20))
    bio = db.Column(db.Text)
    profile_image = db.Column(db.String(200))
    subscription_end_date = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    videos = db.relationship('Video', backref='author', lazy=True, cascade='all, delete-orphan')
    materials = db.relationship('Material', backref='author', lazy=True, cascade='all, delete-orphan')
    tasks = db.relationship('Task', backref='author', lazy=True, cascade='all, delete-orphan')
    submissions = db.relationship('TaskSubmission', backref='student', lazy=True, cascade='all, delete-orphan')
    comments = db.relationship('Comment', backref='user', lazy=True, cascade='all, delete-orphan')
    sent_messages = db.relationship('Message', foreign_keys='Message.from_user_id', backref='sender', lazy=True, cascade='all, delete-orphan')
    received_messages = db.relationship('Message', foreign_keys='Message.to_user_id', backref='receiver', lazy=True, cascade='all, delete-orphan')
    notifications = db.relationship('Notification', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def is_subscription_expired(self):
        if self.role != 'student' or not self.subscription_end_date:
            return False
        return datetime.utcnow() > self.subscription_end_date
    
    # Alias for templates
    def is_expired(self):
        return self.is_subscription_expired()
    
    @property
    def subscription_end(self):
        return self.subscription_end_date
    
    def __repr__(self):
        return f'<User {self.email}>'

class Video(db.Model):
    __tablename__ = 'videos'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    video_url = db.Column(db.String(500))
    file_path = db.Column(db.String(500))
    keywords = db.Column(db.String(200))
    category = db.Column(db.String(100))
    difficulty = db.Column(db.String(20), default='medium')  # easy, medium, hard
    duration = db.Column(db.String(20))  # e.g., "10:30"
    active = db.Column(db.Boolean, default=True)
    views = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Relationships
    comments = db.relationship('Comment', backref='video', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Video {self.title}>'

class Material(db.Model):
    __tablename__ = 'materials'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    file_type = db.Column(db.String(50))  # PDF, Texto, Link, Imagem
    file_url = db.Column(db.String(500))
    content = db.Column(db.Text)
    category = db.Column(db.String(100))
    tags = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    @property
    def file_path(self):
        """Alias for file_url to maintain compatibility with templates"""
        return self.file_url or ''
    
    def __repr__(self):
        return f'<Material {self.title}>'

class Task(db.Model):
    __tablename__ = 'tasks'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    due_date = db.Column(db.DateTime, nullable=False)
    max_score = db.Column(db.Float, default=10)
    task_type = db.Column(db.String(20), default='normal')  # normal (0-10) or redacao (0-1000)
    status = db.Column(db.String(20), default='active')  # active, inactive
    attachment = db.Column(db.String(500))  # Path to attachment file
    allow_late_submission = db.Column(db.Boolean, default=True)
    external_link = db.Column(db.String(500))
    external_link_type = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Relationships
    submissions = db.relationship('TaskSubmission', backref='task', lazy=True, cascade='all, delete-orphan')
    
    @property
    def max_grade(self):
        """Alias for max_score to maintain compatibility with templates"""
        return self.max_score
    
    @property
    def professor(self):
        """Alias for author to maintain compatibility with templates"""
        return self.author
    
    def is_past_due(self):
        """Check if the task is past its due date"""
        if not self.due_date:
            return False
        return datetime.utcnow() > self.due_date
    
    def __repr__(self):
        return f'<Task {self.title}>'

class TaskSubmission(db.Model):
    __tablename__ = 'task_submissions'
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text)
    file_url = db.Column(db.String(500))
    file_path = db.Column(db.String(500))  # Path to uploaded file
    score = db.Column(db.Float)  # Changed to Float for decimal grades
    feedback = db.Column(db.Text)
    is_late = db.Column(db.Boolean, default=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    graded_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @property
    def grade(self):
        """Alias for score to maintain compatibility with templates"""
        return self.score
    
    @grade.setter
    def grade(self, value):
        """Setter for grade alias"""
        self.score = value
    
    @property
    def score_percentage(self):
        """Retorna a nota como percentual (0-100) normalizado pelo tipo de tarefa"""
        if self.score is None:
            return None
        task_type = self.task.task_type if self.task else 'normal'
        max_score = 1000 if task_type == 'redacao' else 10
        return (self.score / max_score) * 100
    
    @property
    def score_display(self):
        """Retorna a nota formatada para exibição"""
        if self.score is None:
            return 'N/A'
        task_type = self.task.task_type if self.task else 'normal'
        if task_type == 'redacao':
            return f'{int(self.score)}'
        return f'{self.score:.1f}'
    
    def __repr__(self):
        return f'<TaskSubmission {self.id}>'

class Comment(db.Model):
    __tablename__ = 'comments'
    
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Comment {self.id}>'

class Message(db.Model):
    __tablename__ = 'messages'
    
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    from_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    to_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    @property
    def sender_id(self):
        """Alias for from_user_id"""
        return self.from_user_id
    
    @property
    def is_read(self):
        """Alias for read"""
        return self.read
    
    @property
    def timestamp(self):
        """Alias for created_at - usado nos templates de chat"""
        return self.created_at
    
    def __repr__(self):
        return f'<Message {self.id}>'

class Notification(db.Model):
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), nullable=False)  # video, material, task, grade, message
    reference_id = db.Column(db.Integer)
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    @property
    def is_read(self):
        """Alias for read"""
        return self.read
    
    def __repr__(self):
        return f'<Notification {self.id}>'
