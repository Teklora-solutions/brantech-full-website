from django.urls import path
from . import views

app_name = 'library'
urlpatterns = [
    path('', views.index, name='index'),
    path('upload/', views.upload, name='upload'),
    path('review/', views.review_queue, name='review'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/download/', views.download, name='download'),
    path('<int:pk>/actions/<slug:action>/', views.action, name='action'),
]
