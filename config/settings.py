import os
from pathlib import Path
BASE_DIR=Path(__file__).resolve().parents[1]
SECRET_KEY=os.environ.get('MOTOR_SECRET_KEY','local-synthetic-demo-not-a-production-secret')
DEBUG=os.environ.get('MOTOR_DEBUG','1')=='1'
ALLOWED_HOSTS=['127.0.0.1','localhost','testserver']
INSTALLED_APPS=['django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.staticfiles','app']
MIDDLEWARE=['django.middleware.security.SecurityMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','app.account_middleware.AccountSessionMiddleware']
ROOT_URLCONF='config.urls'
DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':os.environ.get('MOTOR_SQLITE_PATH',str(BASE_DIR/'data/platform.sqlite3')),'OPTIONS':{'timeout':30}}}
TEMPLATES=[{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request']}}]
STATIC_URL='/static/';STATICFILES_DIRS=[BASE_DIR/'static']
TIME_ZONE='Asia/Shanghai';USE_TZ=True;LANGUAGE_CODE='zh-hans'
DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'
DATA_UPLOAD_MAX_MEMORY_SIZE=60*1024*1024
FILE_UPLOAD_MAX_MEMORY_SIZE=2*1024*1024
CSRF_COOKIE_SAMESITE='Strict';SESSION_COOKIE_SAMESITE='Strict'
X_FRAME_OPTIONS='DENY'
# The demo collector reads only this generated local inbox, never Excel paths.
DEVICE_COLLECTION_ENABLED=DEBUG
DEVICE_COLLECTION_ROOT=BASE_DIR/'data/device_inbox'
DEVICE_COLLECTION_SOURCES={'DS-PC-2026-001','DS-PC-2026-002'}
DEVICE_COLLECTION_STABLE_SECONDS=2
