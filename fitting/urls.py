
from django.urls import path
from . import views

urlpatterns = [
    # Home
    path('', views.home, name='home'),

    # Clothing try-on
    path('clothes/upload/', views.upload_view, name='upload_view'),
    path('clothes/preview/', views.preview_view, name='preview_view'),
    path('clothes/process/', views.process_view, name='process_view'),
    path('clothes/result/', views.result_view, name='result_view'),

    # Hair try-on
    path('hair/upload/', views.hair_upload_view, name='hair_upload_view'),
    path('hair/preview/', views.hair_preview_view, name='hair_preview_view'),
    path('hair/process/', views.hair_process_view, name='hair_process_view'),
    path('hair/result/', views.hair_result_view, name='hair_result_view'),
]
