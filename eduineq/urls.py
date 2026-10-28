from django.urls import include, path

urlpatterns = [path("", include("portal.urls"))]

handler404 = "portal.views.not_found"
handler500 = "portal.views.server_error"
