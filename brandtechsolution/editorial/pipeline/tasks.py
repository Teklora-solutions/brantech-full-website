"""Celery tasks for the autonomous newsroom."""
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, name='editorial.run_pipeline')
def run_editorial_pipeline_task(self, run_id: int):
    """Execute one autonomous newsroom cycle, reporting progress to its run row.

    Not retried automatically. The pipeline creates TrendTopics, dossiers and
    article drafts as it goes, so a blind replay would duplicate content and
    spend model quota twice. A failed run is left failed for a human to look at.
    """
    from ai_workflows.harness.supervisor import Supervisor
    from editorial.models import EditorialPipelineRun

    try:
        run = EditorialPipelineRun.objects.get(pk=run_id)
    except EditorialPipelineRun.DoesNotExist:
        logger.error("[pipeline] run %s vanished before the task started", run_id)
        return {'status': 'missing', 'run_id': run_id}

    run.status = 'running'
    run.task_id = self.request.id or ''
    run.started_at = timezone.now()
    run.save(update_fields=['status', 'task_id', 'started_at'])

    # Dispatched through the supervisor rather than by building the
    # orchestrator here. The cycle is the same cycle; what the routing adds is
    # that the newsroom's health is recorded like every other agent's, so a
    # nightly Beat run that starts failing pages whoever holds `receive_alerts`
    # instead of going unnoticed until somebody wonders why the queue is empty.
    # One supervisor per run, because the dispatch ceiling is per run.
    supervisor = Supervisor(run_id=run.pk)

    try:
        result = supervisor.dispatch("newsroom", {
            "limit": run.limit,
            "auto_publish": run.auto_publish,
            "on_stage": run.mark_stage,
        })
        articles = result.output or []
    except SoftTimeLimitExceeded:
        # The soft limit lands here as an exception, which leaves just enough
        # time to record the failure before the hard limit kills the process.
        logger.error("[pipeline] run %s exceeded its time limit", run_id)
        run.status = 'failed'
        run.error = 'The pipeline exceeded its time limit and was stopped.'
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'error', 'finished_at'])
        raise
    except Exception as exc:
        logger.exception("[pipeline] run %s failed", run_id)
        run.status = 'failed'
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'error', 'finished_at'])
        raise

    run.status = 'success'
    run.stage = ''
    run.stage_label = ''
    run.finished_at = timezone.now()
    run.save(update_fields=['status', 'stage', 'stage_label', 'finished_at'])
    if articles:
        run.articles.set(articles)

    return {
        'status': 'success',
        'run_id': run.pk,
        'articles_processed': len(articles),
    }


@shared_task(name='editorial.release_stale_pipeline_runs')
def release_stale_pipeline_runs_task():
    """Fail runs whose worker died without recording an outcome.

    acks_late means the broker re-delivers a task whose worker was killed, but
    reject_on_worker_lost is off for the pipeline, so nothing re-runs it. Left
    alone the row would sit at 'running' forever and the dashboard would keep
    polling it. Anything still running well past the hard time limit is dead.
    """
    from django.conf import settings
    from editorial.models import EditorialPipelineRun

    cutoff = timezone.now() - timezone.timedelta(
        seconds=settings.CELERY_TASK_TIME_LIMIT * 2
    )
    stale = EditorialPipelineRun.objects.filter(
        status__in=['queued', 'running'], created_at__lt=cutoff
    )
    count = stale.update(
        status='failed',
        error='The worker handling this run stopped without reporting a result.',
        finished_at=timezone.now(),
    )
    if count:
        logger.warning("[pipeline] failed %s abandoned run(s)", count)
    return {'failed': count}


@shared_task(
    bind=True,
    name='editorial.index_article_embeddings',
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=4,
)
def index_article_embeddings_task(self, article_id: int, blog_post_id: int):
    """Push a published article into the pgvector knowledge base.

    Split out of the publish request: this calls the Gemini embedding API, and
    it ran inline inside publish_approved_article behind a bare try/except --
    so a slow embedding delayed the editor's response and a failing one was
    swallowed with a warning and never retried.

    Safe to retry, unlike the pipeline: index_document upserts on article ID,
    and vector work retains durable per-source recovery state.
    """
    from editorial.models import EditorialArticle
    from knowledge_base.services.knowledge_graph import KnowledgeBaseAgent

    try:
        article = EditorialArticle.objects.get(pk=article_id)
    except EditorialArticle.DoesNotExist:
        logger.warning("[embeddings] article %s no longer exists", article_id)
        return {'status': 'missing'}

    category = article.topic.category if article.topic else "General"

    KnowledgeBaseAgent().index_document(
        title=article.title,
        content=article.get_full_markdown_content(),
        doc_type='article',
        metadata={
            "article_id": article.id,
            "blog_post_id": blog_post_id,
            "category": category,
            "slug": article.slug,
        },
    )
    logger.info("[embeddings] indexed article #%s", article_id)
    return {'status': 'indexed', 'article_id': article_id}
