from django.urls import path

from gmp_apps.authentication.controllers.auth import AuthenticationAuthViewController
from gmp_apps.authentication.controllers.profile import AuthenticationProfileViewController

urlpatterns = [
    path('register/', AuthenticationAuthViewController.register, name='create_authentication_register'),
    path('verify_otp/', AuthenticationAuthViewController.verify_otp, name='create_authentication_verify_otp'),
    path('resend_otp/', AuthenticationAuthViewController.resend_otp, name='create_authentication_resend_otp'),
    path('login/', AuthenticationAuthViewController.login, name='create_authentication_login'),
    path('refresh/', AuthenticationAuthViewController.refresh, name='create_authentication_refresh'),
    path('logout/', AuthenticationAuthViewController.logout, name='create_authentication_logout'),
    path('change_password/', AuthenticationAuthViewController.change_password, name='update_authentication_change_password'),
    path('forgot_password/', AuthenticationAuthViewController.forgot_password, name='create_authentication_forgot_password'),
    path('reset_password/', AuthenticationAuthViewController.reset_password, name='update_authentication_reset_password'),
    path('profile/get/', AuthenticationProfileViewController.get, name='get_authentication_profile'),
    path('profile/update/', AuthenticationProfileViewController.update, name='update_authentication_profile'),
]
