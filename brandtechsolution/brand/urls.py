from django.urls import path
from . import views, api_views

urlpatterns = [
    path('donate/', views.donate, name='donate'),
    path('', views.index, name='index'),
    path('about/', views.about, name='about'),
    path('careers/', views.careers, name='careers'),
    path('partnerships/', views.partnerships, name='partnerships'),

    # API Endpoints
    path('api/posts/', api_views.post_list, name='api_post_list'),
    path('api/posts/<int:pk>/', api_views.post_detail, name='api_post_detail'),
    path('api/projects/', api_views.project_list, name='api_project_list'),
    path('api/projects/<int:pk>/', api_views.project_detail, name='api_project_detail'),
    path('api/projects/<int:pk>/sync-github/', api_views.project_sync_github, name='api_project_sync_github'),
    path('api/projects/<int:pk>/commits/', api_views.project_commits, name='api_project_commits'),
    
    path('api/github/repos/', api_views.github_repos_list, name='api_github_repos'),
    path('api/github/repos/<int:repo_id>/readme/', api_views.github_repo_readme, name='api_github_repo_readme'),
    path('api/github/account/', api_views.github_account, name='api_github_account'),
    path('api/github/refresh/', api_views.github_refresh, name='api_github_refresh'),
    path('api/github/sync/', api_views.github_sync_selected, name='api_github_sync'),

    path('blog/', views.blog, name='blog'),
    path('blog/<slug:slug>/', views.blog_detail, name='blog_detail'),
    path('api/blogs/<int:post_id>/like/', views.like_blog_post, name='like_blog_post'),
    path('api/blogs/<int:post_id>/comment/', views.comment_blog_post, name='comment_blog_post'),
    path('api/blogs/<int:post_id>/comments/', views.get_blog_comments, name='get_blog_comments'),
    path('blog/post/<int:post_id>/json/', views.blog_json, name='blog_json'),

    path('products/', views.products, name='products'),
    path('projects/', views.projects, name='projects'),
    path('projects/<int:pk>/', views.project_page, name='project_page'),
    path('faq/', views.faq, name='faq'),
    path('contacts/', views.contacts, name='contacts'),
    path('solutions/', views.solutions, name='solutions'),
    path('research/', views.research, name='research'),
    path('admin-panel/', views.admin_panel_page, name='admin-panel'),
    path('admin-panel/site-content/', views.admin_site_content, name='admin-site-content'),
    path('admin-panel/partnerships/', views.admin_partnerships, name='admin-partnerships'),
    path('admin-panel/partnerships/<slug:kind>/new/', views.admin_partnership_edit, name='admin-partnership-new'),
    path('admin-panel/partnerships/<slug:kind>/<int:pk>/', views.admin_partnership_edit, name='admin-partnership-edit'),
    path('admin-panel/partnerships/<slug:kind>/<int:pk>/status/', views.admin_partnership_status, name='admin-partnership-status'),
    path('admin-panel/partnerships/<slug:kind>/<int:pk>/delete/', views.admin_partnership_delete, name='admin-partnership-delete'),
    # No trailing slash: llmstxt.org specifies the file at /llms.txt exactly,
    # and that is the path assistants look for.
    path('llms.txt', views.llms_txt, name='llms_txt'),
    path('developer/setup/', views.developer_agent_setup, name='developer-agent-setup'),
    path('developer/setup.md', views.developer_agent_setup_md, name='developer-agent-setup-md'),
    path('developer/mcp/server.py', views.developer_mcp_script, name='developer-mcp-script'),
    path('developer/skill/SKILL.md', views.developer_skill_file, name='developer-skill-file'),
    path('privacy/', views.privacy_policy, name='privacy'),
    path('terms/', views.terms_conditions, name='terms'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]
