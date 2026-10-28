from django.conf import settings

NAV = [("home", "Home"), ("dashboard", "Dashboard"), ("inequality", "Inequality"), ("data_home", "Data"),
       ("causal", "Causal analysis"), ("simulate", "Policy simulator"), ("reports", "Reports"), ("methodology", "Methodology")]


def site(request):
    return {"NAV": NAV, "SITE_TITLE": "Educational Inequality in Nigeria", "DEBUG": settings.DEBUG}
