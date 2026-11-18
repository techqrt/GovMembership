from django.urls import path

from gmp_apps.notifications.controllers.notification import NotificationsNotificationViewController as Notification

urlpatterns = [
    path('get_all/', Notification.get_all, name='get_all_notifications_notification'),
    path('unread_count/', Notification.unread_count, name='get_notifications_unread_count'),
    path('mark_read/', Notification.mark_read, name='update_notifications_mark_read'),
]
