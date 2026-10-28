"""Operator command: run the cleaning pipeline and register sources, datasets, versions and quality reports.

Data are imported ONLY through this server-side command (the public site has no upload endpoint because it has no
authentication).  Place new raw files in data/raw/, register them in config/source_register.json, then run this."""
from django.core.management.base import BaseCommand, CommandError

from portal import services as S


class Command(BaseCommand):
    help = "Run the data pipeline (validate, clean, document) and record dataset versions in the database."

    def handle(self, *args, **opts):
        job = S.import_all_datasets()
        if job.status != "succeeded":
            raise CommandError(f"Import failed: {job.error}")
        self.stdout.write(self.style.SUCCESS(f"Import job {job.pk} succeeded: {job.summary}"))
