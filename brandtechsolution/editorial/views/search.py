from django.http import JsonResponse
from staff.decorators import capability_required_api
from knowledge_base.services.knowledge_graph import KnowledgeBaseAgent


@capability_required_api('manage_blog')
def semantic_search_api(request):
    """Searches vector knowledge base using pgvector embeddings."""
    q = request.GET.get('q', '')
    if not q:
        return JsonResponse({'results': []})

    agent = KnowledgeBaseAgent()
    docs = agent.semantic_search(q, limit=5)

    results = [{
        'id': d.id,
        'title': d.title,
        'doc_type': d.get_doc_type_display(),
        'content_snippet': d.content[:250],
        'metadata': d.metadata
    } for d in docs]

    return JsonResponse({'query': q, 'results': results, 'search_mode': agent.search_mode})
