"""Relational schema (plan 6.2), adapted to an open-access system.

Differences from the plan, by project decision: there are NO User / Role / Permission entities because the
system has no authentication.  ``AuditLog`` records anonymous activity (a salted hash of the client address,
never the address itself).
"""
import uuid

from django.db import models
from django.db.models import Q


class DataSource(models.Model):
    source_id = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=300)
    publisher = models.CharField(max_length=300, blank=True)
    url = models.URLField(max_length=500)
    publication_year = models.PositiveSmallIntegerField(null=True, blank=True)
    collection_period = models.CharField(max_length=120, blank=True)
    access_date = models.DateField()
    geographic_coverage = models.CharField(max_length=200, blank=True)
    licence = models.CharField(max_length=300)
    documentation = models.TextField(blank=True)
    limitations = models.TextField()
    permitted_uses = models.TextField()
    retrieval_method = models.TextField(blank=True)

    class Meta:
        ordering = ["source_id"]

    def __str__(self):
        return self.source_id


class Dataset(models.Model):
    dataset_id = models.CharField(max_length=60, unique=True)
    name = models.CharField(max_length=300)
    source = models.ForeignKey(DataSource, on_delete=models.PROTECT, related_name="datasets")
    unit_of_analysis = models.CharField(max_length=120)
    role = models.CharField(max_length=200, blank=True)
    raw_file = models.CharField(max_length=300)

    class Meta:
        ordering = ["dataset_id"]

    def __str__(self):
        return self.dataset_id


class DatasetVersion(models.Model):
    READINESS = [("Approved", "Approved"), ("Approved with limitations", "Approved with limitations"), ("Rejected", "Rejected")]
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    n_rows = models.PositiveIntegerField()
    size_bytes = models.PositiveIntegerField()
    readiness = models.CharField(max_length=30, choices=READINESS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["dataset__dataset_id", "-version"]
        constraints = [models.UniqueConstraint(fields=["dataset", "version"], name="uniq_dataset_version"),
                       models.UniqueConstraint(fields=["dataset", "sha256"], name="uniq_dataset_checksum")]


class DataQualityReport(models.Model):
    version = models.OneToOneField(DatasetVersion, on_delete=models.CASCADE, related_name="quality_report")
    readiness_reasons = models.JSONField(default=list)
    readiness_detail = models.JSONField(default=dict)
    checks = models.JSONField(default=list)
    transformations = models.JSONField(default=list)
    missingness = models.JSONField(default=dict)
    rejected_columns = models.JSONField(default=dict)
    flags = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class ImportJob(models.Model):
    STATUS = [("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed")]
    status = models.CharField(max_length=12, choices=STATUS, default="running")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    summary = models.JSONField(default=dict)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]


class IndicatorDefinition(models.Model):
    code = models.CharField(max_length=60, unique=True)
    label = models.CharField(max_length=200)
    unit = models.CharField(max_length=80)
    direction = models.CharField(max_length=20)
    denominator = models.TextField()
    weighting = models.TextField()
    missing_rule = models.TextField()
    source_id = models.CharField(max_length=40)
    comparable = models.BooleanField(default=True)
    interpretation = models.TextField()

    class Meta:
        ordering = ["code"]


class AnalysisRun(models.Model):
    TYPES = [("inequality", "Inequality analysis"), ("causal", "Causal analysis"), ("simulation", "Policy simulation")]
    STATUS = [("queued", "Queued"), ("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed")]
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    analysis_type = models.CharField(max_length=12, choices=TYPES)
    status = models.CharField(max_length=10, choices=STATUS, default="queued")
    config = models.JSONField(default=dict)
    config_hash = models.CharField(max_length=64)
    data_sha256 = models.CharField(max_length=64)
    results = models.JSONField(null=True, blank=True)       # set ONLY when status == succeeded
    results_sha256 = models.CharField(max_length=64, blank=True)
    artefact_path = models.CharField(max_length=300, blank=True)
    software_versions = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    retries = models.PositiveSmallIntegerField(default=0)
    progress = models.CharField(max_length=200, blank=True)
    label = models.CharField(max_length=200, blank=True)
    is_default = models.BooleanField(default=False, help_text="Standard analysis shown on the public pages")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["analysis_type", "config_hash", "data_sha256"]), models.Index(fields=["status", "created_at"])]
        constraints = [
            # a failed / unfinished run can never carry results (plan 10.2: no incomplete results marked successful)
            models.CheckConstraint(condition=Q(status="succeeded") | Q(results__isnull=True), name="results_only_if_succeeded"),
        ]

    @property
    def duration(self):
        return (self.finished_at - self.started_at).total_seconds() if self.finished_at and self.started_at else None

    def __str__(self):
        return f"{self.analysis_type}:{self.public_id}"


class InequalityResult(models.Model):
    run = models.ForeignKey(AnalysisRun, on_delete=models.CASCADE, related_name="inequality_results")
    indicator = models.CharField(max_length=60)
    group_type = models.CharField(max_length=30)
    group = models.CharField(max_length=80)
    metric = models.CharField(max_length=60)
    value = models.FloatField(null=True)
    ci_low = models.FloatField(null=True, blank=True)
    ci_high = models.FloatField(null=True, blank=True)
    n = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["run", "indicator", "metric"])]


class CausalModel(models.Model):
    run = models.OneToOneField(AnalysisRun, on_delete=models.CASCADE, related_name="causal_model")
    name = models.CharField(max_length=200)
    treatment = models.CharField(max_length=60)
    outcome = models.CharField(max_length=60)
    confounders = models.JSONField(default=list)
    estimand = models.TextField()
    graph = models.JSONField(default=dict)
    assumptions = models.JSONField(default=list)
    identification = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class ModelVersion(models.Model):
    causal_model = models.ForeignKey(CausalModel, on_delete=models.CASCADE, related_name="versions")
    version = models.CharField(max_length=40)
    software_versions = models.JSONField(default=dict)
    artefact_path = models.CharField(max_length=300)
    artefact_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)


class ValidationRun(models.Model):
    KINDS = [("refutation", "Refutation tests"), ("sensitivity", "Sensitivity to unmeasured confounding"), ("robustness", "Robustness checks"),
             ("predictive", "Predictive validation"), ("overlap", "Overlap and balance")]
    model_version = models.ForeignKey(ModelVersion, on_delete=models.CASCADE, related_name="validations")
    kind = models.CharField(max_length=20, choices=KINDS)
    summary = models.JSONField(default=dict)
    passed = models.BooleanField(null=True, help_text="Null = informational (no pass/fail criterion)")
    created_at = models.DateTimeField(auto_now_add=True)


class PolicyScenario(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True)
    config = models.JSONField()
    config_hash = models.CharField(max_length=64, db_index=True)
    is_preset = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_preset", "-created_at"]


class SimulationRun(models.Model):
    scenario = models.ForeignKey(PolicyScenario, on_delete=models.CASCADE, related_name="simulations")
    run = models.OneToOneField(AnalysisRun, on_delete=models.CASCADE, related_name="simulation")
    created_at = models.DateTimeField(auto_now_add=True)


class SimulationResult(models.Model):
    simulation = models.ForeignKey(SimulationRun, on_delete=models.CASCADE, related_name="results")
    group_type = models.CharField(max_length=20)      # national | subgroup | state
    group = models.CharField(max_length=80)
    baseline = models.FloatField(null=True)
    counterfactual = models.FloatField(null=True)
    change_pp = models.FloatField(null=True)
    ci_low = models.FloatField(null=True, blank=True)
    ci_high = models.FloatField(null=True, blank=True)


class AuditLog(models.Model):
    action = models.CharField(max_length=60)
    object_type = models.CharField(max_length=40, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    details = models.JSONField(default=dict)
    client_hash = models.CharField(max_length=16, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["action", "created_at"])]
