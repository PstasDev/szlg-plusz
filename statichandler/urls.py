from django.urls import re_path

from . import views

app_name = "statichandler"

urlpatterns = [
    re_path(r"^static/(?P<path>.*)$", views.serve_static, name="static"),
    re_path(r"^media/(?P<path>.*)$", views.serve_media, name="media"),
]
