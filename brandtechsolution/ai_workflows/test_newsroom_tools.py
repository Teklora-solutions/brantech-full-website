"""Step 9: the tools the newsroom was deliberately not given until now.

Step 4 declared the newsroom suites empty with a note: giving them
`search_knowledge` and `fetch_url` changes what they can *do*, and that belongs
behind its own review. This is that review, and most of it is about `fetch_url`.

`fetch_url` is the only place in this codebase where a network destination is
chosen by model output. The application runs in a compose network with `db`,
`redis` and `cloudflared` addressable by name. A fetcher that resolves whatever
it is handed can read all of that and return it as "research", so the refusals
below are the feature and the fetching is incidental.
"""
from unittest.mock import Mock, patch

from django.test import TestCase

from ai_workflows.harness.fetching import (
    MAX_BYTES,
    UnsafeURL,
    extract_text,
    fetch,
    validate,
)
from ai_workflows.harness.gather import gather
from ai_workflows.harness.tools import SUITES, ToolRegistry, register_builtin_tools


def _resolving_to(*addresses):
    """Pin DNS, so these tests are about the check and not about the network."""
    return patch("ai_workflows.harness.fetching._addresses", return_value=set(addresses))


class SchemeTests(TestCase):
    def test_only_http_and_https_are_fetchable(self):
        for url in (
            "file:///etc/passwd",
            "gopher://redis:6379/_SET%20foo%20bar",
            "ftp://example.com/x",
            "data:text/html,<h1>hi</h1>",
        ):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeURL):
                    validate(url)

    def test_a_url_with_no_host_is_refused(self):
        with self.assertRaises(UnsafeURL):
            validate("http:///just-a-path")

    def test_embedded_credentials_are_refused(self):
        """A redirect-laundering trick with no place in model output."""
        with _resolving_to("93.184.216.34"):
            with self.assertRaises(UnsafeURL):
                validate("https://user:pass@example.com/")

    def test_an_ordinary_public_url_passes(self):
        with _resolving_to("93.184.216.34"):
            self.assertEqual(validate("https://example.com/a"), "https://example.com/a")


class AddressTests(TestCase):
    """Checked after resolution, not by looking at the hostname."""

    REFUSED = [
        ("loopback", "127.0.0.1"),
        ("loopback v6", "::1"),
        ("cloud metadata", "169.254.169.254"),
        ("link local", "169.254.1.1"),
        ("private 10", "10.0.0.5"),
        ("private 172", "172.16.0.5"),
        ("private 192", "192.168.1.1"),
        ("unspecified", "0.0.0.0"),
        ("unique local v6", "fd00::1"),
    ]

    def test_private_and_special_addresses_are_refused(self):
        for label, address in self.REFUSED:
            with self.subTest(label=label):
                with _resolving_to(address):
                    with self.assertRaises(UnsafeURL) as caught:
                        validate("https://anything.example/")
                self.assertIn(address, str(caught.exception))

    def test_a_public_looking_name_resolving_privately_is_refused(self):
        """The bypass that a hostname pattern would miss.

        `localtest.me` resolves to 127.0.0.1 and looks nothing like localhost,
        and an attacker-controlled domain can resolve to whatever it likes.
        """
        with _resolving_to("127.0.0.1"):
            with self.assertRaises(UnsafeURL):
                validate("https://research.example.com/paper")

    def test_every_address_a_name_resolves_to_must_be_public(self):
        """One public and one private A record is a way past a check that only
        looks at the first."""
        with _resolving_to("93.184.216.34", "10.0.0.5"):
            with self.assertRaises(UnsafeURL):
                validate("https://split-horizon.example/")

    def test_the_compose_service_names_are_refused_in_practice(self):
        """Not a synthetic case: these are reachable from the app container."""
        for host in ("localhost", "127.0.0.1"):
            with self.subTest(host=host):
                with self.assertRaises(UnsafeURL):
                    validate(f"http://{host}:6379/")

    def test_an_unresolvable_host_is_refused_rather_than_attempted(self):
        with self.assertRaises(UnsafeURL):
            validate("https://nothing.invalid./x")


def _response(*, status=200, headers=None, body=b"<p>Hi</p>", url="https://example.com/a"):
    response = Mock()
    response.status_code = status
    response.headers = headers or {"Content-Type": "text/html"}
    response.is_redirect = status in (301, 302, 303, 307, 308)
    response.is_permanent_redirect = status in (301, 308)
    response.url = url
    response.encoding = "utf-8"
    response.iter_content = lambda chunk_size=None: iter([body])
    response.raise_for_status = Mock()
    response.close = Mock()
    return response


class RedirectTests(TestCase):
    """Every hop re-validated, because validating only the first is the
    classic bypass: the server answers 302 to http://169.254.169.254/."""

    def test_a_redirect_to_a_private_address_is_refused(self):
        hops = [
            _response(status=302, headers={"Location": "http://169.254.169.254/latest/meta-data/"}),
        ]
        with _resolving_to("93.184.216.34") as addresses:
            addresses.side_effect = lambda host: (
                {"169.254.169.254"} if "169.254" in host else {"93.184.216.34"}
            )
            with patch("requests.get", side_effect=hops):
                with self.assertRaises(UnsafeURL) as caught:
                    fetch("https://example.com/a")

        self.assertIn("169.254.169.254", str(caught.exception))

    def test_a_redirect_to_another_public_page_is_followed(self):
        hops = [
            _response(status=302, headers={"Location": "https://example.com/b"}),
            _response(body=b"<p>The article</p>", url="https://example.com/b"),
        ]
        with _resolving_to("93.184.216.34"), patch("requests.get", side_effect=hops):
            final, text = fetch("https://example.com/a")

        self.assertEqual(final, "https://example.com/b")
        self.assertIn("The article", text)

    def test_a_redirect_loop_is_refused(self):
        def looping(url, **kwargs):
            other = "https://example.com/b" if url.endswith("/a") else "https://example.com/a"
            return _response(status=302, headers={"Location": other})

        with _resolving_to("93.184.216.34"), patch("requests.get", side_effect=looping):
            with self.assertRaises(UnsafeURL) as caught:
                fetch("https://example.com/a")

        self.assertIn("loop", str(caught.exception))

    def test_a_redirect_with_no_destination_is_refused(self):
        with _resolving_to("93.184.216.34"), \
                patch("requests.get", return_value=_response(status=302, headers={})):
            with self.assertRaises(UnsafeURL):
                fetch("https://example.com/a")


class BodyTests(TestCase):
    def test_a_non_text_content_type_is_refused(self):
        response = _response(headers={"Content-Type": "application/octet-stream"})
        with _resolving_to("93.184.216.34"), patch("requests.get", return_value=response):
            with self.assertRaises(UnsafeURL):
                fetch("https://example.com/a")

    def test_the_body_is_capped_whatever_content_length_claims(self):
        """Streamed and counted rather than trusted: the header is the server's
        word for it, and the server was chosen by a model."""
        response = _response(
            body=b"x" * (MAX_BYTES * 2),
            headers={"Content-Type": "text/plain", "Content-Length": "12"},
        )
        with _resolving_to("93.184.216.34"), patch("requests.get", return_value=response):
            _, text = fetch("https://example.com/a")

        self.assertLessEqual(len(text), MAX_BYTES)


class ExtractionTests(TestCase):
    def test_script_and_style_contents_do_not_survive(self):
        """The regex in messaging.rendering strips tags but keeps what is
        inside them, which on a real page means every script arrives as prose."""
        html = (
            "<html><head><style>.a{color:red}</style>"
            "<script>var secret = 'tracking';</script></head>"
            "<body><h1>The headline</h1><p>The body.</p></body></html>"
        )
        text = extract_text(html, "text/html")

        self.assertIn("The headline", text)
        self.assertIn("The body.", text)
        self.assertNotIn("tracking", text)
        self.assertNotIn("color:red", text)

    def test_plain_text_is_passed_through(self):
        self.assertEqual(extract_text("Just words.", "text/plain"), "Just words.")

    def test_malformed_html_does_not_raise(self):
        self.assertIn("Dangling", extract_text("<p>Dangling<<<", "text/html"))


class FetchToolTests(TestCase):
    """The tool wrapper answers the model rather than failing the run."""

    def _fetch_url(self):
        return register_builtin_tools(ToolRegistry()).resolve(["fetch_url"])[0]

    def test_a_refusal_is_explained_not_raised(self):
        """The model chose this URL and can choose another. A refusal is not
        an outage."""
        answer = self._fetch_url().invoke({"url": "file:///etc/passwd"})
        self.assertIn("could not be fetched", answer)

    def test_a_transport_failure_is_explained_too(self):
        import requests

        with _resolving_to("93.184.216.34"), \
                patch("requests.get", side_effect=requests.ConnectionError("refused")):
            answer = self._fetch_url().invoke({"url": "https://example.com/a"})

        self.assertIn("Could not reach", answer)

    def test_a_successful_fetch_names_the_url_it_read(self):
        with _resolving_to("93.184.216.34"), \
                patch("requests.get", return_value=_response(body=b"<p>Content here</p>")):
            answer = self._fetch_url().invoke({"url": "https://example.com/a"})

        self.assertIn("https://example.com/a", answer)
        self.assertIn("Content here", answer)


class KnowledgeToolTests(TestCase):
    def _search(self):
        return register_builtin_tools(ToolRegistry()).resolve(["search_knowledge"])[0]

    def test_an_unavailable_knowledge_base_is_not_reported_as_an_empty_one(self):
        """"Nothing found" reads as "this is novel", which is the opposite of
        what a broken index means."""
        from ai_workflows.harness.errors import MemoryUnavailable

        with patch("ai_workflows.harness.memory.Memory.recall",
                   side_effect=MemoryUnavailable("no space")):
            answer = self._search().invoke({"query": "agents"})

        self.assertIn("could not be searched", answer)
        self.assertNotIn("Nothing relevant", answer)

    def test_an_empty_result_says_so_plainly(self):
        with patch("ai_workflows.harness.memory.Memory.recall", return_value=[]):
            self.assertIn("Nothing relevant", self._search().invoke({"query": "x"}))

    def test_results_carry_their_similarity(self):
        record = Mock(title="A past article", text="Body text.", score=0.91)
        with patch("ai_workflows.harness.memory.Memory.recall", return_value=[record]):
            answer = self._search().invoke({"query": "x"})

        self.assertIn("A past article", answer)
        self.assertIn("0.91", answer)


class SuiteTests(TestCase):
    """Who was given what, and who deliberately was not."""

    def test_the_verifier_can_check_claims_against_something_outside_itself(self):
        """Until step 9 it asked a language model whether it believed itself."""
        self.assertEqual(SUITES["fact_verifier"], ["search_knowledge", "fetch_url", "search_public_library"])

    def test_the_researcher_can_read_the_sources_it_cites(self):
        self.assertIn("fetch_url", SUITES["research"])

    def test_the_writer_cannot_fetch(self):
        """It drafts from the verified report. New material at the drafting
        stage is how an unsupported claim gets back in after the verifier
        removed it."""
        self.assertNotIn("fetch_url", SUITES["writer"])
        self.assertIn("search_knowledge", SUITES["writer"])

    def test_the_social_agent_gets_nothing(self):
        """It adapts an article that is already written and verified; a tool
        could only add something the article does not say."""
        self.assertEqual(SUITES["social"], [])

    def test_every_suite_still_names_only_registered_tools(self):
        registry = register_builtin_tools(ToolRegistry())
        for agent, names in SUITES.items():
            for name in names:
                self.assertIn(name, registry, f"{agent} names an unregistered tool")


class FakeTool:
    def __init__(self, name, result="a result"):
        self.name = name
        self.result = result
        self.calls = []

    def invoke(self, args):
        self.calls.append(args)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _model(*turns):
    """A model that returns each turn in sequence."""
    model = Mock()
    model.invoke = Mock(side_effect=list(turns))
    return model


def _turn(content="", tool_calls=()):
    message = Mock()
    message.content = content
    message.tool_calls = list(tool_calls)
    return message


from ai_workflows.harness.retrying import NEVER


class GatherTests(TestCase):
    """The bounded tool loop that sits before `ask`."""

    def _gather(self, model, tools, **kwargs):
        return self._gather_over([model], tools, **kwargs)

    def _gather_over(self, models, tools, **kwargs):
        """Run the loop over a preference order of `models`.

        The fake stands in for `iter_models`, so a test can hand the loop a
        second provider and watch it move across -- which is the behaviour a
        single client could not express.
        """
        from ai_workflows.harness.llm import Provider

        names = [Provider.GEMINI, Provider.OPENROUTER, Provider.ANTHROPIC]

        def candidates(*args, **kwargs):
            for name, model in zip(names, models):
                yield name, model

        # These tests are about moving between providers, so nothing waits.
        # A refusal that clears on its own is a different question, answered
        # in test_retrying -- and left on, the default policy would make the
        # fixtures below sleep out a real rate-limit window.
        kwargs.setdefault("policy", NEVER)

        with patch("ai_workflows.harness.gather.iter_models", new=candidates):
            return gather(None, "check this", tools, agent="test", **kwargs)

    def test_no_tools_means_no_call_at_all(self):
        """An agent with an empty suite must not pay for a round trip."""
        with patch("ai_workflows.harness.gather.iter_models") as iter_models:
            self.assertEqual(gather(None, "brief", []), "")
        iter_models.assert_not_called()

    def test_a_tool_result_reaches_the_transcript(self):
        tool = FakeTool("fetch_url", "The page said X.")
        model = _model(
            _turn(tool_calls=[{"name": "fetch_url", "args": {"url": "https://e.com"},
                               "id": "1"}]),
            _turn("The source supports X."),
        )
        evidence = self._gather(model, [tool])

        self.assertIn("The page said X.", evidence)
        self.assertIn("The source supports X.", evidence)
        self.assertEqual(tool.calls, [{"url": "https://e.com"}])

    def test_a_tool_that_raises_is_a_fact_about_that_lookup(self):
        """Not about the run. The agent should know and carry on."""
        tool = FakeTool("fetch_url", RuntimeError("timed out"))
        model = _model(
            _turn(tool_calls=[{"name": "fetch_url", "args": {}, "id": "1"}]),
            _turn("I could not read that source."),
        )
        evidence = self._gather(model, [tool])

        self.assertIn("That lookup failed", evidence)
        self.assertIn("could not read", evidence)

    def test_asking_for_a_tool_it_was_not_given_is_answered_not_fatal(self):
        model = _model(
            _turn(tool_calls=[{"name": "run_sql", "args": {}, "id": "1"}]),
            _turn("Understood."),
        )
        evidence = self._gather(model, [FakeTool("fetch_url")])

        self.assertIn("No tool named 'run_sql'", evidence)

    def test_the_loop_is_bounded(self):
        """A tool loop with no ceiling is an unbounded bill."""
        tool = FakeTool("fetch_url")
        forever = [
            _turn(tool_calls=[{"name": "fetch_url", "args": {}, "id": str(i)}])
            for i in range(10)
        ]
        model = _model(*forever)
        self._gather(model, [tool], max_steps=3)

        self.assertEqual(model.invoke.call_count, 3)

    def test_a_model_that_uses_no_tools_still_reports(self):
        """Not every claim needs a source fetched to check it."""
        model = _model(_turn("I already know this is standard."))
        self.assertIn("standard", self._gather(model, [FakeTool("fetch_url")]))

    def test_a_failed_gathering_step_raises(self):
        """Proceeding on an empty string would be the fallback pattern again."""
        from ai_workflows.harness.errors import ToolFailed

        model = Mock()
        model.invoke = Mock(side_effect=RuntimeError("the model fell over"))

        with self.assertRaises(ToolFailed):
            self._gather(model, [FakeTool("fetch_url")])

    def test_an_exhausted_provider_moves_to_the_next_one(self):
        """The defect a live eval run found: a 429 arrives at invoke time.

        The client built fine, so `get_model` had nothing to report and the
        whole gathering step -- and the writer with it -- died on one spent
        quota while other providers sat unused.
        """
        exhausted = Mock()
        exhausted.invoke = Mock(side_effect=RuntimeError("429 RESOURCE_EXHAUSTED"))
        working = _model(_turn("I checked, and it holds up."))

        evidence = self._gather_over([exhausted, working], [FakeTool("fetch_url")])

        self.assertIn("it holds up", evidence)
        self.assertEqual(working.invoke.call_count, 1)

    def test_a_provider_that_failed_is_not_offered_again(self):
        """It does not recover in the second between two calls.

        Re-offering it would spend the step budget rediscovering the same
        outage instead of gathering evidence.
        """
        exhausted = Mock()
        exhausted.invoke = Mock(side_effect=RuntimeError("429"))
        tool = FakeTool("fetch_url")
        working = _model(
            _turn(tool_calls=[{"name": "fetch_url", "args": {}, "id": "1"}]),
            _turn("Done."),
        )

        self._gather_over([exhausted, working], [tool], max_steps=3)

        self.assertEqual(exhausted.invoke.call_count, 1)

    def test_a_provider_can_fail_part_way_through_the_loop(self):
        """A quota runs out mid-gather, not only on the first call.

        The transcript already collected stays: it is evidence that was really
        gathered, and throwing it away would lose work that cost money.
        """
        tool = FakeTool("fetch_url", "The page said X.")
        first = Mock()
        first.invoke = Mock(side_effect=[
            _turn(tool_calls=[{"name": "fetch_url", "args": {}, "id": "1"}]),
            RuntimeError("429 RESOURCE_EXHAUSTED"),
        ])
        second = _model(_turn("The source supports X."))

        evidence = self._gather_over([first, second], [tool], max_steps=4)

        self.assertIn("The page said X.", evidence)
        self.assertIn("The source supports X.", evidence)

    def test_every_provider_failing_names_all_of_them(self):
        """An aggregate that says only "it failed" sends nobody anywhere."""
        from ai_workflows.harness.errors import ToolFailed

        def dead(message):
            model = Mock()
            model.invoke = Mock(side_effect=RuntimeError(message))
            return model

        with self.assertRaises(ToolFailed) as caught:
            self._gather_over(
                [dead("429 exhausted"), dead("401 revoked")],
                [FakeTool("fetch_url")],
            )

        detail = str(caught.exception)
        self.assertIn("gemini", detail)
        self.assertIn("openrouter", detail)
        self.assertIn("429 exhausted", detail)
        self.assertIn("401 revoked", detail)

    def test_a_pinned_run_refuses_to_drift(self):
        """`allow_fallback=False` means this model or nothing.

        An eval comparing runs pins the model on purpose; answering from a
        different one would compare two different questions.
        """
        from ai_workflows.harness.errors import ToolFailed

        exhausted = Mock()
        exhausted.invoke = Mock(side_effect=RuntimeError("429"))
        working = _model(_turn("I could have answered."))

        with self.assertRaises(ToolFailed):
            self._gather_over(
                [exhausted, working], [FakeTool("fetch_url")], allow_fallback=False,
            )

        working.invoke.assert_not_called()

    def test_tool_output_is_truncated_before_it_reaches_the_context(self):
        from ai_workflows.harness.gather import MAX_RESULT_CHARS

        tool = FakeTool("fetch_url", "x" * (MAX_RESULT_CHARS * 2))
        model = _model(
            _turn(tool_calls=[{"name": "fetch_url", "args": {}, "id": "1"}]),
            _turn("Done."),
        )
        evidence = self._gather(model, [tool])

        self.assertLess(len(evidence), MAX_RESULT_CHARS * 1.5)

    def test_a_truncated_result_says_so(self):
        """A model handed a silently cut page reads what it never saw as
        absent: the verifier called a correct spec unsupported because the
        table sat past the cut."""
        from ai_workflows.harness.gather import MAX_RESULT_CHARS

        tool = FakeTool("fetch_url", "x" * (MAX_RESULT_CHARS * 2))
        model = _model(
            _turn(tool_calls=[{"name": "fetch_url", "args": {}, "id": "1"}]),
            _turn("Done."),
        )
        evidence = self._gather(model, [tool])

        self.assertIn("this result was truncated", evidence)

    def test_the_gather_cap_does_not_undercut_the_fetcher(self):
        """Two limits on one page is one limit nobody chose."""
        from ai_workflows.harness.fetching import MAX_CHARS
        from ai_workflows.harness.gather import MAX_RESULT_CHARS

        self.assertGreaterEqual(MAX_RESULT_CHARS, MAX_CHARS)


class WiringTests(TestCase):
    """A suite an agent never resolves is a tool on paper only."""

    def _gathered(self, agent_class, build):
        """The brief an agent actually sends to its tools, or None."""
        from editorial.tests.fakes import fake_gemini

        with patch.object(agent_class, "gather_evidence", return_value="") as gather:
            with fake_gemini():
                build()
        return gather.call_args[0][0] if gather.call_args else None

    def test_the_verifier_gathers_before_it_judges(self):
        from editorial.models.research import ResearchDossier
        from editorial.services.research.fact_verifier import FactVerificationAgent
        from editorial.models.trends import TrendTopic

        topic = TrendTopic.objects.create(
            title="A topic", summary="A summary.", source="HN",
            source_url="https://example.com/a", category="AI",
        )
        dossier = ResearchDossier.objects.create(
            topic=topic, technical_explanations="How it works.",
            african_opportunities="Regional.", structured_dossier="# D",
            sources=[{"title": "S", "url": "https://example.com/s"}],
        )

        brief = self._gathered(
            FactVerificationAgent,
            lambda: FactVerificationAgent().verify_dossier(dossier),
        )
        self.assertIsNotNone(brief)
        self.assertIn("https://example.com/s", brief)

    def test_the_researcher_gathers_before_it_writes_anything_down(self):
        from editorial.services.research.investigator import ResearchAgent
        from editorial.models.trends import TrendTopic

        topic = TrendTopic.objects.create(
            title="A topic", summary="A summary.", source="HN",
            source_url="https://example.com/a", category="AI",
        )

        brief = self._gathered(
            ResearchAgent, lambda: ResearchAgent().conduct_research(topic),
        )
        self.assertIsNotNone(brief)
        self.assertIn("https://example.com/a", brief)

    def test_the_writer_looks_for_continuity_not_for_material(self):
        """It is given search_knowledge and not fetch_url, and the brief has to
        match: new facts at the drafting stage are how an unsupported claim
        gets back in after the verifier removed it."""
        from editorial.services.writer import AIWriterAgent
        from editorial.models.research import ResearchDossier, VerifiedFactReport
        from editorial.models.trends import TrendTopic

        topic = TrendTopic.objects.create(
            title="A topic", summary="A summary.", source="HN", category="AI",
        )
        dossier = ResearchDossier.objects.create(
            topic=topic, technical_explanations="How.", african_opportunities="R",
            structured_dossier="# D", sources=[],
        )
        report = VerifiedFactReport.objects.create(
            dossier=dossier, confidence_level=0.9, verified_dossier="Verified body.",
            is_approved=True,
        )

        brief = self._gathered(
            AIWriterAgent, lambda: AIWriterAgent().write_article(report, {}),
        )
        self.assertIsNotNone(brief)
        self.assertIn("already published", brief)
        # Collapsed, because the brief is wrapped and the assertion is about
        # what it says rather than where the lines break.
        self.assertIn("not go looking for new facts", " ".join(brief.split()))

    def test_an_agent_with_an_empty_suite_gathers_nothing(self):
        """The social agent adapts an article that is already verified."""
        from editorial.services.social import MultiPlatformContentAgent

        self.assertEqual(MultiPlatformContentAgent().gather_evidence("anything"), "")
