from django.core.management.base import BaseCommand

from core.services import expire_stale


class Command(BaseCommand):
    help = "Mark expired incidents stale and overdue blockages as needing re-confirmation. Run from cron every minute."

    def handle(self, *args, **options):
        n_inc, n_blk = expire_stale()
        self.stdout.write(self.style.SUCCESS(f"{n_inc} incident(s) → stale, {n_blk} blockage(s) → needs re-confirmation"))
