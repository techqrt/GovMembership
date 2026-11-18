from django.urls import path

from gmp_apps.content.controllers.content import ContentItemViewController as Content

urlpatterns = [
    path('get_all/', Content.get_all, name='get_all_content_item'),
    path('get/', Content.get, name='get_content_item'),
    path('category/get_all/', Content.get_categories, name='get_all_content_category'),
]
