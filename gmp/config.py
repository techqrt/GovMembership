from decouple import Csv, config


class Configurations:
    secret_key: str = config('SECRET_KEY')
    debug: bool = config('DEBUG', default=False, cast=bool)
    allowed_hosts: list[str] = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

    # Origins trusted for CSRF (admin login over HTTPS). Example: CSRF_TRUSTED_ORIGINS=https://cop.checkour.work
    csrf_trusted_origins: list[str] = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())

    # Browser origins allowed to call the API (website / web app). Empty = no cross-origin access.
    # Mobile apps do not use CORS. Example: CORS_ALLOWED_ORIGINS=https://members.example.gov.in
    cors_allowed_origins: list[str] = config('CORS_ALLOWED_ORIGINS', default='', cast=Csv())

    # Fernet keys (url-safe base64, 32 bytes) that encrypt Aadhaar/PAN at rest. The FIRST key encrypts, every key can
    # decrypt, so rotation = put a new key first. Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Empty is allowed only for local development (a key is derived from SECRET_KEY then).
    field_encryption_keys: list[str] = config('FIELD_ENCRYPTION_KEYS', default='', cast=Csv())

    db_engine: str = config('DB_ENGINE', default='postgresql')
    db_name: str = config('DB_NAME', default='gmp')
    db_user: str = config('DB_USER', default='')
    db_password: str = config('DB_PASSWORD', default='')
    db_host: str = config('DB_HOST', default='localhost')
    db_port: str = config('DB_PORT', default='5432')

    pagination_count: int = 10
    max_page_limit: int = 100

    active_referrals_required: int = config('ACTIVE_REFERRALS_REQUIRED', default=5, cast=int)
    referral_link_base_url: str = config('REFERRAL_LINK_BASE_URL', default='http://localhost:3000/register')
    referral_flag_same_ip: bool = config('REFERRAL_FLAG_SAME_IP', default=True, cast=bool)
    referral_invite_ttl_days: int = config('REFERRAL_INVITE_TTL_DAYS', default=30, cast=int)
    celery_broker_url: str = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
    invite_expiry_interval_minutes: int = config('INVITE_EXPIRY_INTERVAL_MINUTES', default=60, cast=int)
    contact_max_open_requests: int = config('CONTACT_MAX_OPEN_REQUESTS', default=5, cast=int)
    contact_max_per_day: int = config('CONTACT_MAX_PER_DAY', default=10, cast=int)
    contact_public_submit_rate: str = config('CONTACT_PUBLIC_SUBMIT_RATE', default='5/hour')
    contact_public_category_rate: str = config('CONTACT_PUBLIC_CATEGORY_RATE', default='60/min')
    scheme_source_host: str = config('SCHEME_SOURCE_HOST', default='www.govtschemes.in')
    scheme_sync_delay_seconds: float = config('SCHEME_SYNC_DELAY_SECONDS', default=1.0, cast=float)
    scheme_sync_max_pages: int = config('SCHEME_SYNC_MAX_PAGES', default=2000, cast=int)
    scheme_sync_interval_hours: int = config('SCHEME_SYNC_INTERVAL_HOURS', default=24, cast=int)
    scheme_sync_request_timeout: int = config('SCHEME_SYNC_REQUEST_TIMEOUT', default=20, cast=int)
    scheme_sync_max_consecutive_errors: int = config('SCHEME_SYNC_MAX_CONSECUTIVE_ERRORS', default=10, cast=int)
    media_base_url: str = config('MEDIA_BASE_URL', default='')
    scheme_image_max_bytes: int = config('SCHEME_IMAGE_MAX_BYTES', default=5_000_000, cast=int)
    scheme_document_max_bytes: int = config('SCHEME_DOCUMENT_MAX_BYTES', default=15_000_000, cast=int)
    portal_url_max_length: int = 500
    private_media_root: str = config('PRIVATE_MEDIA_ROOT', default='')   # empty = <backend>/private_media (never served publicly)
    member_document_max_bytes: int = config('MEMBER_DOCUMENT_MAX_BYTES', default=10_000_000, cast=int)
    member_document_max_per_member: int = config('MEMBER_DOCUMENT_MAX_PER_MEMBER', default=30, cast=int)
    member_document_max_contact_attachments: int = config('MEMBER_DOCUMENT_MAX_CONTACT_ATTACHMENTS', default=15, cast=int)
    member_document_max_per_type: int = config('MEMBER_DOCUMENT_MAX_PER_TYPE', default=3, cast=int)
    member_document_upload_rate: str = config('MEMBER_DOCUMENT_UPLOAD_RATE', default='20/hour')
    dashboard_items_per_section: int = config('DASHBOARD_ITEMS_PER_SECTION', default=5, cast=int)
    dashboard_support_items: int = config('DASHBOARD_SUPPORT_ITEMS', default=3, cast=int)
    chatbot_enabled: bool = config('CHATBOT_ENABLED', default=False, cast=bool)
    chatbot_provider: str = config('CHATBOT_PROVIDER', default='gmp_apps.chatbot.providers.gemini.GeminiProvider')
    gemini_api_key: str = config('GEMINI_API_KEY', default='')
    gemini_model: str = config('GEMINI_MODEL', default='gemini-3.5-flash-lite')
    chatbot_timeout_seconds: int = config('CHATBOT_TIMEOUT_SECONDS', default=20, cast=int)
    chatbot_max_output_tokens: int = config('CHATBOT_MAX_OUTPUT_TOKENS', default=1024, cast=int)
    chatbot_max_question_chars: int = config('CHATBOT_MAX_QUESTION_CHARS', default=500, cast=int)
    chatbot_rate: str = config('CHATBOT_RATE', default='6/min')
    app_text_rate: str = config('APP_TEXT_RATE', default='300/hour')
    chatbot_max_per_day: int = config('CHATBOT_MAX_PER_DAY', default=60, cast=int)
    chatbot_index_max_entries: int = config('CHATBOT_INDEX_MAX_ENTRIES', default=300, cast=int)
    chatbot_log_retention_days: int = config('CHATBOT_LOG_RETENTION_DAYS', default=90, cast=int)
    content_video_hosts: list[str] = config('CONTENT_VIDEO_HOSTS', default='youtube.com,youtu.be,vimeo.com', cast=Csv())
    content_read_words_per_minute: int = config('CONTENT_READ_WORDS_PER_MINUTE', default=200, cast=int)
    content_image_max_bytes: int = config('CONTENT_IMAGE_MAX_BYTES', default=5_000_000, cast=int)
    referral_max_per_day: int = config('REFERRAL_MAX_PER_DAY', default=10, cast=int)

    access_token_minutes: int = config('ACCESS_TOKEN_MINUTES', default=15, cast=int)
    refresh_token_days: int = config('REFRESH_TOKEN_DAYS', default=7, cast=int)

    otp_length: int = config('OTP_LENGTH', default=6, cast=int)
    otp_ttl_minutes: int = config('OTP_TTL_MINUTES', default=10, cast=int)
    otp_max_attempts: int = config('OTP_MAX_ATTEMPTS', default=5, cast=int)
    otp_resend_cooldown_seconds: int = config('OTP_RESEND_COOLDOWN_SECONDS', default=60, cast=int)
    otp_delivery_backend: str = config(
        'OTP_DELIVERY_BACKEND',
        default='gmp_apps.authentication.otp_delivery.ConsoleOtpBackend',
    )
    auth_throttle_rate: str = config('AUTH_THROTTLE_RATE', default='30/min')
