
from django.urls import path
from . import views

urlpatterns = [
    path('', views.upload_view, name='upload_view'), # Changed home to upload_view
    path('preview/', views.preview_view, name='preview_view'),
    path('process/', views.process_view, name='process_view'), # New route for processing
    path('result/', views.result_view, name='result_view'), # New route for result
]
