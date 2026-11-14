from django.urls import path

from . import views


app_name = "kb"
urlpatterns = [
    path("", views.home, name="home"),
    path("disciplines/", views.discipline_home, name="disciplines"),
    path("services/<str:slug>/", views.service_home, name="service"),
    path("search/", views.search, name="search"),
    path("api/search/suggest/", views.suggest, name="suggest"),
    path("sections/<str:slug>/", views.section_detail, name="section"),
    path("articles/<str:slug>/", views.article_detail, name="article"),
    path("private/image/<int:pk>/", views.private_file, name="private_file"),
    path("private/attachment/<int:pk>/", views.private_attachment, name="private_attachment"),
    path("private/video/<int:pk>/", views.private_video, name="private_video"),
]
