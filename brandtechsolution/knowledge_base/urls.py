from django.urls import path
from . import views, embedding_views

app_name = 'library'
urlpatterns = [
    path('', views.index, name='index'),
    path('upload/', views.upload, name='upload'),
    path('review/', views.review_queue, name='review'),
    path('embeddings/', embedding_views.index, name='embeddings'),
    path('embeddings/control/', embedding_views.control, name='embedding-control'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/download/', views.download, name='download'),
    path('<int:pk>/preview/<int:version_id>/', views.preview, name='preview'),
    path('<int:pk>/actions/<slug:action>/', views.action, name='action'),
]
