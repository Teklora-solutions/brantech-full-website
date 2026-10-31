"""Tests for AI Touchpoints registry and routing governance."""
from django.test import TestCase
from ai_workflows.models import AITouchpoint
from ai_workflows.harness.touchpoints import (
    register_touchpoint,
    get_or_create_touchpoint_row,
    sync_registered_touchpoints,
)
from ai_workflows.harness.llm import get_model, ModelRole


class TouchpointRegistryTests(TestCase):
    def test_sync_registered_touchpoints_populates_database(self):
        synced = sync_registered_touchpoints()
        self.assertTrue(len(synced) >= 7)
        self.assertTrue(AITouchpoint.objects.filter(key="writer").exists())
        self.assertTrue(AITouchpoint.objects.filter(key="assistant").exists())

    def test_touchpoint_decorator_registers_definition(self):
        @register_touchpoint(
            key="test_summarizer",
            name="Test Document Summarizer",
            description="Summarizes enterprise documents",
            default_role="analytic",
        )
        class DummySummarizer:
            pass

        row = get_or_create_touchpoint_row("test_summarizer")
        self.assertEqual(row.key, "test_summarizer")
        self.assertEqual(row.name, "Test Document Summarizer")
        self.assertEqual(row.description, "Summarizes enterprise documents")

    def test_touchpoint_override_is_honored_in_get_model(self):
        # Create touchpoint pinned to gemini / gemini-2.5-flash
        tp, _ = AITouchpoint.objects.get_or_create(
            key="test_custom_agent",
            defaults={
                "name": "Test Custom Agent",
                "pinned_provider": "gemini",
                "pinned_model": "gemini-2.5-flash",
                "allow_fallback": False,
            }
        )
        from unittest.mock import patch, MagicMock
        from ai_workflows.harness.llm import _BUILDERS, Provider

        mock_gemini = MagicMock()
        mock_client = MagicMock()
        mock_gemini.return_value = mock_client

        with patch.dict(_BUILDERS, {Provider.GEMINI: mock_gemini}):
            client = get_model(ModelRole.PRECISE, touchpoint="test_custom_agent")
            self.assertIs(client, mock_client)
            mock_gemini.assert_called_once()
            args, kwargs = mock_gemini.call_args
            self.assertEqual(args[2], "gemini-2.5-flash")
