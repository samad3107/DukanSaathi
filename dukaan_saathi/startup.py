import os

from django.core.management import call_command


def prepare_vercel_database():
    if not (os.getenv("VERCEL") or os.getenv("VERCEL_ENV") or os.path.exists("/var/task")):
        return
    if os.getenv("DATABASE_URL"):
        return
    call_command("migrate", interactive=False, verbosity=0)