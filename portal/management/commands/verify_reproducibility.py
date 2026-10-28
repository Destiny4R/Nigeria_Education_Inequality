"""Re-run the standard analyses from the raw files and confirm that the result hashes are identical (plan 11.3 reproducibility)."""
import json

from django.core.management.base import BaseCommand, CommandError

from portal import services as S
from src.cleaning.pipeline import run_cleaning
from src.common import PROCESSED


class Command(BaseCommand):
    help = "Re-run cleaning + analyses from raw data and compare checksums with the stored results."

    def handle(self, *args, **opts):
        before = json.loads((PROCESSED / "quality_report.json").read_text())["analytic_sha256"] if (PROCESSED / "quality_report.json").exists() else None
        run_cleaning(write=True)
        after = json.loads((PROCESSED / "quality_report.json").read_text())["analytic_sha256"]
        self.stdout.write(f"analytic dataset checksum before={before} after={after}")
        if before and before != after:
            raise CommandError("Cleaning is NOT reproducible: analytic dataset checksum changed")
        mismatches = []
        for kind in ("inequality", "causal"):
            stored = S.latest_default(kind)
            if not stored:
                continue
            res = S._compute(kind, stored.config)
            ok = res.get("results_sha256") == stored.results_sha256
            self.stdout.write(f"{kind}: stored={stored.results_sha256[:16]} recomputed={res.get('results_sha256', '')[:16]} {'OK' if ok else 'MISMATCH'}")
            if not ok:
                mismatches.append(kind)
        if mismatches:
            raise CommandError("Not reproducible: " + ", ".join(mismatches))
        self.stdout.write(self.style.SUCCESS("Reproducibility verified"))
