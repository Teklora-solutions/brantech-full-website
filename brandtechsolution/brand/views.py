import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import models
from django.db.models import F, Count
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from brandtechsolution import turnstile
from brandtechsolution.ratelimit import client_ip as _client_ip, rate_limited as _rate_limited
from . import login_throttle
from staff.context_processors import held_capabilities
from .models import BlogPost, BlogLike, BlogComment, Project, SiteContent, Career, PartnershipType, PartnerOrganisation, careers_address
from .forms import CareerForm, PartnerOrganisationForm, PartnershipTypeForm, SiteContentForm
from .markdown_utils import render_markdown


def is_admin(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def can_manage_site_content(user):
    if not is_admin(user):
        return False
    _, can = held_capabilities(user)
    return bool(getattr(can, 'manage_staff', False))


def _published_post_or_404(post_id):
    """Look up a post by id, refusing anything not published.

    Every public entry point must go through this. The lookups here take an
    integer primary key straight from the URL, so without the status filter a
    visitor can walk the id space and reach drafts -- and the editorial
    pipeline keeps a standing queue of generated drafts awaiting approval.
    blog_detail() has always filtered on status; these paths had not.
    """
    return get_object_or_404(BlogPost, pk=post_id, status='published')


def index(request):
    """Home page view"""
    return render(request, 'brand/index.html')


def about(request):
    """About page view"""
    return render(request, 'brand/about.html')


def careers(request):
    """Careers page view – now pulls open positions from the admin"""
    career_list = Career.objects.filter(status=Career.STATUS_OPEN)
    return render(request, 'brand/careers.html', {
        'career_list': career_list,
        'careers_email': careers_address(),
    })


def partnerships(request):
    """Standalone Partnerships page.

    Fetches all partnership types (ordered by status then order field) and
    featured partner organisations so admins can control everything without
    touching code.
    """
    open_types   = PartnershipType.objects.filter(status=PartnershipType.STATUS_OPEN)
    closed_types = PartnershipType.objects.filter(status=PartnershipType.STATUS_CLOSED)
    featured_partners = PartnerOrganisation.objects.filter(featured=True)
    all_partners      = PartnerOrganisation.objects.all()
    return render(request, 'brand/partnerships.html', {
        'open_types':       open_types,
        'closed_types':     closed_types,
        'featured_partners': featured_partners,
        'all_partners':      all_partners,
    })


def products(request):
    """The deep product showcase.

    Renders the Project rows flagged `showcase`, grouped into the three phase
    bands the page has always shown. The six products used to be written into
    products.html by hand; the template is now a loop over these rows and the
    per-product theming (accent, badge, headings, chart) travels with the row.

    prefetch_related covers gallery, features and notes because the template
    walks all three for every card -- without it a six-product page costs
    nineteen queries.
    """
    showcase = (
        Project.objects
        .filter(showcase=True)
        .order_by('display_order', 'title')
        .prefetch_related('gallery', 'features', 'notes')
    )

    groups = []
    for key, _label in Project.PHASE_CHOICES:
        items = [p for p in showcase if p.phase == key]
        if not items:
            continue
        dot_color, dot_animation = Project.PHASE_DOTS[key]
        groups.append({
            'key': key,
            'heading': Project.PHASE_GROUP_HEADINGS[key],
            'dot': dot_color,
            'dot_animation': dot_animation,
            'tab_label': Project.PHASE_TAB_LABELS[key],
            'icon': Project.PHASE_ICONS.get(key, ''),
            'items': items,
            'count': len(items),
        })

    # One blob for every chart on the page rather than a <script> per card,
    # so the template holds no executable JSON.
    charts = {p.slug: p.chart_spec for p in showcase if p.chart_spec}

    return render(request, 'brand/products.html', {
        'groups': groups,
        'total': len(showcase),
        'charts': charts,
    })


def donate(request):
    """Donate page view"""
    return render(request, 'brand/donate.html')


def research(request):
    """Research & Engineering Tech Innovation page view"""
    return render(request, 'brand/research.html')


def faq(request):
    """FAQ page view"""
    return render(request, 'brand/faq.html')


def contacts(request):
    """Contact page view"""
    return render(request, 'brand/contacts.html')


def solutions(request):
    """Solutions page view"""
    return render(request, 'brand/solutions.html')


def privacy_policy(request):
    """Privacy Policy page view"""
    return render(request, 'brand/privacy.html')


def terms_conditions(request):
    """Terms & Conditions page view"""
    return render(request, 'brand/terms.html')


def llms_txt(request):
    """/llms.txt - a curated index of this site for language models.

    The llmstxt.org convention: a short markdown file naming the pages worth
    reading, so an assistant answering questions about Teklora works from the
    pages we chose rather than whatever fragments a crawler happened to keep.

    Rendered rather than served as a static file so every link comes from
    {% url %} and the blog list is the real one. A hand-maintained copy would
    start rotting the first time a route moved.

    Served as text/plain: browsers display it instead of downloading it, which
    matters because people do open this by hand to see what it says. The
    convention names the file .txt and its body is markdown either way.

    Note this is advisory. It is not an access control - the "not for
    indexing" section asks politely, while staff.decorators and the API
    permission classes are what actually refuse.
    """
    posts = (
        BlogPost.objects.filter(status='published')
        .only('title', 'slug', 'excerpt')
        .order_by('-created_at')[:20]
    )
    return render(
        request,
        'brand/llms.txt',
        {'base': settings.SITE_BASE_URL.rstrip('/'), 'posts': posts},
        content_type='text/plain; charset=utf-8',
    )



def blog(request):
    """Blog list page (server-rendered, paginated, sorted)."""
    sort_by = request.GET.get('sort', 'latest')
    
    queryset = BlogPost.objects.filter(status='published').annotate(
        likes_count=Count('likes', distinct=True),
        comments_count=Count('comments', distinct=True)
    )
    
    if sort_by == 'popular':
        queryset = queryset.order_by('-likes_count', '-created_at')
    else:
        queryset = queryset.order_by('-created_at')
        
    paginator = Paginator(queryset, 9)
    posts = paginator.get_page(request.GET.get("page"))
    return render(request, 'brand/blog.html', {
        'posts': posts,
        'sort_by': sort_by,
    })


def blog_detail(request, slug):
    """Server-rendered individual blog post at /blog/<slug>/."""
    post = get_object_or_404(BlogPost, slug=slug, status='published')
    BlogPost.objects.filter(pk=post.pk).update(view_count=F('view_count') + 1)
    content_html = render_markdown(post.content)
    
    likes_count = post.likes.count()
    comments = post.comments.filter(is_approved=True)
    
    return render(request, 'brand/blog_detail.html', {
        'post': post,
        'content_html': content_html,
        'likes_count': likes_count,
        'comments': comments,
    })


@login_required(login_url='/login/')
@user_passes_test(is_admin, login_url='/login/')
def admin_panel_page(request):
    """The panel shell.

    `capabilities` is the held set, serialised to JavaScript via json_script;
    `can` is the same set as an object so templates can write `{% if can.x %}`.
    Superusers pass has_perm() unconditionally, so they hold everything.
    This gating is cosmetic - each API enforces its own capability.

    Both come from staff.context_processors, which supplies them to every
    template extending admin_base.html. They are passed explicitly here as
    well so this view still renders correctly if it is ever called with a
    context that bypasses the processors - and so the single implementation
    of "what does this user hold" stays in one place.
    """
    held, can = held_capabilities(request.user)
    return render(request, 'brand/admin_panel.html', {
        'capabilities': held,
        'can': can,
    })


@login_required(login_url='/login/')
@user_passes_test(can_manage_site_content, login_url='/login/')
def admin_site_content(request):
    """Edit the shared header, footer, and current landing-page sections."""
    content = SiteContent.objects.filter(pk=1).first() or SiteContent()
    if request.method == 'POST':
        form = SiteContentForm(request.POST, instance=content)
        if form.is_valid():
            form.save()
            messages.success(request, 'Site content saved and published.')
            return redirect('admin-site-content')
    else:
        form = SiteContentForm(instance=content)
    return render(request, 'brand/admin_site_content.html', {'form': form})


# Partnerships & People: one tab per record type behind /partnerships/ and
# /careers/. The slug is the tab name in the URL.
PARTNERSHIP_KINDS = {
    'tracks': {
        'model': PartnershipType, 'form': PartnershipTypeForm,
        'tab': 'Partnership tracks', 'short': 'Tracks', 'noun': 'track', 'icon': 'fa-route',
        'public_url': '/partnerships/',
    },
    'partners': {
        'model': PartnerOrganisation, 'form': PartnerOrganisationForm,
        'tab': 'Partners', 'short': 'Partners', 'noun': 'partner', 'icon': 'fa-building',
        'public_url': '/partnerships/',
    },
    'jobs': {
        'model': Career, 'form': CareerForm,
        'tab': 'Job openings', 'short': 'Jobs', 'noun': 'job opening', 'icon': 'fa-briefcase',
        'public_url': '/careers/',
    },
}


def _partnership_kind(request, kind):
    """Refuse anyone Website Content would refuse, then resolve the tab."""
    if not can_manage_site_content(request.user):
        raise PermissionDenied
    try:
        return PARTNERSHIP_KINDS[kind]
    except KeyError:
        raise Http404('Unknown section')


def _record_name(record):
    # PartnershipType.__str__ appends its status, which reads oddly in a message.
    return getattr(record, 'title', None) or record.name


def _partnerships_url(kind):
    return f"{reverse('admin-partnerships')}?tab={kind}"


@login_required(login_url='/login/')
def admin_partnerships(request):
    """List partnership tracks, partners or job openings, one tab at a time."""
    kind = request.GET.get('tab', 'tracks')
    if kind not in PARTNERSHIP_KINDS:
        kind = 'tracks'
    config = _partnership_kind(request, kind)
    tabs = [
        {'slug': slug, 'label': c['tab'], 'short': c['short'], 'icon': c['icon'], 'count': c['model'].objects.count()}
        for slug, c in PARTNERSHIP_KINDS.items()
    ]
    return render(request, 'brand/admin_partnerships.html', {
        'kind': kind,
        'config': config,
        'tabs': tabs,
        'records': config['model'].objects.all(),
    })


@login_required(login_url='/login/')
def admin_partnership_edit(request, kind, pk=None):
    """Add a record when pk is None, otherwise edit it."""
    config = _partnership_kind(request, kind)
    instance = get_object_or_404(config['model'], pk=pk) if pk else None
    if request.method == 'POST':
        form = config['form'](request.POST, request.FILES, instance=instance)
        if form.is_valid():
            record = form.save()
            verb = 'saved' if instance else 'added'
            messages.success(request, f'"{_record_name(record)}" {verb}.')
            return redirect(_partnerships_url(kind))
    else:
        form = config['form'](instance=instance)
    return render(request, 'brand/admin_partnership_form.html', {
        'kind': kind,
        'config': config,
        'form': form,
        'record': instance,
    })


@login_required(login_url='/login/')
@require_POST
def admin_partnership_status(request, kind, pk):
    """Close a track or job opening, or reopen it; hide a partner, or show it.

    A closed track moves to the archived list on /partnerships/, a closed job
    leaves /careers/ and answers anyone who still applies with an
    applications-closed email, and a hidden partner leaves the partners strip.
    """
    config = _partnership_kind(request, kind)
    record = get_object_or_404(config['model'], pk=pk)
    name = _record_name(record)
    if kind == 'partners':
        record.featured = not record.featured
        record.save(update_fields=['featured'])
        done = 'shown on the partnerships page' if record.featured else 'hidden from the partnerships page'
    else:
        record.status = record.STATUS_CLOSED if record.status == record.STATUS_OPEN else record.STATUS_OPEN
        record.save()
        if record.status == record.STATUS_OPEN:
            done = f'reopened and back on {config["public_url"]}'
        elif kind == 'jobs':
            done = 'closed. Anyone who still applies is told applications have closed'
        else:
            done = 'closed and moved to the archived tracks'
    messages.success(request, f'"{name}" {done}.')
    return redirect(_partnerships_url(kind))


@login_required(login_url='/login/')
@require_POST
def admin_partnership_delete(request, kind, pk):
    config = _partnership_kind(request, kind)
    record = get_object_or_404(config['model'], pk=pk)
    name = _record_name(record)
    record.delete()
    messages.success(request, f'"{name}" deleted.')
    return redirect(_partnerships_url(kind))


def projects(request):
    """Projects page view - public access"""
    return render(request, 'brand/projects.html')


def project_page(request, pk):
    """Single project detail page."""
    project = get_object_or_404(Project, pk=pk)
    return render(request, 'brand/project_detail.html', {'project': project})


def signup_view(request):
    """User signup view"""
    if request.method == 'POST':
        # Signup mints real User rows on a public URL, so it is the endpoint
        # a script would use to fill the auth table. Each one also costs a
        # password hash, so solved challenges are capped per address too.
        if _rate_limited(request, 'signup', limit=5, window_seconds=60 * 60):
            messages.error(request, 'Too many sign-ups from your network. Please try again later.')
            return render(request, 'brand/signup.html', status=429)
        if not turnstile.passed(request):
            messages.error(request, turnstile.FAILED)
            return render(request, 'brand/signup.html')

        first_name = request.POST.get('firstName')
        last_name = request.POST.get('lastName')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirmPassword')
        
        # Validation
        if not all([first_name, last_name, email, password, confirm_password]):
            messages.error(request, 'Please fill in all fields.')
            return render(request, 'brand/signup.html')
        
        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'brand/signup.html')
        
        # Check if user exists with this email or username in a single query
        if User.objects.filter(models.Q(email=email) | models.Q(username=email)).exists():
            messages.error(request, 'An account with this email already exists.')
            return render(request, 'brand/signup.html')
        
        # Create user. Sign-up is closed: the account starts deactivated, so
        # it cannot sign in until someone with manage_staff invites the
        # address and the invitation is accepted (staff/signups.py).
        try:
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                is_active=False,
            )
            messages.success(
                request,
                'Your account has been created but is not active yet. '
                'An administrator will send you an invitation to finish setting it up.',
            )
            return redirect('login')
        except Exception as e:
            messages.error(request, f'Error creating account: {str(e)}')
            return render(request, 'brand/signup.html')
    
    return render(request, 'brand/signup.html')


def _login_user_for(identifier):
    """The account an identifier names, or None.

    An exact username match wins; otherwise the personal email, the handle in
    any case, or the work address <handle>@MAILBOX_DOMAIN. Resolving it once
    up front means a sign-in hashes the password once - the old flow tried
    authenticate() twice and so paid for two hashes on every wrong password.
    """
    exact = User.objects.filter(username=identifier).first()
    if exact:
        return exact
    handle = identifier
    domain_suffix = '@' + settings.MAILBOX_DOMAIN
    if identifier.lower().endswith(domain_suffix.lower()):
        handle = identifier[:-len(domain_suffix)]
    return User.objects.filter(
        models.Q(username__iexact=handle) | models.Q(email__iexact=identifier)
    ).first()


def login_view(request):
    """User login view"""
    ip = _client_ip(request)

    def page(next_url, *, challenge=False, status=200):
        return render(
            request, 'brand/login.html',
            {'next': next_url, 'challenge': challenge}, status=status,
        )

    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password')
        remember_me = request.POST.get('remember')
        next_url = request.POST.get('next') or request.GET.get('next', '/')
        # An unchecked next turns the sign-in page into a redirect to any
        # site, with our domain in the link.
        if not url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
        ):
            next_url = '/'

        if not email or not password:
            messages.error(request, 'Please fill in all fields.')
            return page(next_url, challenge=login_throttle.needs_challenge(ip))

        # Both refusals below come before any password is hashed: that is
        # the work a bot would otherwise make every real sign-in wait behind.
        if login_throttle.blocked(ip):
            messages.error(
                request,
                'Too many failed sign-in attempts from your network. '
                'Please wait 15 minutes and try again.',
            )
            return page(next_url, status=429)

        user_obj = _login_user_for(email)
        account = user_obj.username if user_obj else email
        if login_throttle.needs_challenge(ip, account) and not turnstile.passed(request):
            messages.error(request, 'Please confirm you are human, then sign in again.')
            return page(next_url, challenge=True, status=400)

        # The raw identifier when nothing matched still runs the backend, so
        # an unknown account costs the same hash as a wrong password and the
        # timing does not say which it was.
        user = authenticate(request, username=account, password=password)

        if user is not None:
            login_throttle.record_success(account)
            login(request, user)
            if not remember_me:
                request.session.set_expiry(0)
            else:
                request.session.set_expiry(1209600)

            return redirect(next_url)

        login_throttle.record_failure(ip, account)
        # Backends refuse inactive accounts, which would otherwise read as
        # a wrong password. Say so only to someone who knows the password,
        # and only for sign-ups: a deactivated staff account gets the
        # generic message, so its old password cannot be confirmed here.
        if (
            user_obj
            and not user_obj.is_active
            and not (user_obj.is_staff or user_obj.is_superuser)
            and user_obj.check_password(password)
        ):
            messages.error(
                request,
                'This account is not active yet. An administrator needs to '
                'invite you before you can sign in.',
            )
        else:
            messages.error(request, 'Invalid email/username or password.')
        return page(next_url, challenge=login_throttle.needs_challenge(ip, account))

    next_url = request.GET.get('next', '/')
    return page(next_url, challenge=login_throttle.needs_challenge(ip))


class PasswordResetView(auth_views.PasswordResetView):
    """Django's reset form, with the bot protection every other public form has.

    Each accepted request sends an email, so unguarded it lets a script fill
    any inbox with reset mail - ours, through our Mailgun quota and sending
    reputation. Three limits, in the order a request meets them:

    - per address: past PASSWORD_RESET_ADDRESS_LIMIT requests an hour the
      network is refused outright;
    - Turnstile on every request, as on sign-up and the contact form;
    - per email: past PASSWORD_RESET_EMAIL_LIMIT an hour no more mail goes to
      that address, however many networks ask. The page still says the email
      is on its way, as it does for an unknown address, so the form never
      tells anyone which addresses have accounts.
    """

    template_name = 'brand/auth/password_reset_form.html'

    PASSWORD_RESET_ADDRESS_LIMIT = 5
    PASSWORD_RESET_EMAIL_LIMIT = 3
    WINDOW_SECONDS = 60 * 60

    def refuse(self, error, status):
        context = self.get_context_data(form=self.get_form(), error=error)
        return self.render_to_response(context, status=status)

    def post(self, request, *args, **kwargs):
        if _rate_limited(
            request, 'password-reset',
            limit=self.PASSWORD_RESET_ADDRESS_LIMIT, window_seconds=self.WINDOW_SECONDS,
        ):
            return self.refuse(
                'Too many reset requests from your network. Please try again in an hour.',
                status=429,
            )
        if not turnstile.passed(request):
            return self.refuse(turnstile.FAILED, status=400)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        if _rate_limited(
            self.request, 'password-reset-email',
            limit=self.PASSWORD_RESET_EMAIL_LIMIT, window_seconds=self.WINDOW_SECONDS,
            subject=form.cleaned_data['email'],
        ):
            return HttpResponseRedirect(self.get_success_url())
        return super().form_valid(form)


def logout_view(request):
    """User logout view"""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('index')


@csrf_exempt
def like_blog_post(request, post_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST request required'}, status=400)
    
    try:
        data = json.loads(request.body)
        browser_id = data.get('browser_id')
    except Exception:
        browser_id = request.POST.get('browser_id')
        
    if not browser_id:
        return JsonResponse({'error': 'browser_id required'}, status=400)

    # browser_id is supplied by the client and nothing binds it to a real
    # visitor, so a script can mint a fresh one per request and like without
    # limit -- and the blog list ranks by likes_count under ?sort=popular.
    # Throttling by address caps how fast that can be done. It does not make
    # the count trustworthy; only a server-issued identity would.
    if _rate_limited(
        request,
        'blog-like',
        limit=settings.BLOG_LIKE_RATE_LIMIT_COUNT,
        window_seconds=settings.BLOG_LIKE_RATE_LIMIT_WINDOW_SECONDS,
    ):
        return JsonResponse(
            {'error': 'Too many requests. Please slow down.'}, status=429
        )

    post = _published_post_or_404(post_id)

    like_qs = BlogLike.objects.filter(post=post, browser_id=browser_id)
    if like_qs.exists():
        like_qs.delete()
        liked = False
    else:
        BlogLike.objects.create(post=post, browser_id=browser_id)
        liked = True
        
    likes_count = post.likes.count()
    return JsonResponse({
        'liked': liked,
        'likes_count': likes_count
    })


@csrf_exempt
def comment_blog_post(request, post_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST request required'}, status=400)

    # Comments are public, unauthenticated and rendered back to every reader,
    # which is exactly the shape spam wants.
    if not turnstile.passed(request):
        return JsonResponse({'error': turnstile.FAILED}, status=400)


    try:
        data = json.loads(request.body)
        browser_id = data.get('browser_id')
        user_name = data.get('user_name', 'Anonymous')
        content = data.get('content')
    except Exception:
        browser_id = request.POST.get('browser_id')
        user_name = request.POST.get('user_name', 'Anonymous')
        content = request.POST.get('content')
        
    if not browser_id or not content:
        return JsonResponse({'error': 'browser_id and content required'}, status=400)

    post = _published_post_or_404(post_id)

    comment = BlogComment.objects.create(
        post=post,
        browser_id=browser_id,
        user_name=user_name or 'Anonymous',
        content=content
    )
    
    return JsonResponse({
        'status': 'success',
        'comment': {
            'id': comment.id,
            'user_name': comment.user_name,
            'content': comment.content,
            'created_at': comment.created_at.strftime('%b %d, %Y at %H:%M')
        }
    })


def get_blog_comments(request, post_id):
    post = _published_post_or_404(post_id)
    # is_approved=True, matching blog_detail() and blog_json(). It defaults to
    # True, so this is not about spam waiting for review -- it is about a
    # comment a moderator has taken down staying readable from the API after
    # it has vanished from the page.
    comments = post.comments.filter(is_approved=True)
    comments_list = [
        {
            'id': c.id,
            'user_name': c.user_name,
            'content': c.content,
            'created_at': c.created_at.strftime('%b %d, %Y at %H:%M')
        }
        for c in comments
    ]
    return JsonResponse({'comments': comments_list})


def blog_json(request, post_id):
    post = _published_post_or_404(post_id)
    content_html = render_markdown(post.content)
    likes_count = post.likes.count()
    
    browser_id = request.GET.get('browser_id')
    user_liked = post.likes.filter(browser_id=browser_id).exists() if browser_id else False
    
    comments = [
        {
            'user_name': c.user_name,
            'content': c.content,
            'created_at': c.created_at.strftime('%b %d, %Y at %H:%M')
        } for c in post.comments.filter(is_approved=True)
    ]
    
    return JsonResponse({
        'id': post.id,
        'title': post.title,
        'category': post.category,
        'image': post.image.url if post.image else None,
        'created_at': post.created_at.strftime('%B %d, %Y'),
        'content_html': content_html,
        'likes_count': likes_count,
        'user_liked': user_liked,
        'comments': comments
    })


def developer_agent_setup(request):
    """Serve developer agent onboarding instructions in Markdown."""
    from staff.models import DeveloperApiKey, StaffProfile

    raw_key = (request.GET.get('key') or request.META.get('HTTP_X_TEKLORA_API_KEY') or '').strip()
    developer = None
    profile = None
    is_valid_key = False

    if raw_key.startswith(DeveloperApiKey.KEY_PREFIX):
        key_hash = DeveloperApiKey.hash_key(raw_key)
        api_key = DeveloperApiKey.objects.filter(key_hash=key_hash, is_active=True).select_related('user').first()
        if api_key and api_key.user.is_active:
            developer = api_key.user
            profile, _ = StaffProfile.objects.get_or_create(user=developer)
            is_valid_key = True

    base_url = request.build_absolute_uri('/').rstrip('/')
    mcp_script_url = f"{base_url}/developer/mcp/server.py"

    return render(
        request,
        'brand/developer_agent_setup.md',
        {
            'developer': developer,
            'profile': profile,
            'key': raw_key if is_valid_key else '<YOUR_TEKLORA_API_KEY>',
            'base_url': base_url,
            'mcp_script_url': mcp_script_url,
            'is_valid_key': is_valid_key,
        },
        content_type='text/markdown; charset=utf-8',
    )


def developer_agent_setup_md(request):
    return developer_agent_setup(request)


def developer_mcp_script(request):
    """Serve the standalone zero-dependency Python MCP server script."""
    import os
    candidates = [
        os.path.join(settings.BASE_DIR, 'scripts', 'teklora_mcp.py'),
        os.path.join(settings.BASE_DIR, 'brandtechsolution', 'scripts', 'teklora_mcp.py'),
    ]
    script_path = None
    for c in candidates:
        if os.path.exists(c):
            script_path = c
            break

    if not script_path:
        raise Http404("MCP script not found.")

    with open(script_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return HttpResponse(content, content_type='text/x-python; charset=utf-8')

