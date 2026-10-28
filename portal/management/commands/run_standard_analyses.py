"""Operator command: (re)compute the standard inequality, causal and simulation analyses shown on the public pages."""
from django.core.management.base import BaseCommand, CommandError

from portal import services as S


class Command(BaseCommand):
    help = "Run the standard analyses (idempotent: identical config + data reuse the stored run)."

    def handle(self, *args, **opts):
        out = S.run_standard_analyses()
        runs = [out["inequality"], out["causal"], *out["simulations"]]
        for r in runs:
            r.refresh_from_db()
            self.stdout.write(f"{r.analysis_type:11s} {r.status:10s} {r.public_id} {r.label}")
        if any(r.status != "succeeded" for r in runs):
            raise CommandError("At least one standard analysis failed; see the run pages for the error.")
