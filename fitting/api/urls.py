from django.urls import path
from . import views

urlpatterns = [
    # Home
    path('', views.api_home, name='api_home'),
    
    # Simplified try-on endpoints
    path('clothes/try-on/', views.clothes_try_on, name='api_clothes_try_on'),
    path('hair/try-on/', views.hair_try_on, name='api_hair_try_on'),
    path('config/openai-api-key/', views.OpenAIApiKeyView.as_view(), name='open_ai_api_key'),
]
