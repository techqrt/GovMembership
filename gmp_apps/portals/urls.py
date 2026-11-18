from django.urls import path

from gmp_apps.portals.controllers.portal import PortalsPortalViewController as Portal

urlpatterns = [
    path('get_all/', Portal.get_all, name='get_all_portals_portal'),
    path('get/', Portal.get, name='get_portals_portal'),
    path('category/get_all/', Portal.get_categories, name='get_all_portals_category'),
]
