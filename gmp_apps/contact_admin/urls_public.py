from django.urls import path

from gmp_apps.contact_admin.controllers.public import ContactPublicCategoryViewController as Category
from gmp_apps.contact_admin.controllers.public import ContactPublicRequestViewController as Request

# Mounted at contact/ (no login). The logged-in member endpoints stay under contact_admin/.
urlpatterns = [
    path('category/get_all/', Category.get_all, name='get_all_contact_category'),
    path('request/create/', Request.create, name='create_contact_request'),
]
