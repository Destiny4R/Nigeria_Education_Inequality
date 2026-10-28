"""Operator command: generate the 9-combination causal analysis report as a DOCX file."""
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from portal.exports import causal_matrix_report_docx


class Command(BaseCommand):
    help = ("Generate the full 9-combination causal analysis report as a standalone DOCX file with all six portal charts "
            "embedded per section via kaleido (runs are ephemeral, settings n_boot=300, n_refute=30, dml_repeats=3; needs "
            "a local Chrome install because figure rendering goes through a headless browser).")

    def add_arguments(self, parser):
        parser.add_argument("--output", default="reports/causal_matrix_report.docx")

    def handle(self, *args, **opts):
        path = Path(opts["output"])
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        started = time.time()
        self.stdout.write(f"Running 9 causal analyses and rendering 54 chart screenshots - typically 20-30 minutes total. Writing to {path}")
        data = causal_matrix_report_docx(progress=lambda m: self.stdout.write(m))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.stdout.write(self.style.SUCCESS(f"Report saved to {path} ({len(data) / 1024:.0f} KB, {time.time() - started:.0f}s)"))
