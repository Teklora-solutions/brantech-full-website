"""
Central configuration management for the application.

All environment variables should be loaded through this module.
The .env file should be located in the brandtechsolution/ directory.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import List, Optional

# BASE_DIR points to brandtechsolution directory (where .env file is located)
BASE_DIR = Path(__file__).resolve().parent.parent


class AppSettings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    All environment variables are loaded from:
    1. .env file in brandtechsolution/ directory
    2. System environment variables (takes precedence)
    """
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Ignore env vars / .env keys that aren't declared here (e.g. tooling
        # secrets like GITHUB_ACCESS_TOKEN) so a shared .env doesn't crash startup.
        extra="ignore",
    )

    # ============================================================
    # Django Core Settings
    # ============================================================
    secret_key: str
    debug: bool = True
    allowed_hosts: list[str] = ["teklora.co.ke", "www.teklora.co.ke", "127.0.0.1", "localhost"]
    # HTTPS origins trusted for CSRF (required behind the Cloudflare Tunnel where
    # TLS terminates at the edge). Must include the scheme.
    csrf_trusted_origins: list[str] = ["https://teklora.co.ke", "https://www.teklora.co.ke"]

    # ============================================================
    # Email Configuration
    # ============================================================
    email_host: str = "smtp.gmail.com"
    email_port: int = 587
    email_use_tls: bool = True
    email_host_user: str = ""
    email_host_password: str = ""
    email_timeout: int = 10

    # Mailgun is the preferred transport; the SMTP settings above are only a
    # fallback for a deployment that has not been given Mailgun credentials.
    # base_url is the API root and must not include the domain -- EU accounts
    # use https://api.eu.mailgun.net/v3.
    mailgun_api_key: str = ""
    mailgun_webhook_signing_key: str = ""
    mailgun_skip_webhook_verification: bool = False
    mailgun_base_url: str = "https://api.mailgun.net/v3"
    mailgun_domain: str = ""


    # The public From address. Defaults to noreply@<mailgun_domain>, because a
    # From address outside the sending domain fails SPF and DKIM alignment and
    # lands the mail in spam.
    default_from_email: str = ""

    # Where "an article is waiting for review" lands. Falls back to
    # email_host_user, which is what this used before the move to Mailgun.
    editorial_review_email: str = ""

    # The founding team, used ONCE per address to issue a panel invitation.
    # Notifications are addressed to capability holders, never to this list --
    # its only job is to get these people onto the platform in the first place,
    # after which the panel is the single record of who is on the team. Someone
    # who never accepts stops being contacted; someone who joins later is
    # enrolled through the panel, not by editing this.
    team_seed_emails: List[str] = [
        "juniorkariuki735@gmail.com",
        "mugishalionel02@gmail.com",
        "teklorasolutionsltd@gmail.com",
        "leonmusungu138@gmail.com",
        "davidnjihia536@gmail.com",
    ]
    # The preset role a seeded invitation carries. Inquiry, booking and
    # shared-mail emails go to the superuser only, whatever the role.
    team_seed_role: str = "Support"

    # ============================================================
    # Bulk mail outbox
    # ============================================================
    outbox_batch_size: int = 50
    outbox_max_attempts: int = 3
    outbox_stale_claim_minutes: int = 15
    site_base_url: str = "https://teklora.co.ke"

    # ============================================================
    # Redis / Celery
    # ============================================================
    # One Redis instance backs three things: the Celery broker (db 0), the
    # Celery result backend (db 1) and the Django cache (db 2). Separate
    # logical databases so that clearing the cache can never drop queued work.
    #
    # In docker compose the host is the `redis` service; on a developer
    # machine it defaults to localhost, and if no Redis is running the cache
    # falls back to locmem (see settings.py) so runserver still works.
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""

    # Set to True on a developer machine without a worker: tasks then execute
    # inline in the calling process instead of being queued. The test suite
    # forces this on regardless, so tests never need a live broker.
    celery_task_always_eager: bool = False

    # Hard ceilings for a single task. The editorial pipeline makes eight
    # sequential Gemini calls and routinely runs three minutes, so these are
    # deliberately generous; the soft limit fires first and raises
    # SoftTimeLimitExceeded, which the tasks catch to record a failure.
    celery_task_soft_time_limit: int = 900
    celery_task_time_limit: int = 1200
    celery_worker_concurrency: int = 2

    # Beat intervals, in seconds.
    beat_outbox_interval: int = 60
    beat_github_sync_interval: int = 3600
    # How often linked repositories are read for task commits and roadmaps.
    beat_task_repo_interval: int = 600

    @property
    def redis_url_base(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}"

    @property
    def celery_broker_url(self) -> str:
        return f"{self.redis_url_base}/0"

    @property
    def celery_result_backend(self) -> str:
        return f"{self.redis_url_base}/1"

    @property
    def django_cache_url(self) -> str:
        return f"{self.redis_url_base}/2"

    # ============================================================
    # Cloudflare Turnstile (bot protection on public forms)
    # ============================================================
    # Both come from the Cloudflare dashboard under Turnstile. The site key is
    # public and rendered into the page; the secret key is not and is only
    # ever sent server-to-server to siteverify.
    #
    # Leaving them empty disables the checks, which is what you want on a
    # developer machine. A Django system check refuses to start with DEBUG
    # off and no secret, so an unprotected deployment cannot happen quietly -
    # see brandtechsolution/turnstile.py.
    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""

    # ============================================================
    # Public contact form rate limiting
    # ============================================================
    contact_rate_limit_count: int = 5
    contact_rate_limit_window_seconds: int = 3600

    # Likes are one request each and a reader may work through a page of
    # posts, so this is far looser than the contact form -- it exists to stop
    # a script inflating the "popular" ranking, not to pace a human.
    blog_like_rate_limit_count: int = 30
    blog_like_rate_limit_window_seconds: int = 60

    # Chatbot messages per address. Each is a paid model call holding a web
    # worker for seconds; a person chatting rarely sends more than one every
    # half minute.
    chat_rate_limit_count: int = 20
    chat_rate_limit_window_seconds: int = 600

    # ============================================================
    # Gemini API Configuration
    # ============================================================
    google_api_key: str
    
    # Gemini Model Configuration
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_embedding_model: str = "models/gemini-embedding-001"
    
    # ============================================================
    # LangSmith Configuration
    # ============================================================
    # A real bool, not a str. Declared as `str = "true"` it could not be turned
    # off: both readers in ai_workflows/service.py test it for truthiness, and
    # the string "false" is truthy in Python, so LANGSMITH_TRACING=false in the
    # environment still resolved to enabled. pydantic-settings parses the usual
    # false/0/no spellings into False.
    langsmith_tracing: bool = True
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "brantech-ai"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # ============================================================
    # Model providers
    # ============================================================
    # One key per provider. Presence makes a provider a *candidate*; it only
    # becomes active once it has answered its own model-list endpoint, because
    # "a key is present" and "a key works" are different things and conflating
    # them turns a typo into a silent outage. Gemini's key is google_api_key
    # above -- it predates this block and everything currently runs on it.
    openrouter_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""

    # ChatGPT OAuth for Codex. Subscription-billed rather than usage-billed,
    # and off unless deliberately enabled -- see harness/providers.py for why.
    codex_oauth_token: str = ""

    # Google Cloud Vertex AI Configuration (Service Account JSON & Project)
    google_application_credentials: str = ""
    vertex_project_id: str = ""
    vertex_location: str = "us-central1"

    # Per-request ceiling for a chat model call, in seconds.
    llm_timeout: int = 60

    # What one supervised run may spend before it refuses to dispatch again,
    # in USD. Checked between agents, so a run stops cleanly rather than
    # abandoning an agent mid-call.
    #
    # Approximate by construction, and deliberately so. Most prices in the
    # catalogue are borrowed from OpenRouter's listing rather than published
    # by the provider that bills, and a call to an unpriced model cannot be
    # counted against this at all -- see `harness/usage.py`. It is a runaway
    # stop, not an accountant. Set to 0 to turn it off.
    agent_run_spend_ceiling_usd: float = 5.0

    # ============================================================
    # GitHub Integration Configuration
    # ============================================================
    github_access_token: Optional[str] = None
    github_username: Optional[str] = None
    # Signs GitHub's push webhook for the task board (optional; polling
    # covers the same ground a few minutes later).
    github_webhook_secret: Optional[str] = None

    # ============================================================
    # Database Configuration
    # ============================================================
    database_engine: str = "postgresql"
    database_name: str = "brantech"
    database_user: str
    database_password: str
    database_host: str = "localhost"
    database_port: str = "5432"
    database_conn_max_age: int = 60

    # ============================================================
    # Static & Media (filesystem paths)
    # ============================================================
    static_root: str = str(BASE_DIR / "staticfiles")
    media_root: str = str(BASE_DIR / "media")
    # Mail attachments are private and must never sit under media_root,
    # which is served to anyone.
    mail_attachments_root: str = str(BASE_DIR / "private" / "mail_attachments")


# Create global config instance
config = AppSettings()


# ============================================================
# Which .env actually took effect
# ============================================================
# There are two .env files in this project and they are not the same file.
#
#   brandtechsolution/.env   what `env_file` above points at, so what a local
#                            `manage.py` reads.
#   <repo root>/.env         what docker-compose's `env_file:` injects, so what
#                            the containers read.
#
# pydantic-settings reads real environment variables at higher priority than
# any env_file, so inside Docker the root file wins and the path above is
# irrelevant. Outside Docker the root file is never read at all.
#
# That asymmetry is invisible and it cost a full day: a key was rotated in the
# root file, the local process kept reading a months-old key from the other
# one, and every symptom pointed at the API rather than at the file. Nothing
# raised, because nothing was wrong -- both files were valid, and the wrong one
# was being read perfectly.
#
# So: report it. Not merge the files, which would hand a local `manage.py` the
# container's database credentials, and not refuse to start, because the two
# files differing is the *normal* state for everything else in them.

ROOT_ENV_FILE = BASE_DIR.parent / ".env"

# Only credentials, and deliberately not the whole file. `database_host`,
# `debug` and `allowed_hosts` differ between these two files *on purpose* --
# they describe two environments -- and a warning that fires on every run for
# an expected difference is one people learn to scroll past. An API key is not
# environment-specific: the same key works in both, so the two disagreeing
# means one of them is stale.
SHARED_CREDENTIALS = (
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY",
    "CODEX_OAUTH_TOKEN",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "LANGSMITH_API_KEY",
)


def fingerprint(secret: str) -> str:
    """Eight hex characters identifying a secret, without disclosing it.

    Enough to answer "is this the same key I just pasted?", and useless to
    anyone who reads it out of a log.
    """
    import hashlib

    if not secret:
        return "unset"
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:8]


def read_env_file(path) -> dict:
    """KEY=VALUE pairs from a .env file, or {} if it is not readable.

    A deliberately small parser rather than a dependency: this runs during
    settings import, it only ever needs to answer a comparison, and an
    unreadable or malformed file must degrade to "cannot tell" rather than
    stopping Django from starting.
    """
    values = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return values

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        values[key.strip().upper()] = value
    return values


def credential_drift(settings=None, root_env_file=ROOT_ENV_FILE):
    """Credentials the root .env sets to something other than what is live.

    Compares against the *loaded* value rather than against the other file, so
    it answers the question that actually matters -- "is the file I just edited
    the one in effect?" -- and stays quiet under Docker, where the root file is
    what loaded and there is nothing to report.

    Returns a list of (key, live_fingerprint, file_fingerprint). Empty when the
    root file does not exist, which is the normal case in a container built
    from it.
    """
    if settings is None:
        settings = config

    if not root_env_file.exists():
        return []

    on_disk = read_env_file(root_env_file)
    drifted = []

    for key in SHARED_CREDENTIALS:
        if key not in on_disk:
            continue
        stated = on_disk[key]
        live = getattr(settings, key.lower(), "") or ""
        # A key present in one file and absent from the other is a gap, not a
        # conflict; only report two values that disagree.
        if not stated or not live:
            continue
        if stated != live:
            drifted.append((key, fingerprint(live), fingerprint(stated)))

    return drifted
