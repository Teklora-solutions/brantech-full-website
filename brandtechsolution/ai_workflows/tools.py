"""
RAG tools for retrieving blog posts and projects using pgvector and Django ORM.
"""
from langchain.tools import tool
from django.contrib.auth.models import User
from brandtechsolution.config import config
import logging

logger = logging.getLogger(__name__)


def _handle_search_error(error: Exception, search_type: str) -> str:
    """
    Centralized error handling for search operations.
    
    Args:
        error: The exception that occurred
        search_type: Type of search ("blog posts" or "projects")
    
    Returns:
        User-friendly error message
    """
    error_str = str(error)
    logger.error(f"Error searching {search_type}: {error_str}", exc_info=True)
    
    if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str or "quota" in error_str.lower():
        return f"I'm currently unable to search {search_type} due to API rate limits. Please try again in a moment."
    elif "embed" in error_str.lower() or "embedding" in error_str.lower():
        return f"I'm having trouble accessing the {search_type} search feature at the moment. Please try again later."
    else:
        return f"I encountered an issue searching {search_type}. Please try again or ask about something else."


def get_embeddings():
    """Resolve the active profile and its explicit Google billing route."""
    from ai_workflows.harness.llm import get_embedder
    from knowledge_base.models import EmbeddingSpace
    # Do not cache a model-independent singleton across model cutovers.
    return get_embedder(space=EmbeddingSpace.active())


class _SiteSearch:
    """Semantic search over one kind of site content.

    Replaces two near-identical retrievers that queried `BlogPost.embedding`
    and `Project.embedding` directly. Those columns hold one vector per row
    with no record of which model produced it, so they could not survive a
    change of embedding model -- and they were a second corpus alongside the
    one `Memory` maintains, each half-populated, neither aware of the other.

    Everything now reads the active embedding space, which means these tools
    get the provenance, the re-embedding and the vector index for free.

    `status='published'` used to be applied here, at query time. It is applied
    at write time now -- see `ai_workflows/signals.py` -- because a
    `MemoryDocument` has no status to filter on. That is the stricter of the
    two: an unpublished draft is not in the corpus at all.
    """

    def __init__(self, kind, label):
        self.kind = kind
        self.label = label

    def search(self, query: str, k: int = 3) -> str:
        from ai_workflows.harness.errors import AgentError
        from ai_workflows.harness.memory import Memory

        try:
            records = Memory(scope="site").recall(
                query, kind=self.kind, limit=k, scope="site",
            )
        except AgentError as exc:
            # Distinguished from "nothing found" on purpose. A model told
            # nothing was found will say so confidently; one told the search
            # is down will not.
            logger.warning("[search_%s] memory unavailable: %s", self.kind, exc)
            return (
                f"The {self.label} could not be searched right now. Treat this "
                f"as no information rather than as an absence of {self.label}."
            )
        except Exception as exc:  # noqa: BLE001
            return _handle_search_error(exc, self.label)

        if not records:
            return (
                f"No relevant {self.label} found. Nothing matching that is "
                f"indexed yet."
            )

        # The id is in the output because the assistant is asked for a
        # `sources` block carrying one, and until now had no way to know it --
        # every source it cited came back with `id: null`, so nothing could be
        # linked to the thing it came from. A MemoryDocument knows which row
        # it was built from, so this costs nothing to say.
        return "\n\n---\n\n".join(
            f"{record.title} (id {record.document.object_id}, "
            f"similarity {record.score:.2f})\n{record.text[:500]}"
            for record in records
        )


# Singleton instances
_blog_retriever = None
_project_retriever = None


def get_blog_retriever():
    """Get or create blog retriever instance."""
    global _blog_retriever
    if _blog_retriever is None:
        _blog_retriever = _SiteSearch("blog_post", "blog posts")
    return _blog_retriever


def get_project_retriever():
    """Get or create project retriever instance."""
    global _project_retriever
    if _project_retriever is None:
        _project_retriever = _SiteSearch("project", "projects")
    return _project_retriever


@tool
def search_blog_posts(query: str) -> str:
    """Search blog posts for information about services, technologies, or topics.
    
    Use this when users ask about blog content, articles, or written resources.
    
    Args:
        query: The search query to find relevant blog posts
    """
    blog_tool = get_blog_retriever()
    return blog_tool.search(query)


@tool
def search_projects(query: str) -> str:
    """Search completed projects for information about work done, technologies used, or client projects.
    
    Use this when users ask about past work or project examples.
    
    Args:
        query: The search query to find relevant projects
    """
    project_tool = get_project_retriever()
    return project_tool.search(query)


def create_user_info_tool(user_id: int):
    """
    Create a tool to get user's basic information from the database.
    
    Args:
        user_id: The user ID to fetch information for
        
    Returns:
        A LangChain tool bound to this user_id
    """
    @tool
    def get_user_info() -> str:
        """Get the current user's basic information from the database.
        
        Use this when you need to know the user's name, email, or other account details.
        This tool automatically uses the logged-in user's information.
        
        Returns:
            String containing user's basic information
        """
        try:
            user = User.objects.only('username', 'email', 'first_name', 'last_name', 'date_joined', 'is_active').get(pk=user_id)
            
            info_parts = [
                f"Username: {user.username}",
                f"Email: {user.email}",
            ]
            
            # Add first/last name if available
            if user.first_name:
                info_parts.append(f"First Name: {user.first_name}")
            if user.last_name:
                info_parts.append(f"Last Name: {user.last_name}")
            
            # Add full name if both are available
            if user.first_name and user.last_name:
                info_parts.append(f"Full Name: {user.get_full_name()}")
            
            # Add date joined
            if user.date_joined:
                info_parts.append(f"Member Since: {user.date_joined.strftime('%Y-%m-%d')}")
            
            # Add active status
            info_parts.append(f"Account Active: {'Yes' if user.is_active else 'No'}")
            
            return "\n".join(info_parts)
            
        except User.DoesNotExist:
            return f"User with ID {user_id} not found."
        except Exception as e:
            logger.error(f"Error fetching user info: {e}", exc_info=True)
            return f"Error retrieving user information: {str(e)}"
    
    # Update the tool name to be more descriptive
    get_user_info.name = "get_user_info"
    get_user_info.description = "Get the current logged-in user's basic information (name, email, account details). Use this when you need to personalize responses or reference the user's account."
    
    return get_user_info



@tool
def current_time() -> str:
    """Get the current date and time, in Nairobi time (EAT) and UTC.

    Use this when the answer depends on today's date or the time of day --
    "what's on this week", "how old is that post", anything relative.

    Returns:
        The current date and time.
    """
    from datetime import datetime, timedelta, timezone as dt_timezone

    offset = getattr(config, "timezone_offset", 3)
    now_utc = datetime.now(dt_timezone.utc)
    local = now_utc.astimezone(dt_timezone(timedelta(hours=offset)))

    return (
        f"Nairobi (EAT): {local.strftime('%A %Y-%m-%d %H:%M')}\n"
        f"UTC: {now_utc.strftime('%A %Y-%m-%d %H:%M')}"
    )


@tool
def fetch_url(url: str) -> str:
    """Fetch a web page and return its readable text.

    Use this to check a claim against the source it cites, or to read an
    article you have a link to. Only public http and https pages can be
    fetched.

    Args:
        url: The full URL of the page to read.
    """
    from ai_workflows.harness.fetching import UnsafeURL, fetch

    try:
        final_url, text = fetch(url)
    except UnsafeURL as exc:
        # Returned rather than raised: the model chose this URL and can choose
        # another, and saying why is more useful than a failed run. A refusal
        # is not an outage.
        logger.info("[fetch_url] refused %s: %s", url, exc)
        return f"That URL could not be fetched: {exc}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("[fetch_url] %s failed: %s", url, exc)
        return f"Could not reach that URL: {exc}"

    if not text.strip():
        return f"{final_url} returned no readable text."

    header = f"Fetched: {final_url}" if final_url != url else f"Fetched: {url}"
    return f"{header}\n\n{text}"


@tool
def search_knowledge(query: str) -> str:
    """Search everything the newsroom has already researched and published.

    Use this before asserting something new, to see what has already been
    established and whether it agrees with you. Covers past articles and
    indexed site content.

    Args:
        query: What to look for.
    """
    from ai_workflows.harness.errors import AgentError
    from ai_workflows.harness.memory import Memory

    try:
        # Both corpora, explicitly. The newsroom's own back catalogue is the
        # obvious one; the site content matters too, because a claim already
        # made in a published blog post is a claim this organisation has
        # already stood behind. Naming them beats `scope=None`, which would
        # also pull in anything a future agent happened to store.
        records = Memory(scope="editorial").recall(
            query, limit=5, scope=("editorial", "site"),
        )
    except AgentError as exc:
        # The searchable half of the newsroom being down is worth saying out
        # loud rather than answering "nothing found", which the model would
        # reasonably read as "this is novel".
        logger.warning("[search_knowledge] memory unavailable: %s", exc)
        return (
            "The knowledge base could not be searched right now, so treat this "
            "as no information rather than as an absence of coverage."
        )

    if not records:
        return "Nothing relevant found in the knowledge base."

    return "\n\n---\n\n".join(
        f"{record.title} (similarity {record.score:.2f})\n{record.text[:800]}"
        for record in records
    )
