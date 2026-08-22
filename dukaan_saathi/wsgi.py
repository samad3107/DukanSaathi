"""
WSGI config for dukaan_saathi project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dukaan_saathi.settings')

application = get_wsgi_application()

from .startup import prepare_vercel_database

prepare_vercel_database()
