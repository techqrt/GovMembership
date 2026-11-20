from django.urls import path

from gmp_apps.app_text.controllers.app_text import AppTextAppTextViewController as AppText

urlpatterns = [
    path('get_all/', AppText.get_all, name='get_all_app_text'),
]
