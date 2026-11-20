from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger_ui'),
    path('auth/', include('gmp_apps.authentication.urls')),
    path('membership/', include('gmp_apps.membership.urls')),
    path('contact_admin/', include('gmp_apps.contact_admin.urls')),
    path('schemes/', include('gmp_apps.schemes.urls')),
    path('portals/', include('gmp_apps.portals.urls')),
    path('content/', include('gmp_apps.content.urls')),
    path('notifications/', include('gmp_apps.notifications.urls')),
    path('dashboard/', include('gmp_apps.dashboard.urls')),
    path('chatbot/', include('gmp_apps.chatbot.urls')),
    path('member_documents/', include('gmp_apps.member_documents.urls')),
]

# Development only: in production the web server (nginx etc.) serves MEDIA_ROOT at MEDIA_URL.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
