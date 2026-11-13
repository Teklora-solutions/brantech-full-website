"""Space-bound Google embeddings with explicit billing routes; never fail over."""
import json
import logging
import math
import time
from pathlib import Path

from brandtechsolution.config import config

GOOGLE_MODEL_CHOICES = (('gemini-embedding-001', 'Gemini Embedding 001'), ('gemini-embedding-2', 'Gemini Embedding 2'))
SUPPORTED_DIMENSIONS = (768, 1536, 3072)
logger = logging.getLogger(__name__)


class EmbeddingFailure(Exception):
    """Safe worker metadata; do not retain provider responses or submitted text."""
    def __init__(self, code, *, retryable=False, retry_after=0):
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after
        super().__init__(code)


def validate_vector(vector, dimensions):
    try:
        values = [float(value) for value in vector]
        norm = math.sqrt(sum(value * value for value in values))
        if len(values) != dimensions or not all(math.isfinite(v) for v in values) or not math.isfinite(norm) or norm <= 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise EmbeddingFailure('INVALID_EMBEDDING') from exc
    return [v / norm for v in values]


def classify_failure(exc):
    # MemoryUnavailable keeps a cause; inspect types/codes, never private text.
    cause = exc
    for _ in range(8):
        if isinstance(cause, EmbeddingFailure):
            return cause
        if cause.__cause__ is None:
            break
        cause = cause.__cause__
    exc = cause
    if isinstance(exc, EmbeddingFailure):
        return exc
    from billiard.exceptions import SoftTimeLimitExceeded
    from google.auth.exceptions import RefreshError
    if isinstance(exc, RefreshError) and not exc.retryable:
        return EmbeddingFailure('AUTHENTICATION_OR_PERMISSION')
    if isinstance(exc, (TimeoutError, SoftTimeLimitExceeded)) or 'timeout' in type(exc).__name__.lower():
        return EmbeddingFailure('TIMEOUT', retryable=True)
    status = getattr(exc, 'code', None) or getattr(exc, 'status_code', None)
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = None
    if status in {401, 403}:
        return EmbeddingFailure('AUTHENTICATION_OR_PERMISSION')
    if status == 404:
        return EmbeddingFailure('MODEL_OR_REQUEST_INVALID')
    if status in {400, 422}:
        # A single oversized/invalid source must not disable the entire profile.
        return EmbeddingFailure('SOURCE_OR_REQUEST_INVALID')
    if status == 429:
        headers = getattr(getattr(exc, 'response', None), 'headers', {}) or {}
        try:
            delay = min(3600, max(0, int(headers.get('Retry-After', 0))))
        except (TypeError, ValueError):
            delay = 0
        return EmbeddingFailure('RATE_LIMIT', retryable=True, retry_after=delay)
    if status and status >= 500:
        return EmbeddingFailure('PROVIDER_UNAVAILABLE', retryable=True)
    # Unknown transport failures get a finite retry budget, not an infinite loop.
    return EmbeddingFailure('EMBEDDING_FAILED', retryable=True)


class GoogleEmbeddingClient:
    def __init__(self, *, model, backend, protocol='retrieval_v1', dimensions=3072):
        self.model = model.removeprefix('models/')
        if backend not in {'vertex', 'developer_api'} or protocol not in {'legacy', 'retrieval_v1'}:
            raise EmbeddingFailure('INVALID_PROFILE')
        self.backend, self.protocol, self.dimensions = backend, protocol, dimensions
        self._client = None
        self.before_send = None

    @property
    def client(self):
        if self._client is None:
            from google import genai
            from google.genai import types
            options = types.HttpOptions(timeout=15000, retry_options=types.HttpRetryOptions(attempts=1))
            if self.backend == 'vertex':
                from google.oauth2 import service_account
                from google.auth.transport.requests import Request
                import requests
                path = Path(config.google_application_credentials).expanduser()
                try:
                    identity = json.loads(path.read_text())
                    credentials = service_account.Credentials.from_service_account_file(
                        path, scopes=['https://www.googleapis.com/auth/cloud-platform'])
                    project = config.vertex_project_id or identity['project_id']
                    if not isinstance(project, str) or not project.strip() or not config.vertex_location.strip():
                        raise ValueError('Explicit Vertex project and location required')
                    project = project.strip()
                except (OSError, ValueError, KeyError):
                    raise EmbeddingFailure('VERTEX_CREDENTIAL_CONFIGURATION') from None
                # Explicit refresh has a short per-attempt HTTP timeout; do not
                # let ADC silently use a different project/Developer API key.
                try:
                    with requests.Session() as session:
                        session.trust_env = False
                        request = Request(session=session)
                        deadline = time.monotonic() + 20
                        def bounded_request(*args, **kwargs):
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise TimeoutError('Credential refresh deadline exceeded')
                            return request(*args, **{**kwargs, 'timeout': min(10, remaining)})
                        credentials.refresh(bounded_request)
                except Exception as exc:
                    raise classify_failure(exc) from None
                self._client = genai.Client(vertexai=True, project=project, location=config.vertex_location,
                                            credentials=credentials, http_options=options)
            else:
                if not config.google_api_key:
                    raise EmbeddingFailure('DEVELOPER_API_CREDENTIAL_CONFIGURATION')
                self._client = genai.Client(api_key=config.google_api_key, vertexai=False, http_options=options)
        return self._client

    def _one(self, text, *, document, output_dimensionality=None):
        from google.genai import types
        dimensions = output_dimensionality or self.dimensions
        settings = {'output_dimensionality': dimensions}
        if self.model.startswith('gemini-embedding-2'):
            if self.protocol == 'legacy':
                raise EmbeddingFailure('MODEL_PROTOCOL_UNSUPPORTED')
            text = f'title: none | text: {text}' if document else f'task: search result | query: {text}'
        else:
            settings['task_type'] = 'RETRIEVAL_DOCUMENT' if document and self.protocol != 'legacy' else 'RETRIEVAL_QUERY'
        try:
            # One Content per request avoids model-2 aggregation and Vertex 001
            # single-input limitations. Durable jobs checkpoint each response.
            client = self.client  # Resolve potentially slow credential refresh first.
            if self.before_send is not None:
                self.before_send()
            result = client.models.embed_content(model=self.model, contents=text,
                                                       config=types.EmbedContentConfig(**settings))
            if not result.embeddings or len(result.embeddings) != 1:
                raise EmbeddingFailure('INVALID_EMBEDDING_COUNT')
            return validate_vector(result.embeddings[0].values, dimensions)
        except EmbeddingFailure:
            raise
        except Exception as exc:
            raise classify_failure(exc) from None

    def embed_query(self, text, output_dimensionality=None):
        return self._one(text, document=False, output_dimensionality=output_dimensionality)

    def embed_documents(self, texts, output_dimensionality=None):
        return [self._one(text, document=True, output_dimensionality=output_dimensionality) for text in texts]

    def close(self):
        if self._client is not None:
            try:
                self._client.close()
            except Exception as exc:
                # Closing a transport must not discard a successful paid reply.
                logger.warning('Embedding transport close failed: type=%s', type(exc).__name__)
            finally:
                self._client = None
