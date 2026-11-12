import uuid
from django.db import models
from django.utils import timezone
from pgvector.django import VectorField
from django.conf import settings
from .library.storage import library_storage, version_path


class KnowledgeDocument(models.Model):
    """Module 13: Knowledge Base Agent

    Stores vector embeddings and structured text of every article, research paper,
    summary, trend, and source to allow future articles to reuse verified knowledge via RAG.
    """
    DOC_TYPES = [
        ('article', 'Published Article'),
        ('research_dossier', 'Research Dossier'),
        ('trend_summary', 'Trend Summary'),
        ('source_doc', 'External Reference Document'),
    ]

    title = models.CharField(max_length=300)
    doc_type = models.CharField(max_length=30, choices=DOC_TYPES, default='article')
    content = models.TextField()
    metadata = models.JSONField(default=dict, help_text="Source URL, tags, category, author info")
    
    # 3072 dimensions matching Gemini embedding-001 vector space
    embedding = VectorField(dimensions=3072, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_doc_type_display()}] {self.title}"


# ============================================================
# UNIFIED SEMANTIC MEMORY
# ============================================================
# Step 2 of the agent harness. Memory lived in three places that did not know
# about each other: DjangoCheckpointer (chat only), EditorialMemory (a
# singleton row, editorial only), and this app's KnowledgeDocument -- a proper
# pgvector store that was barely used, while the newsroom's duplicate check
# compared the first twenty characters of a title.
#
# Vectors also lived as single columns on BlogPost, Project and
# KnowledgeDocument, which meant a row could hold exactly one vector and
# nothing recorded which model produced it. Two embedding spaces could not
# coexist, so changing the embedding model was unimplementable: every stored
# vector would have been incomparable with every new one, and nothing would
# have raised -- search would simply have got quietly worse.


class EmbeddingSpace(models.Model):
    """One embedding model's vector space.

    Vectors from two models are not comparable; a cosine score between them is
    a number with no meaning. So a space is the unit of comparability, and
    queries never mix them. Changing model creates a new space and backfills
    into it while the old one keeps serving, then cutover is one atomic flip.
    """

    BUILDING = 'building'
    ACTIVE = 'active'
    RETIRED = 'retired'
    STATUS_CHOICES = [
        (BUILDING, 'Building'),
        (ACTIVE, 'Active'),
        (RETIRED, 'Retired'),
    ]

    provider = models.CharField(max_length=40, default='gemini')
    model_id = models.CharField(max_length=120)
    dimensions = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=BUILDING)

    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            # Two active spaces would mean queries silently drawing from both.
            models.UniqueConstraint(
                fields=['status'], condition=models.Q(status='active'),
                name='only_one_active_embedding_space',
            ),
        ]

    def __str__(self):
        return f"{self.provider}/{self.model_id} ({self.dimensions}d, {self.status})"

    @classmethod
    def active(cls):
        return cls.objects.filter(status=cls.ACTIVE).first()


class MemoryDocument(models.Model):
    """One thing worth remembering, independent of how it is embedded.

    Identity and usage statistics live here rather than on the vector, so they
    survive a re-embedding. That is the point: retrieval counts are the input
    to the importance score that decides what gets re-embedded first when the
    model changes, and a count that reset on every migration would be useless
    for exactly the job it exists to do.
    """

    content_type = models.ForeignKey(
        'contenttypes.ContentType', on_delete=models.CASCADE, null=True, blank=True,
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)

    # Which corpus this belongs to. `Memory` took a `scope` argument from the
    # day it was written, stored it, and never used it -- so a caller writing
    # `Memory(scope="editorial")` got a parameter that read as a filter and
    # filtered nothing. This is the column that makes it true.
    scope = models.CharField(max_length=40, default='default', db_index=True)

    kind = models.CharField(max_length=40, default='document', db_index=True)
    title = models.CharField(max_length=300, blank=True, default='')
    text = models.TextField(blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)

    # Skips re-embedding text that has not changed.
    content_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)

    # The strongest importance signal, and the one that did not exist before:
    # how often the agents actually use this. View counts measure human
    # attention; this measures what the system reaches for.
    retrieval_count = models.PositiveIntegerField(default=0, db_index=True)
    last_retrieved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['content_type', 'object_id'],
                condition=models.Q(content_type__isnull=False),
                name='one_memory_document_per_object',
            ),
        ]
        indexes = [models.Index(fields=['kind', '-retrieval_count'])]

    def __str__(self):
        return self.title or f"MemoryDocument #{self.pk}"


class Embedding(models.Model):
    """One document's vector in one space.

    provider / model_id / dimensions are denormalised from the space on
    purpose. A space row can be edited and a model can be renamed or retired,
    but what produced *this* vector cannot change after the fact, so provenance
    has to survive its parent being corrected. It also makes "which model
    served this result?" a query rather than an inference from deployment
    dates, and makes a space holding two model_ids an assertable bug rather
    than silent corruption.
    """

    space = models.ForeignKey(EmbeddingSpace, related_name='embeddings', on_delete=models.CASCADE)
    document = models.ForeignKey(MemoryDocument, related_name='embeddings', on_delete=models.CASCADE)

    provider = models.CharField(max_length=40)
    model_id = models.CharField(max_length=120)
    dimensions = models.PositiveIntegerField()

    # No fixed dimension: pgvector emits a bare `vector` column, which accepts
    # any width, so one table holds both spaces during a migration.
    #
    # The cost of that is an index, and the prediction this comment used to
    # make turned out to be right: Postgres refuses `create index ... using
    # hnsw` on a column whose width it does not know ("column does not have
    # dimensions"), and the answer is a partial index per space over a cast
    # expression, not a schema redesign. See knowledge_base/indexes.py, which
    # builds it, and Memory._vector_column, which carries the matching cast
    # into the query so the index is actually used.
    #
    # One constraint that only shows up in practice: pgvector caps hnsw at
    # 2000 dimensions, and gemini-embedding-001's native width is 3072. That
    # space cannot be indexed at any effort, which is why `manage.py reembed`
    # exists -- a narrower space is a supported Matryoshka truncation of the
    # same model, and it is indexable.
    vector = VectorField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['space', 'document'], name='one_embedding_per_document_per_space',
            ),
        ]
        indexes = [models.Index(fields=['space', 'document'])]

    def __str__(self):
        return f"{self.document} in {self.space}"


class LibraryDocument(models.Model):
    """Authoritative ACL and current-version pointer; never stored in vector metadata."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='library_documents')
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True, max_length=5000)
    category = models.CharField(max_length=80, default='general', db_index=True)
    tags = models.JSONField(default=list, blank=True)
    visibility = models.CharField(max_length=20, choices=[('private', 'Private'), ('organisation', 'Organisation staff')], default='private')
    current_version = models.ForeignKey('LibraryVersion', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']


class LibraryVersion(models.Model):
    """Immutable original; processing and review states belong to the exact version."""
    document = models.ForeignKey(LibraryDocument, on_delete=models.CASCADE, related_name='versions')
    version_number = models.PositiveIntegerField()
    original = models.FileField(storage=library_storage, upload_to=version_path)
    original_filename = models.CharField(max_length=255)
    detected_format = models.CharField(max_length=10)
    size_bytes = models.PositiveIntegerField()
    checksum_sha256 = models.CharField(max_length=64)
    uploader = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='library_uploads')
    upload_authority = models.BooleanField(default=False)
    processing_state = models.CharField(max_length=30, default='awaiting_clearance', db_index=True)
    clearance_state = models.CharField(max_length=20, default='pending', db_index=True)
    public_approval_state = models.CharField(max_length=20, default='not_reviewed', db_index=True)
    classification = models.CharField(max_length=40, default='internal_standard')
    permitted_provider = models.CharField(max_length=40, blank=True)
    safe_error_code = models.CharField(max_length=60, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    processing_token = models.UUIDField(default=uuid.uuid4, editable=False)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['document', 'version_number'], name='library_unique_version')]


class LibraryGrant(models.Model):
    document = models.ForeignKey(LibraryDocument, on_delete=models.CASCADE, related_name='grants')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name='library_grants')
    group = models.ForeignKey('auth.Group', null=True, blank=True, on_delete=models.CASCADE, related_name='library_grants')
    access_level = models.CharField(max_length=10, choices=[('read', 'Read'), ('edit', 'Edit')], default='read')

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(models.Q(user__isnull=False, group__isnull=True) | models.Q(user__isnull=True, group__isnull=False)), name='library_grant_one_subject'),
            models.UniqueConstraint(fields=['document', 'user'], name='library_unique_user_grant'),
            models.UniqueConstraint(fields=['document', 'group'], name='library_unique_group_grant'),
        ]


class LibraryChunk(models.Model):
    version = models.ForeignKey(LibraryVersion, on_delete=models.CASCADE, related_name='chunks')
    ordinal = models.PositiveIntegerField()
    text = models.TextField()
    page_or_section = models.CharField(max_length=100, blank=True)
    content_hash = models.CharField(max_length=64)
    memory_document = models.OneToOneField(MemoryDocument, null=True, blank=True, on_delete=models.SET_NULL, related_name='library_chunk')

    @property
    def document(self):
        return self.version.document

    @property
    def document_id(self):
        return self.version.document_id

    class Meta:
        constraints = [models.UniqueConstraint(fields=['version', 'ordinal'], name='library_unique_chunk')]
        ordering = ['ordinal']


class LibraryAudit(models.Model):
    """Append-only decisions/access events. Never include extracted text or credentials."""
    document = models.ForeignKey(LibraryDocument, on_delete=models.SET_NULL, null=True, related_name='audit_events')
    version = models.ForeignKey(LibraryVersion, on_delete=models.SET_NULL, null=True, related_name='audit_events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='library_audit_events')
    action = models.CharField(max_length=40, db_index=True)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
