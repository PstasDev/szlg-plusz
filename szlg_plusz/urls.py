from django.urls import path

from api.views import api

urlpatterns = [
    path("api/", api.urls),
]
