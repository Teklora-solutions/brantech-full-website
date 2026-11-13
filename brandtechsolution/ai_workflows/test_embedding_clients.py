"""Provider contract tests with no credentials, ADC, network, or paid calls."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from ai_workflows.harness.embeddings import GoogleEmbeddingClient, EmbeddingFailure, classify_failure, validate_vector


class EmbeddingClientTests(SimpleTestCase):
    def make_client(self, model='gemini-embedding-001', backend='developer_api', protocol='retrieval_v1'):
        instance = GoogleEmbeddingClient(model=model, backend=backend, protocol=protocol, dimensions=3)
        instance._client = Mock()
        instance._client.models.embed_content.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[3, 4, 0])])
        return instance

    def test_model_001_preserves_separate_document_and_query_task_types(self):
        client = self.make_client()
        self.assertEqual(client.embed_documents(['Synthetic document']), [[0.6, 0.8, 0.0]])
        first = client.client.models.embed_content.call_args.kwargs
        self.assertEqual(first['config'].task_type, 'RETRIEVAL_DOCUMENT')
        client.embed_query('Synthetic query')
        self.assertEqual(client.client.models.embed_content.call_args.kwargs['config'].task_type, 'RETRIEVAL_QUERY')

    def test_legacy_profiles_keep_query_style_documents(self):
        client = self.make_client(protocol='legacy')
        client.embed_documents(['Synthetic document'])
        self.assertEqual(client.client.models.embed_content.call_args.kwargs['config'].task_type, 'RETRIEVAL_QUERY')

    def test_model_2_has_prompt_prefixes_and_no_unsupported_task_type(self):
        client = self.make_client(model='models/gemini-embedding-2')
        client.embed_documents(['First synthetic doc', 'Second synthetic doc'])
        calls = client.client.models.embed_content.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].kwargs['contents'], 'title: none | text: First synthetic doc')
        self.assertIsNone(calls[0].kwargs['config'].task_type)
        self.assertEqual(calls[0].kwargs['config'].output_dimensionality, 3)
        client.embed_query('Synthetic query')
        self.assertEqual(client.client.models.embed_content.call_args.kwargs['contents'], 'task: search result | query: Synthetic query')

    def test_model_2_cannot_reuse_an_incompatible_legacy_protocol(self):
        client = self.make_client(model='gemini-embedding-2', protocol='legacy')
        with self.assertRaises(EmbeddingFailure):
            client.embed_query('Synthetic')
        client.client.models.embed_content.assert_not_called()

    def test_invalid_vectors_are_not_persistable(self):
        for vector in ([0, 0, 0], [1, 2], [1, float('nan'), 0], [float('inf'), 1, 0]):
            with self.subTest(vector=vector), self.assertRaises(EmbeddingFailure):
                validate_vector(vector, 3)

    def test_unexpected_aggregation_is_rejected(self):
        client = self.make_client(model='gemini-embedding-2')
        client.client.models.embed_content.return_value.embeddings *= 2
        with self.assertRaises(EmbeddingFailure) as caught:
            client.embed_query('Synthetic')
        self.assertEqual(caught.exception.code, 'INVALID_EMBEDDING_COUNT')

    def test_vertex_uses_only_explicit_service_account_project_and_route(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'identity.json'
            path.write_text(json.dumps({'project_id': 'sanitized-vertex-project'}))
            settings = SimpleNamespace(google_application_credentials=str(path), vertex_project_id='', vertex_location='global', google_api_key='unused-fake-key')
            credentials = Mock()
            with patch('ai_workflows.harness.embeddings.config', settings), patch('google.oauth2.service_account.Credentials.from_service_account_file', return_value=credentials), patch('google.genai.Client') as factory, patch('google.auth.default', side_effect=AssertionError('ADC must not run')):
                GoogleEmbeddingClient(model='gemini-embedding-001', backend='vertex').client
                kwargs = factory.call_args.kwargs
                self.assertTrue(kwargs['vertexai'])
                self.assertEqual(kwargs['project'], 'sanitized-vertex-project')
                self.assertEqual(kwargs['location'], 'global')
                self.assertNotIn('api_key', kwargs)
                self.assertEqual(kwargs['http_options'].timeout, 15000)
                self.assertEqual(kwargs['http_options'].retry_options.attempts, 1)
                credentials.refresh.assert_called_once()

    def test_vertex_configuration_failure_never_falls_back_to_developer_key(self):
        settings = SimpleNamespace(google_application_credentials='/nonexistent/synthetic-identity.json', vertex_project_id='', vertex_location='global', google_api_key='unused-fake-key')
        with patch('ai_workflows.harness.embeddings.config', settings), patch('google.genai.Client') as factory:
            with self.assertRaises(EmbeddingFailure) as caught:
                GoogleEmbeddingClient(model='gemini-embedding-001', backend='vertex').client
            self.assertEqual(caught.exception.code, 'VERTEX_CREDENTIAL_CONFIGURATION')
            factory.assert_not_called()

    def test_developer_api_is_an_explicit_separate_route(self):
        settings = SimpleNamespace(google_api_key='synthetic-key')
        with patch('ai_workflows.harness.embeddings.config', settings), patch('google.genai.Client') as factory, patch('google.auth.default', side_effect=AssertionError('ADC must not run')):
            GoogleEmbeddingClient(model='gemini-embedding-001', backend='developer_api').client
            self.assertFalse(factory.call_args.kwargs['vertexai'])
            self.assertEqual(factory.call_args.kwargs['api_key'], 'synthetic-key')
            self.assertNotIn('project', factory.call_args.kwargs)

    def test_retry_after_is_bounded_and_errors_do_not_echo_provider_body(self):
        failure = RuntimeError('PRIVATE provider response and credential')
        failure.code = 429
        failure.response = SimpleNamespace(headers={'Retry-After': '999999'})
        safe = classify_failure(failure)
        self.assertEqual(safe.code, 'RATE_LIMIT')
        self.assertTrue(safe.retryable)
        self.assertEqual(safe.retry_after, 3600)
        self.assertNotIn('PRIVATE', str(safe))

    def test_nontransient_permissions_are_not_automatically_retried(self):
        failure = RuntimeError('PRIVATE')
        failure.code = 403
        safe = classify_failure(failure)
        self.assertFalse(safe.retryable)
        self.assertEqual(safe.code, 'AUTHENTICATION_OR_PERMISSION')
