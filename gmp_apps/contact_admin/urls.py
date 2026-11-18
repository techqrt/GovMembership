from django.urls import path

from gmp_apps.contact_admin.controllers.category import ContactAdminCategoryViewController as Category
from gmp_apps.contact_admin.controllers.request import ContactAdminRequestViewController as Request

urlpatterns = [
    path('category/get_all/', Category.get_all, name='get_all_contact_admin_category'),
    path('request/create/', Request.create, name='create_contact_admin_request'),
    path('request/get/', Request.get, name='get_contact_admin_request'),
    path('request/get_all/', Request.get_all, name='get_all_contact_admin_request'),
]
