"""Re-embed the corpus into a new space, most important documents first.

Two jobs, and they are the same job. Changing embedding model has been
designed for since the memory layer was built and never implemented; and the
active space is 3072 dimensions, which pgvector cannot index, so every recall
is a sequential scan. A narrower space fixes the second and needs the first.
"""
from django.core.management.base import BaseCommand, CommandError

from brandtechsolution.config import config


class Command(BaseCommand):
    help = "Build a new embedding space, in importance order, within a budget."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model", default=config.gemini_embedding_model,
            help="The embedding model to build the space with.",
        )
        parser.add_argument(
            "--provider", default="gemini",
            help="Embeddings are not multi-provider; this exists to be explicit.",
        )
        parser.add_argument(
            "--dimensions", type=int, default=1536,
            help=(
                "Width of the new space. gemini-embedding-001 is trained with "
                "Matryoshka representation learning, so a narrower width is a "
                "supported truncation. Must be 2000 or less to be indexable."
            ),
        )
        parser.add_argument("--limit", type=int, default=None,
                            help="Embed at most this many documents this run.")
        parser.add_argument("--budget", type=float, default=None,
                            help="Stop below this estimated spend, in USD.")
        parser.add_argument("--scope", default="", help="Only this memory scope.")
        parser.add_argument("--kind", default="", help="Only this document kind.")
        parser.add_argument("--batch", type=int, default=64)
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would be embedded, and what it would cost.",
        )
        parser.add_argument(
            "--activate", action="store_true",
            help="Make the space live once it is fully built.",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Deprecated compatibility flag; activation always requires complete eligible coverage.",
        )
        parser.add_argument(
            "--no-index", action="store_true",
            help="Skip building the vector index for the new space.",
        )
        parser.add_argument(
            "--status", action="store_true",
            help="Show every space and whether its queries can use an index.",
        )

    def handle(self, *args, **options):
        from ai_workflows.harness import reembed
        from knowledge_base import indexes

        if options["status"]:
            self._status()
            return

        dimensions = options["dimensions"]
        if dimensions > indexes.HNSW_MAX_DIMENSIONS:
            self.stdout.write(self.style.WARNING(
                f"{dimensions} dimensions is above pgvector's hnsw limit of "
                f"{indexes.HNSW_MAX_DIMENSIONS}, so this space will not be "
                f"indexable and its queries will be sequential scans."
            ))

        space, created = reembed.target_space(
            options["provider"], options["model"], dimensions,
        )
        self.stdout.write(
            f"{'Created' if created else 'Using'} space #{space.pk}: {space}"
        )

        try:
            plan = reembed.plan(
                space,
                limit=options["limit"],
                budget_usd=options["budget"],
                scope=options["scope"] or None,
                kind=options["kind"] or None,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Plan: {plan.describe()}")
        if plan.deferred:
            self.stdout.write(
                f"      {plan.deferred} document(s) deferred to a later run."
            )

        if not plan.count:
            self.stdout.write(self.style.SUCCESS("Nothing to embed."))
            self._finish(space, options, already_complete=True)
            return

        self._show_choices(plan)

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run; nothing was embedded."))
            return

        report = reembed.execute(
            plan, batch_size=options["batch"],
            on_batch=lambda r: self.stdout.write(
                f"  batch {r.batches}: {r.embedded} embedded, {r.failed} failed",
                ending="\r",
            ),
        )
        self.stdout.write("")

        if report.failed:
            self.stdout.write(self.style.ERROR(
                f"{report.failed} document(s) failed: "
                f"{'; '.join(report.errors[:3])}"
            ))
            self.stdout.write(
                "Re-run to pick up what is left -- progress is which documents "
                "have a vector, so nothing already done is repeated."
            )

        self.stdout.write(self.style.SUCCESS(
            f"Embedded {report.embedded} document(s) into space #{space.pk}."
        ))
        self._finish(space, options)

    def _status(self):
        """Every space, and whether its searches are scans.

        The question nobody could ask before: a sequential scan and an index
        scan look identical from the outside, right up until the corpus is big
        enough for the difference to be the only thing that matters.
        """
        from ai_workflows.harness import reembed
        from knowledge_base import indexes

        rows = indexes.report()
        if not rows:
            self.stdout.write("No embedding spaces exist yet.")
            return

        self.stdout.write("\nEmbedding spaces\n")
        for row in rows:
            space = row["space"]
            outstanding = reembed.pending(space).count()
            state = (
                "indexed" if row["indexed"]
                else ("not built" if row["indexable"] else "CANNOT be indexed")
            )
            self.stdout.write(
                f"  #{space.pk} {space.provider}/{space.model_id} "
                f"{space.dimensions}d [{space.status}] -- "
                f"{row['embeddings']} vector(s), index {state}"
            )
            if row["reason"]:
                self.stdout.write(f"       {row['reason']}")
            if outstanding:
                self.stdout.write(f"       {outstanding} document(s) not embedded here")

    def _show_choices(self, plan):
        """Justify the ordering, so a partial run is not a black box."""
        from ai_workflows.harness.importance import explain

        self.stdout.write("\nMost important first:")
        for document, score in plan.documents[:5]:
            parts = explain(document)
            self.stdout.write(
                f"  {score:6.3f}  {document.title[:44]:<44} "
                f"retrieved {parts['retrievals']:>3}x, "
                f"{parts['age_days']:g}d old"
            )
        if plan.count > 5:
            self.stdout.write(f"  ... and {plan.count - 5} more\n")

    def _finish(self, space, options, already_complete=False):
        from ai_workflows.harness import reembed
        from knowledge_base import indexes

        if not options["no_index"]:
            name = indexes.ensure_index(space)
            if name:
                self.stdout.write(self.style.SUCCESS(f"Index ready: {name}"))
            else:
                self.stdout.write(self.style.WARNING(
                    f"No index: {indexes.why_not(space)}"
                ))

        if not options["activate"]:
            outstanding = reembed.pending(space).count()
            if outstanding:
                self.stdout.write(
                    f"{outstanding} document(s) still to go. Re-run to continue, "
                    f"then pass --activate to cut over."
                )
            else:
                self.stdout.write(
                    "Space is complete. Pass --activate to make it live."
                )
            return

        try:
            reembed.activate(space, require_complete=not options["force"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            f"Space #{space.pk} is now active. The previous space is retired, "
            f"not deleted -- flip back by activating it again if this was wrong."
        ))
