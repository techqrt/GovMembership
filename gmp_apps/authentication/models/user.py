from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from gmp_apps.authentication.identity import KINDS, IdentityUtils
from gmp_apps.authentication.utils import AuthenticationUtils
from gmp_apps.common import field_encryption
from gmp_apps.common.exceptions.errors import ForbiddenError


class MembershipLevel(models.TextChoices):
    GENERAL = 'general', 'General'
    ACTIVE = 'active', 'Active'
    PERMANENT = 'permanent', 'Permanent'


class Role(models.TextChoices):
    MEMBER = 'member', 'Member'
    ADMIN = 'admin', 'Admin'


class Gender(models.TextChoices):
    MALE = 'male', 'Male'
    FEMALE = 'female', 'Female'
    OTHER = 'other', 'Other'


class AreaType(models.TextChoices):
    URBAN = 'urban', 'Urban'
    RURAL = 'rural', 'Rural'


class UserManager(BaseUserManager):
    def create_user(
        self,
        full_name: str,
        password: str,
        email: str | None = None,
        mobile_number: str | None = None,
        **extra: object,
    ) -> 'User':
        if not email and not mobile_number:
            raise ValueError('Provide a mobile number or an email')
        user = self.model(
            full_name=full_name,
            email=AuthenticationUtils.normalize_email(email),
            mobile_number=AuthenticationUtils.normalize_mobile(mobile_number),
            membership_id=self._unique_code('membership_id', 'GM', 8),
            referral_code=self._unique_code('referral_code', 'R', 8),
            **extra,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, full_name: str, password: str, email: str, **extra: object) -> 'User':
        extra.pop('membership_id', None)  # createsuperuser asks for the USERNAME_FIELD; the ID is always generated
        extra.update(is_staff=True, is_superuser=True, role=Role.ADMIN, email_verified=True)
        return self.create_user(full_name=full_name, password=password, email=email, **extra)

    def _unique_code(self, field: str, prefix: str, length: int) -> str:
        while True:
            code = AuthenticationUtils.random_code(prefix=prefix, length=length)
            if not self.model.objects.filter(**{field: code}).exists():
                return code


class User(AbstractBaseUser, PermissionsMixin):
    user_id = models.BigAutoField(primary_key=True)
    membership_id = models.CharField(max_length=16, unique=True, editable=False)
    referral_code = models.CharField(max_length=16, unique=True, editable=False)
    full_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True, null=True, blank=True)
    mobile_number = models.CharField(max_length=16, unique=True, null=True, blank=True)
    email_verified = models.BooleanField(default=False)
    mobile_verified = models.BooleanField(default=False)
    membership_level = models.CharField(max_length=16, choices=MembershipLevel.choices, default=MembershipLevel.GENERAL)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=8, choices=Gender.choices, blank=True, default='')
    state = models.CharField(max_length=100, blank=True, default='')
    city = models.CharField(max_length=100, blank=True, default='')
    father_name = models.CharField(max_length=150, blank=True, default='')
    profession = models.CharField(max_length=100, blank=True, default='')
    area_type = models.CharField(max_length=8, choices=AreaType.choices, blank=True, default='')
    mandal = models.CharField(max_length=100, blank=True, default='')
    ward_village = models.CharField(max_length=100, blank=True, default='')
    house_street = models.CharField(max_length=200, blank=True, default='')
    pin_code = models.CharField(max_length=6, blank=True, default='')
    app_language = models.CharField(max_length=10, blank=True, default='')
    declaration_accepted = models.BooleanField(default=False)
    declaration_accepted_at = models.DateTimeField(null=True, blank=True)
    # Government ID numbers: ciphertext + last 4 characters (for the mask) + keyed hash (exact-match lookup).
    # Never editable through a form and never returned by any API except as a mask.
    aadhaar_encrypted = models.TextField(blank=True, default='', editable=False)
    aadhaar_last4 = models.CharField(max_length=4, blank=True, default='', editable=False)
    aadhaar_hash = models.CharField(max_length=64, blank=True, default='', editable=False, db_index=True)
    pan_encrypted = models.TextField(blank=True, default='', editable=False)
    pan_last4 = models.CharField(max_length=4, blank=True, default='', editable=False)
    pan_hash = models.CharField(max_length=64, blank=True, default='', editable=False, db_index=True)
    registration_ip = models.GenericIPAddressField(null=True, blank=True, editable=False)
    is_active = models.BooleanField(default=True)
    suspended_reason = models.TextField(blank=True, default='')
    suspended_at = models.DateTimeField(null=True, blank=True)
    # Bumped on suspend/reactivate. Every token carries the version it was issued with; a mismatch is rejected.
    token_version = models.PositiveIntegerField(default=0, editable=False)
    is_staff = models.BooleanField(default=False)
    created_date_time = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = 'membership_id'
    REQUIRED_FIELDS = ['full_name', 'email']

    class Meta:
        db_table = 'user'
        permissions = [
            ('suspend_member', 'Can suspend or reactivate members'),
            ('view_government_ids', 'Can see members\' full Aadhaar and PAN numbers'),
        ]

    def __str__(self) -> str:
        return f'{self.membership_id} ({self.full_name})'

    @staticmethod
    def id_columns(kind: str) -> tuple[str, str, str]:
        if kind not in KINDS:
            raise ValueError('Unknown ID kind')
        return f'{kind}_encrypted', f'{kind}_last4', f'{kind}_hash'

    def set_government_id(self, kind: str, value: str | None) -> list[str]:
        """Store (encrypted) or clear an Aadhaar/PAN number. `value` must already be validated.
        Returns the column names to include in save(update_fields=...)."""
        encrypted, last4, digest = User.id_columns(kind)
        normalized = IdentityUtils.normalize(kind, value or '')
        if not normalized:
            setattr(self, encrypted, ''), setattr(self, last4, ''), setattr(self, digest, '')
        else:
            if not IdentityUtils.is_valid(kind, normalized):
                raise ValueError(f'Invalid {kind} number')
            setattr(self, encrypted, field_encryption.encrypt(normalized))
            setattr(self, last4, normalized[-4:])
            setattr(self, digest, field_encryption.blind_index(kind, normalized))
        return [encrypted, last4, digest]

    def masked_id(self, kind: str) -> str | None:
        """What members and the API see: all but the last 4 characters hidden, or None when not given."""
        last4 = getattr(self, User.id_columns(kind)[1])
        return IdentityUtils.mask(kind, last4) if last4 else None

    def reveal_government_id(self, kind: str) -> str | None:
        """The full number. Only for the admin reveal page, which logs every use."""
        token = getattr(self, User.id_columns(kind)[0])
        return field_encryption.decrypt(token) if token else None

    @staticmethod
    def find_by_identifier(identifier: str) -> 'User | None':
        """Look up by normalized email or mobile number."""
        normalized = AuthenticationUtils.normalize_identifier(identifier)
        field = 'email' if AuthenticationUtils.identifier_channel(normalized) == 'email' else 'mobile_number'
        return User.objects.filter(**{field: normalized}).first()

    @staticmethod
    def is_valid_referrer_code(code: str) -> bool:
        """A code is usable only if its owner is active and has a verified contact."""
        owner = User.objects.filter(referral_code=code, is_active=True).first()
        return owner is not None and (owner.email_verified or owner.mobile_verified)

    @staticmethod
    def assert_can_change_status(actor: 'User', target: 'User', make_active: bool, reason: str) -> None:
        """Rules for suspending/reactivating. Raises ForbiddenError or ValueError with a clear message."""
        if actor.user_id == target.user_id:
            raise ForbiddenError('You cannot suspend or reactivate your own account')
        if not actor.has_perm('authentication.suspend_member'):
            raise ForbiddenError('You do not have permission to suspend or reactivate members')
        if (target.is_staff or target.is_superuser or target.role == Role.ADMIN) and not actor.is_superuser:
            raise ForbiddenError('Only a superuser can suspend or reactivate admin accounts')
        if not make_active and not reason.strip():
            raise ValueError('A reason is required to suspend a member')

    def suspend(self, actor: 'User', reason: str) -> None:
        """Deactivate the account and kill every session immediately (the reason is kept)."""
        User.assert_can_change_status(actor, self, make_active=False, reason=reason)
        self.is_active = False
        self.suspended_reason = reason.strip()
        self.suspended_at = timezone.now()
        self.token_version += 1
        self.save(update_fields=['is_active', 'suspended_reason', 'suspended_at', 'token_version'])
        self.revoke_all_sessions()

    def reactivate(self, actor: 'User') -> None:
        """Re-enable the account. Old sessions stay revoked: the member must log in again."""
        User.assert_can_change_status(actor, self, make_active=True, reason='')
        self.is_active = True
        self.token_version += 1
        self.save(update_fields=['is_active', 'token_version'])
        self.revoke_all_sessions()

    def revoke_all_sessions(self) -> None:
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

        for outstanding in OutstandingToken.objects.filter(user=self):
            BlacklistedToken.objects.get_or_create(token=outstanding)

    def is_channel_verified(self, channel: str) -> bool:
        return self.email_verified if channel == 'email' else self.mobile_verified

    def mark_channel_verified(self, channel: str) -> None:
        field = 'email_verified' if channel == 'email' else 'mobile_verified'
        setattr(self, field, True)
        self.save(update_fields=[field])
