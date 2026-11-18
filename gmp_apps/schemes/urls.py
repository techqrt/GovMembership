from django.urls import path

from gmp_apps.schemes.controllers.scheme import SchemesSchemeViewController as Scheme

urlpatterns = [
    path('get_all/', Scheme.get_all, name='get_all_schemes_scheme'),
    path('get/', Scheme.get, name='get_schemes_scheme'),
    path('tag/get_all/', Scheme.get_tags, name='get_all_schemes_tag'),
    path('delete/', Scheme.delete, name='delete_schemes_scheme'),
]
