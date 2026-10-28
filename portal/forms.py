from django import forms

from src.inequality import metrics as M
from src.inequality.analysis import LEVELS
from src.simulation.engine import INTERVENTIONS, COVERAGE_KINDS, EFFECT_MODELS

OUTCOME_CHOICES = [("oos_total_2021", "Primary OOS rate, all children (primary outcome)"), ("oos_male_2021", "Primary OOS rate, boys"), ("oos_female_2021", "Primary OOS rate, girls")]
CONFOUNDER_CHOICES = [("pov_215,north", "Poverty (2018) + region (recommended)"), ("north", "Region only (drops poverty)"), ("pov_215", "Poverty only")]


class InequalityFilterForm(forms.Form):
    indicator = forms.ChoiceField(choices=[(k, v["label"]) for k, v in M.INDICATORS.items()], initial="oos_total_2021")
    region = forms.ChoiceField(choices=[("All", "All regions"), ("North", "North"), ("South", "South")], required=False, initial="All")
    zone = forms.ChoiceField(choices=[("All", "All zones")] + [(z, z) for z in ("NC", "NE", "NW", "SE", "SS", "SW")], required=False, initial="All")
    poverty_group = forms.ChoiceField(choices=[("All", "All")] + [(g, g) for g in ("Low poverty", "Middle poverty", "High poverty")], required=False, initial="All")
    level = forms.ChoiceField(choices=list(LEVELS.items()), required=False, initial="oos_primary")
    states = forms.MultipleChoiceField(required=False, choices=[])

    def __init__(self, *a, state_choices=(), **kw):
        super().__init__(*a, **kw)
        self.fields["states"].choices = [(s, s) for s in state_choices]

    def config(self) -> dict:
        d = self.cleaned_data
        return {"indicator": d["indicator"], "region": d.get("region") or "All", "zone": d.get("zone") or "All", "poverty_group": d.get("poverty_group") or "All",
                "level": d.get("level") or "oos_primary", "states": d.get("states") or []}


class CausalRunForm(forms.Form):
    outcome = forms.ChoiceField(choices=OUTCOME_CHOICES, initial="oos_total_2021")
    confounders = forms.ChoiceField(choices=CONFOUNDER_CHOICES, initial="pov_215,north")
    quick = forms.BooleanField(required=False, initial=True, label="Quick settings (fewer bootstrap / refutation / DML repeats; about 15 s instead of about 1 min)")

    def config(self) -> dict:
        d = self.cleaned_data
        c = {"outcome": d["outcome"], "confounders": d["confounders"].split(",")}
        if d.get("quick"):
            c.update({"n_boot": 300, "n_refute": 30, "dml_repeats": 3})
        return c


class ScenarioForm(forms.Form):
    name = forms.CharField(max_length=120, initial="My scenario")
    description = forms.CharField(max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 2}))
    intervention = forms.ChoiceField(choices=list(INTERVENTIONS.items()), initial="pct_reduction")
    value = forms.FloatField(min_value=0.1, max_value=1000, initial=20, help_text="Percent reduction (0-100) or the PQTR cap in pupils per qualified teacher")
    coverage = forms.ChoiceField(choices=list(COVERAGE_KINDS.items()), initial="all")
    region = forms.ChoiceField(choices=[("North", "North"), ("South", "South")], required=False)
    poverty_min = forms.FloatField(required=False, min_value=0, max_value=100, label="Poverty headcount threshold (%)")
    states = forms.MultipleChoiceField(required=False, choices=[])
    effect_model = forms.ChoiceField(choices=list(EFFECT_MODELS.items()), initial="pooled_adjusted")
    fidelity_low = forms.FloatField(min_value=0, max_value=1, initial=0.5, label="Implementation fidelity - low")
    fidelity_high = forms.FloatField(min_value=0, max_value=1, initial=1.0, label="Implementation fidelity - high")
    n_draws = forms.ChoiceField(choices=[(1000, "1,000"), (2000, "2,000"), (4000, "4,000")], initial=2000, label="Uncertainty draws")

    def __init__(self, *a, state_choices=(), **kw):
        super().__init__(*a, **kw)
        self.fields["states"].choices = [(s, s) for s in state_choices]

    def clean(self):
        c = super().clean()
        cov = c.get("coverage")
        if cov == "region" and not c.get("region"):
            self.add_error("region", "Choose a region")
        if cov == "poverty_min" and c.get("poverty_min") is None:
            self.add_error("poverty_min", "Enter a threshold")
        if cov == "states" and not c.get("states"):
            self.add_error("states", "Choose at least one state")
        if c.get("fidelity_low") is not None and c.get("fidelity_high") is not None and c["fidelity_low"] > c["fidelity_high"]:
            self.add_error("fidelity_high", "High must be at least the low value")
        if c.get("intervention") == "pct_reduction" and c.get("value") is not None and not (0 < c["value"] < 100):
            self.add_error("value", "A percentage reduction must be between 0 and 100")
        return c

    def config(self) -> dict:
        d = self.cleaned_data
        cov = d["coverage"]
        cv = {"all": None, "region": d.get("region"), "poverty_min": d.get("poverty_min"), "states": d.get("states")}[cov]
        return {"name": d["name"].strip(), "description": d.get("description", ""), "intervention": d["intervention"], "value": d["value"], "coverage": cov, "coverage_value": cv,
                "effect_model": d["effect_model"], "fidelity_low": d["fidelity_low"], "fidelity_high": d["fidelity_high"], "n_draws": int(d["n_draws"])}
